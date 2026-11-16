"""Prototipo de flujo semanal Maxi Carnes. Sin base de datos ni impresión."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import streamlit as st
from empaque import distribuir_por_destino, distribuir_bolsas

st.set_page_config(page_title="Maxi Carnes | Pedidos", page_icon="🏷️", layout="wide")
st.title("Maxi Carnes | Pedidos y etiquetas")
st.caption("Catálogos consultados desde Supabase. Los pedidos todavía son de prueba y no se guardan en la base de datos.")

# Catálogos reales: lectura desde Supabase, únicamente desde el servidor Streamlit.
@st.cache_data(ttl=120, show_spinner="Consultando catálogos de Maxi Carnes...")
def cargar_catalogos():
    url = st.secrets["SUPABASE_URL"].rstrip("/")
    key = st.secrets["SUPABASE_KEY"]
    def consultar(tabla, columnas):
        params = urlencode({"select": columnas, "order": "id.asc", "limit": "1000"})
        req = Request(
            f"{url}/rest/v1/{tabla}?{params}",
            headers={"apikey": key, "Accept": "application/json"},
        )
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    municipios = consultar("municipios", "id,nombre,activo")
    clientes = consultar("clientes", "id,municipio_id,nombre,activo")
    productos = consultar("productos", "id,nombre,activo")
    nombres = {m["id"]: m["nombre"] for m in municipios if m.get("activo", True)}
    agrupados = {nombre: [] for nombre in nombres.values()}
    for cliente in clientes:
        municipio = nombres.get(cliente["municipio_id"])
        if municipio and cliente.get("activo", True):
            agrupados[municipio].append(cliente["nombre"])
    productos_activos = [p["nombre"] for p in productos if p.get("activo", True)]
    return agrupados, productos_activos, len(clientes)

try:
    catalogo_db, productos_db, total_clientes_db = cargar_catalogos()
except (KeyError, HTTPError, URLError, TimeoutError, ValueError) as exc:
    st.warning("Supabase todavía no permite consultar el catálogo. Puedes usar el modo de prueba mientras corregimos el acceso.")
    st.caption(f"Tipo de error: {type(exc).__name__}" + (f" · Código HTTP: {exc.code}" if isinstance(exc, HTTPError) else ""))
    catalogo_db = {
        "Gama": ["Técnico Agropecuario Martín Romero", "Nuestra Señora del Carmen", "Jardín Infantil"],
        "Sibaté": ["Romeral"],
    }
    productos_db = ["GOULASH", "CARNE MOLIDA"]
    total_clientes_db = 0
    st.info("MODO DE PRUEBA: catálogo de ejemplo. Los datos reales permanecen en Supabase; aquí no se muestran hasta resolver el acceso.")

if total_clientes_db:
    st.success(f"Conectado a Supabase: {len(catalogo_db)} municipios, {total_clientes_db} clientes y {len(productos_db)} productos registrados.")
if "municipios" not in st.session_state:
    st.session_state.municipios = catalogo_db
if "productos" not in st.session_state:
    st.session_state.productos = productos_db
if "pedidos" not in st.session_state:
    st.session_state.pedidos = []
if "fila_id" not in st.session_state:
    st.session_state.fila_id = 0

tab_pedidos, tab_catalogo, tab_revision = st.tabs(
    ["1. Formulario por municipio", "2. Municipios, clientes y productos", "3. Revisión semanal"]
)

with tab_catalogo:
    st.subheader("Catálogo de prueba")
    st.warning("Los municipios, clientes y productos se consultan desde Supabase. Las altas realizadas aquí son temporales y NO se guardan en Supabase.")
    with st.form("nuevo_municipio"):
        nuevo_municipio = st.text_input("Crear municipio")
        if st.form_submit_button("Agregar municipio"):
            nombre = nuevo_municipio.strip()
            if not nombre:
                st.error("Escribe un municipio.")
            elif any(m.casefold() == nombre.casefold() for m in st.session_state.municipios):
                st.warning("Ese municipio ya existe.")
            else:
                st.session_state.municipios[nombre] = []
                st.success("Municipio agregado a esta sesión.")
    with st.form("nuevo_cliente"):
        municipio_cliente = st.selectbox("Municipio del nuevo cliente", list(st.session_state.municipios))
        nuevo_cliente = st.text_input("Nombre del cliente (sucursal)")
        if st.form_submit_button("Agregar cliente"):
            nombre = nuevo_cliente.strip()
            existentes = st.session_state.municipios[municipio_cliente]
            if not nombre:
                st.error("Escribe un cliente.")
            elif any(c.casefold() == nombre.casefold() for c in existentes):
                st.warning("Ese cliente ya existe en este municipio.")
            else:
                existentes.append(nombre)
                st.success("Cliente agregado a esta sesión.")
    with st.form("nuevo_producto"):
        nuevo_producto = st.text_input("Crear producto")
        if st.form_submit_button("Agregar producto"):
            nombre = nuevo_producto.strip().upper()
            if not nombre:
                st.error("Escribe un producto.")
            elif nombre in st.session_state.productos:
                st.warning("Ese producto ya existe.")
            else:
                st.session_state.productos.append(nombre)
                st.success("Producto agregado a esta sesión. Aplicará la regla general hasta configurar otra.")

with tab_pedidos:
    st.subheader("Pedido completo de un municipio")
    st.info("Selecciona el municipio y registra todos sus clientes y productos. Un producto con 0 kg o vacío no genera etiquetas.")
    municipio = st.selectbox("Municipio que envía el pedido", list(st.session_state.municipios))
    clientes = st.session_state.municipios[municipio]
    if not clientes:
        st.warning("Este municipio todavía no tiene clientes cargados. Agrégalos en la pestaña 2.")
    else:
        st.write(f"**Clientes registrados:** {len(clientes)}")
        with st.form(f"pedido_{municipio}", clear_on_submit=False):
            filas = []
            for i, cliente in enumerate(clientes):
                st.markdown(f"#### {cliente}")
                cantidad_productos = st.number_input(
                    "Número de productos para este cliente", min_value=1, max_value=12,
                    value=1, step=1, key=f"num_{municipio}_{cliente}"
                )
                for j in range(cantidad_productos):
                    a, b, c, d = st.columns([3, 2, 3, 2])
                    with a:
                        producto = st.selectbox("Producto", st.session_state.productos,
                            key=f"prod_{municipio}_{cliente}_{j}")
                    with b:
                        kilos = st.text_input("Cantidad (kg)", value="",
                            placeholder="Ej. 5,5", key=f"kg_{municipio}_{cliente}_{j}")
                    with c:
                        regla = st.selectbox("Regla de empaque",
                            ["Predeterminada", "Especial (máximo por bolsa)"],
                            key=f"regla_{municipio}_{cliente}_{j}")
                    with d:
                        maximo = st.text_input("Máximo especial (kg)", value="",
                            disabled=regla == "Predeterminada",
                            key=f"max_{municipio}_{cliente}_{j}")
                    filas.append((cliente, producto, kilos, regla, maximo))
                st.divider()
            enviar = st.form_submit_button("Guardar pedido de este municipio (prueba)", type="primary")
        if enviar:
            nuevos, errores = [], []
            for cliente, producto, kilos, regla, maximo in filas:
                texto = kilos.strip().replace(",", ".")
                if not texto:
                    continue
                try:
                    valor = Decimal(texto)
                    if not valor.is_finite() or valor < 0:
                        raise ValueError("Debe ser cero o positivo")
                    if valor == 0:
                        continue
                    if regla == "Predeterminada":
                        bolsas = distribuir_por_destino(str(valor), municipio, producto)
                    else:
                        especial = Decimal(maximo.strip().replace(",", "."))
                        gramos = especial * 1000
                        if not especial.is_finite() or especial <= 0 or gramos != gramos.to_integral_value():
                            raise ValueError("Máximo especial inválido")
                        # El empaque especial nunca debe superar los 2 kg para carne molida de Sibaté.
                        if municipio.casefold() == "sibaté" and producto.upper() == "CARNE MOLIDA" and gramos > 2000:
                            raise ValueError("La carne molida de Sibaté no puede superar 2 kg por bolsa")
                        bolsas = distribuir_bolsas(str(valor), int(gramos), 0)
                    nuevos.append({
                        "Municipio": municipio, "Cliente": cliente, "Producto": producto,
                        "Kilos": str(valor), "Empaque": regla, "Bolsas": bolsas,
                    })
                except (InvalidOperation, ValueError) as exc:
                    errores.append(f"{cliente} / {producto}: {exc}")
            if errores:
                for error in errores:
                    st.error(error)
                st.warning("No se guardó este municipio; corrige los datos y vuelve a intentarlo.")
            else:
                st.session_state.pedidos = [p for p in st.session_state.pedidos if p["Municipio"] != municipio] + nuevos
                st.success(f"Pedido de {municipio} registrado en esta sesión: {len(nuevos)} productos con cantidad positiva.")
                if not nuevos:
                    st.info("Municipio sin cantidades solicitadas: 0 etiquetas.")

with tab_revision:
    st.subheader("Consolidado semanal — simulación")
    st.caption("Los catálogos se leen de Supabase; los pedidos de prueba no se guardan ni se imprimen ni se reciben desde enlaces externos.")
    with st.expander("Datos que Cristian diligenciará antes de generar etiquetas", expanded=True):
        fecha_beneficio = st.date_input("Fecha de beneficio (manual)", value=None, format="DD/MM/YYYY")
        lote = st.text_input("Número de lote (manual)")
        st.write("Fecha de empaque: se fijará al confirmar la generación real de etiquetas.")
        st.write("Fecha de vencimiento: empaque + 30 días calendario (pendiente validación sanitaria).")
    pedidos = st.session_state.pedidos
    municipios_con_pedido = {p["Municipio"] for p in pedidos}
    st.metric("Municipios con cantidades positivas", len(municipios_con_pedido))
    st.metric("Bolsas / etiquetas previstas", sum(len(p["Bolsas"]) for p in pedidos))
    st.metric("Kilos solicitados", f"{sum(Decimal(p['Kilos']) for p in pedidos):.3f}")
    if pedidos:
        st.dataframe([{
            "Municipio": p["Municipio"], "Cliente": p["Cliente"],
            "Producto": p["Producto"], "Kilos": p["Kilos"],
            "Regla": p["Empaque"], "Etiquetas": len(p["Bolsas"]),
            "Pesos de bolsas (g)": ", ".join(map(str, p["Bolsas"])),
        } for p in pedidos], use_container_width=True, hide_index=True)
    else:
        st.info("Todavía no hay pedidos registrados en esta sesión.")
    st.warning("Próximo desarrollo: base de datos, enlaces seguros por municipio, confirmación semanal e impresión Zebra en lote.")
