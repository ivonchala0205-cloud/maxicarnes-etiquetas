"""Pedidos Maxi Carnes: catálogo real y guardado administrativo en Supabase."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
import hmac
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
from reportlab.lib.units import mm
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import streamlit as st
from empaque import distribuir_por_destino, distribuir_bolsas, convertir_a_gramos
from etiquetas_zpl import generar_zpl, DIRECCION, INSTRUCCIONES, EMPACADOR

st.set_page_config(page_title="Maxi Carnes | Pedidos", page_icon="🏷️", layout="wide")
st.title("Maxi Carnes | Pedidos y etiquetas")
st.caption("Catálogos desde Supabase. Guardado permanente disponible solo en modo administrador autorizado.")

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

def api_supabase(tabla, metodo="GET", datos=None, parametros=None):
    """Acceso solo desde servidor; nunca enviar la clave al navegador."""
    url = st.secrets["SUPABASE_URL"].rstrip("/")
    key = st.secrets["SUPABASE_KEY"]
    destino = f"{url}/rest/v1/{tabla}"
    if parametros:
        destino += "?" + urlencode(parametros)
    headers = {"apikey": key, "Accept": "application/json"}
    cuerpo = None
    if datos is not None:
        cuerpo = json.dumps(datos).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=representation"
    req = Request(destino, data=cuerpo, headers=headers, method=metodo)
    with urlopen(req, timeout=25) as resp:
        texto = resp.read().decode("utf-8")
        return json.loads(texto) if texto else []


def guardar_pedido_real(municipio, lineas, municipios_db, clientes_db, productos_db):
    """Guarda cabecera y detalles. Limpia la cabecera si fallan los detalles."""
    semanas = api_supabase("semanas", parametros={
        "select": "id", "abierta": "eq.true", "order": "fecha_inicio.desc", "limit": "1"
    })
    if not semanas:
        raise ValueError("No existe una semana abierta en Supabase.")
    municipio_id = municipios_db[municipio]
    semana_id = semanas[0]["id"]
    detalles = []
    for linea in lineas:
        cliente_id = clientes_db.get((municipio_id, linea["Cliente"]))
        producto_id = productos_db.get(linea["Producto"])
        if cliente_id is None or producto_id is None:
            raise ValueError("Cliente o producto no encontrado en el catálogo real.")
        detalles.append({
            "cliente_id": cliente_id,
            "producto_id": producto_id,
            "gramos": convertir_a_gramos(linea["Kilos"]),
            "capacidad_especial_gramos": (
                linea["Capacidad especial"] if linea["Empaque"] != "Predeterminada" else None
            ),
            "aprobado_especial": False
        })
    creados = api_supabase("pedidos", "POST", {
        "semana_id": semana_id, "municipio_id": municipio_id, "estado": "enviado"
    })
    if not creados:
        raise ValueError("Supabase no devolvió el pedido creado.")
    pedido = creados[0]
    try:
        api_supabase("detalles_pedido", "POST", [
            dict(detalle, pedido_id=pedido["id"]) for detalle in detalles
        ])
    except Exception:
        try:
            api_supabase("pedidos", "DELETE", parametros={"id": f'eq.{pedido["id"]}'})
        except Exception:
            raise RuntimeError(
                "Falló el guardado de detalles y no se pudo confirmar la limpieza. "
                "Revisar el pedido en Supabase antes de reintentar."
            )
        raise
    return pedido


@st.cache_data(ttl=120)
def ids_catalogo():
    municipios = api_supabase("municipios", parametros={"select": "id,nombre,activo", "limit": "1000"})
    clientes = api_supabase("clientes", parametros={"select": "id,municipio_id,nombre,activo", "limit": "1000"})
    productos = api_supabase("productos", parametros={"select": "id,nombre,activo", "limit": "1000"})
    mids = {m["nombre"]: m["id"] for m in municipios if m.get("activo", True)}
    cids = {(c["municipio_id"], c["nombre"]): c["id"] for c in clientes if c.get("activo", True)}
    pids = {p["nombre"]: p["id"] for p in productos if p.get("activo", True)}
    return mids, cids, pids


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

# Pruebas sin contraseña: guardar en la sesión, sin exponer escrituras de Supabase.
# El guardado real requiere un acceso administrativo protegido.
autorizado = False
with st.sidebar:
    st.subheader("Modo de prueba")
    st.info("Sin contraseña: puedes crear pedidos de prueba y descargar sus etiquetas. No se guardan en Supabase.")

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
            enviar = st.form_submit_button("Guardar pedido de prueba", type="primary")
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
                        "Capacidad especial": int(gramos) if regla != "Predeterminada" else None,
                    })
                except (InvalidOperation, ValueError) as exc:
                    errores.append(f"{cliente} / {producto}: {exc}")
            if errores:
                for error in errores:
                    st.error(error)
                st.warning("No se guardó este municipio; corrige los datos y vuelve a intentarlo.")
            elif not nuevos:
                st.warning("No hay cantidades positivas. No se creó ningún pedido.")
            elif not autorizado:
                st.session_state.pedidos = [p for p in st.session_state.pedidos if p["Municipio"] != municipio] + nuevos
                st.success("Pedido de prueba guardado en esta sesión. Ve a Revisión semanal para descargar las etiquetas 10 × 10 cm.")
            elif not total_clientes_db:
                st.error("No se permite guardar con el catálogo de ejemplo. Verifica Supabase.")
            else:
                try:
                    mids, cids, pids = ids_catalogo()
                    pedido_guardado = guardar_pedido_real(municipio, nuevos, mids, cids, pids)
                    st.session_state.pedidos = [p for p in st.session_state.pedidos if p["Municipio"] != municipio] + nuevos
                    st.success("Pedido guardado en Supabase: " + str(pedido_guardado.get("numero_pedido") or pedido_guardado["id"]))
                    st.info("Cada envío crea un pedido nuevo, incluso en la misma semana. Impresión aún no disponible.")
                except (HTTPError, URLError, KeyError, ValueError, RuntimeError, TimeoutError) as exc:
                    st.error("No se pudo confirmar el guardado. Revisa Supabase antes de reintentar.")
                    st.caption(f"Error: {type(exc).__name__}" + (f" (HTTP {exc.code})" if isinstance(exc, HTTPError) else f": {exc}"))

def pdf_etiquetas(lineas, numero_pedido="VISTA PREVIA", lote="", fecha_beneficio=None,
                  fecha_empaque=None, nit="", direccion="", conservacion="", instrucciones=""):
    """Una página de 100 x 100 mm por bolsa. No supone datos sanitarios faltantes."""
    buffer = BytesIO()
    fecha_empaque = fecha_empaque or date.today()
    estilos = {
        "titulo": ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=11, leading=12, alignment=TA_CENTER, spaceAfter=5),
        "principal": ParagraphStyle("principal", fontName="Helvetica-Bold", fontSize=9, leading=11, spaceAfter=4),
        "dato": ParagraphStyle("dato", fontName="Helvetica", fontSize=7.5, leading=9.5, spaceAfter=3),
        "nota": ParagraphStyle("nota", fontName="Helvetica", fontSize=6.5, leading=8, spaceAfter=3),
    }
    doc = SimpleDocTemplate(buffer, pagesize=(100 * mm, 100 * mm),
        leftMargin=6 * mm, rightMargin=6 * mm, topMargin=6 * mm, bottomMargin=6 * mm)
    story = []
    def par(texto, estilo="dato"):
        return Paragraph(escape(str(texto)), estilos[estilo])
    for linea in lineas:
        for indice, gramos in enumerate(linea["Bolsas"], 1):
            if story:
                from reportlab.platypus import PageBreak
                story.append(PageBreak())
            story.append(par("MAXI CARNE - ETIQUETA DE PRUEBA", "titulo"))
            story.append(par(linea["Producto"], "principal"))
            story.append(par("Municipio: " + linea["Municipio"]))
            story.append(par("Cliente / sucursal: " + linea["Cliente"]))
            if nit.strip():
                story.append(par("NIT del municipio: " + nit.strip()))
            story.append(par(f"Peso neto: {gramos / 1000:.3f} kg ({gramos} g)", "principal"))
            story.append(par(f"Pedido: {numero_pedido} | Bolsa: {indice}/{len(linea['Bolsas'])}"))
            story.append(par("Lote: " + (lote or "PENDIENTE")))
            story.append(par("Fecha de beneficio: " + (fecha_beneficio.strftime("%d/%m/%Y") if fecha_beneficio else "PENDIENTE")))
            story.append(par("Fecha de empaque: " + fecha_empaque.strftime("%d/%m/%Y")))
            story.append(par("Vencimiento: PENDIENTE DE VALIDACION SANITARIA"))
            story.append(par("Conservacion: " + (conservacion or "PENDIENTE DE CONFIRMAR"), "nota"))
            story.append(par("Procesado y empacado por: Maxi Carne", "nota"))
            story.append(par("Direccion: " + (direccion or "PENDIENTE DE CONFIRMAR"), "nota"))
            story.append(par("Instrucciones: " + (instrucciones or "PENDIENTES DE CONFIRMAR"), "nota"))
            story.append(par("Codigo INVIMA: 233DM (verificar aplicabilidad)", "nota"))
    if not story:
        raise ValueError("No hay bolsas para generar etiquetas.")
    doc.build(story)
    return buffer.getvalue()


with tab_revision:
    st.subheader("Consolidado de esta sesión")
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
    st.divider()
    st.subheader("Archivo de impresión ZPL - etiquetas 10 x 10 cm")
    st.caption("Archivo de prueba desde esta sesión; no marca pedidos como impresos. El diseño definitivo con logo gráfico y datos sanitarios validados está pendiente.")
    with st.expander("Datos para la prueba de impresión", expanded=True):
        numero_preview = st.text_input("Número del pedido (referencia de prueba)", value="PRUEBA")
        nit_preview = st.text_input("NIT del municipio (opcional)")
        st.text_input("Procesado y empacado por (predeterminado)", value=EMPACADOR, disabled=True)
        direccion_preview = st.text_input("Dirección de procesado y empacado (predeterminada)", value=DIRECCION, disabled=True)
        conservacion_preview = st.text_input("Condiciones de conservación (verificar)")
        instrucciones_preview = st.text_input("Instrucciones de uso (predeterminadas)", value=INSTRUCCIONES, disabled=True)
    if pedidos:
        try:
            zpl = generar_zpl(pedidos, numero_pedido=numero_preview,
                lote=lote, fecha_beneficio=fecha_beneficio,
                nit=nit_preview, conservacion=conservacion_preview)
            st.download_button("Descargar archivo ZPL de prueba (100 x 100 mm)",
                data=zpl, file_name="maxicarnes_etiquetas_prueba_100x100.zpl",
                mime="application/octet-stream", type="primary")
            st.info("Archivo ZPL para probar con la SAT TT448-2 USE (ZPL), 203 dpi. No se carga como diseño editable de BarTender; se envía con una utilidad compatible ZPL. Probar primero una sola etiqueta. El logo es texto provisional.")
        except Exception as exc:
            st.error(f"No se pudo generar el PDF: {exc}")
    else:
        st.info("Para generar un PDF de prueba, introduce cantidades en el formulario y pulsa Guardar pedido. Sin contraseña, quedará solo en esta sesión.")
    st.warning("Pendiente: imprimir desde pedidos históricos de Supabase, registrar impresión y reimprimir etiquetas específicas.")
