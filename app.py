"""Pedidos Maxi Carnes: catálogo real y guardado administrativo en Supabase."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
import csv
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
from plantilla_etiqueta import pdf_etiquetas_diseno

st.set_page_config(page_title="Maxi Carnes | Pedidos", page_icon="🏷️", layout="wide")
st.title("Maxi Carnes | Pedidos y etiquetas")
st.caption("Catálogos y pedidos conectados a Supabase.")

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
if "contador_pedidos" not in st.session_state:
    st.session_state.contador_pedidos = 0
if "fila_id" not in st.session_state:
    st.session_state.fila_id = 0

# Pruebas sin contraseña: guardar en la sesión, sin exponer escrituras de Supabase.
# El guardado real requiere un acceso administrativo protegido.
autorizado = bool(total_clientes_db)
with st.sidebar:
    st.subheader("Pedidos")
    st.info("Los pedidos del catálogo real se guardan en Supabase. Las altas de catálogo siguen siendo temporales.")

tab_pedidos, tab_catalogo, tab_revision, tab_bandeja = st.tabs(
    ["1. Formulario por municipio", "2. Municipios, clientes y productos", "3. Revisión semanal", "4. Pedidos recibidos"]
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
            enviar = st.form_submit_button("Guardar pedido", type="primary")
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
                st.session_state.contador_pedidos += 1
                numero = f"MC-{date.today():%Y%m%d}-{st.session_state.contador_pedidos:03d}"
                for p in nuevos:
                    p["Numero pedido"] = numero
                st.session_state.pedidos.extend(nuevos)
                st.success(f"Pedido {numero} registrado en esta sesión. Puedes revisarlo o eliminarlo en Revisión semanal.")
            elif not total_clientes_db:
                st.error("No se permite guardar con el catálogo de ejemplo. Verifica Supabase.")
            else:
                try:
                    mids, cids, pids = ids_catalogo()
                    pedido_guardado = guardar_pedido_real(municipio, nuevos, mids, cids, pids)
                    numero = str(pedido_guardado.get("numero_pedido") or pedido_guardado["id"])
                    for p in nuevos:
                        p["Numero pedido"] = numero
                    st.session_state.pedidos.extend(nuevos)
                    st.success("Pedido guardado permanentemente en Supabase: " + numero)
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
            story.append(par("Conservación: " + (conservacion or "Mantener refrigerado entre 0 °C y 4 °C"), "nota"))
            story.append(par("Procesado y empacado por: MaxiCarnes H&M", "nota"))
            story.append(par("Dirección: " + (direccion or "Calle 3 # 12-74 Tenjo Cundinamarca"), "nota"))
            story.append(par("Instrucciones: " + (instrucciones or "Producto que requiere cocción para su consumo"), "nota"))
            story.append(par("Codigo INVIMA: 233DM (verificar aplicabilidad)", "nota"))
    if not story:
        raise ValueError("No hay bolsas para generar etiquetas.")
    doc.build(story)
    return buffer.getvalue()


def datos_bartender(lineas, numero_pedido, lote, fecha_beneficio, nit, conservacion):
    """Datos delimitados: una fila por etiqueta, para conectar a una plantilla BTW."""
    columnas = ["Pedido", "Municipio", "Cliente", "NIT", "Producto",
                "Peso_kg", "Peso_g", "Bolsa", "Total_bolsas", "Lote",
                "Fecha_beneficio", "Fecha_empaque", "Conservacion",
                "Procesado_por", "Direccion", "Telefono", "Instrucciones"]
    filas = []
    for linea in lineas:
        for i, gramos in enumerate(linea["Bolsas"], 1):
            filas.append([
                numero_pedido, linea["Municipio"], linea["Cliente"], nit,
                linea["Producto"], f"{gramos / 1000:.3f}", str(gramos),
                str(i), str(len(linea["Bolsas"])), lote,
                fecha_beneficio.strftime("%d/%m/%Y") if fecha_beneficio else "",
                date.today().strftime("%d/%m/%Y"), conservacion,
                EMPACADOR, DIRECCION, "3223721832", INSTRUCCIONES,
            ])
    return columnas, filas


def archivo_delimitado(columnas, filas, separador):
    salida = BytesIO()
    from io import StringIO
    texto = StringIO(newline="")
    escritor = csv.writer(texto, delimiter=separador, lineterminator="\\r\\n")
    escritor.writerow(columnas)
    escritor.writerows(filas)
    return texto.getvalue().encode("utf-8-sig")


def consultar_pedido_por_numero(numero):
    """Recupera pedido y detalles de Supabase por número exacto."""
    cabeceras = api_supabase("pedidos", parametros={
        "select": "id,numero_pedido,municipio_id,estado,enviado_en",
        "numero_pedido": "eq." + numero.strip(), "limit": "1"
    })
    if not cabeceras:
        return None, []
    cabecera = cabeceras[0]
    detalles = api_supabase("detalles_pedido", parametros={
        "select": "id,cliente_id,producto_id,gramos,capacidad_especial_gramos",
        "pedido_id": "eq." + str(cabecera["id"]), "limit": "1000"
    })
    mids = api_supabase("municipios", parametros={"select":"id,nombre","id":"eq."+str(cabecera["municipio_id"])})
    if not mids:
        raise ValueError("El municipio del pedido no está disponible")
    municipio = mids[0]["nombre"]
    clientes = api_supabase("clientes", parametros={"select":"id,nombre","municipio_id":"eq."+str(cabecera["municipio_id"]),"limit":"1000"})
    productos = api_supabase("productos", parametros={"select":"id,nombre","limit":"1000"})
    nombres_clientes = {x["id"]:x["nombre"] for x in clientes}
    nombres_productos = {x["id"]:x["nombre"] for x in productos}
    lineas = []
    for d in detalles:
        cliente = nombres_clientes.get(d["cliente_id"], "Cliente no encontrado")
        producto = nombres_productos.get(d["producto_id"], "Producto no encontrado")
        kilos = Decimal(d["gramos"]) / Decimal(1000)
        especial = d.get("capacidad_especial_gramos")
        bolsas = (distribuir_bolsas(str(kilos), int(especial), 0)
                  if especial else distribuir_por_destino(str(kilos), municipio, producto))
        lineas.append({
            "Detalle ID":d["id"],"Numero pedido":cabecera["numero_pedido"],"Municipio":municipio,
            "Cliente":cliente,"Producto":producto,"Kilos":str(kilos),
            "Empaque":"Especial" if especial else "Predeterminada",
            "Bolsas":bolsas,"Capacidad especial":especial
        })
    return cabecera, lineas


def listar_pedidos_guardados():
    """Consulta cabeceras recientes, independientemente de la sesión del navegador."""
    registros = api_supabase("pedidos", parametros={
        "select":"id,numero_pedido,municipio_id,estado,enviado_en,impreso_en",
        "order":"enviado_en.desc","limit":"500"
    })
    municipios = api_supabase("municipios", parametros={"select":"id,nombre","limit":"1000"})
    nombres = {m["id"]:m["nombre"] for m in municipios}
    return [{
        "Número":p.get("numero_pedido") or str(p["id"]),
        "Municipio":nombres.get(p["municipio_id"],"No encontrado"),
        "Fecha de creación":p.get("enviado_en",""),
        "Estado":p.get("estado","enviado"),
        "Fecha de impresión":p.get("impreso_en") or "Sin confirmar",
    } for p in registros]


with tab_revision:
    st.subheader("Consultar pedidos guardados")
    st.caption("Consulta pedidos por su número único. Los cambios y anulaciones de pedidos históricos todavía no están habilitados.")
    with st.expander("Datos que Cristian diligenciará antes de generar etiquetas", expanded=True):
        fecha_beneficio = st.date_input("Fecha de beneficio (manual)", value=None, format="DD/MM/YYYY")
        lote = st.text_input("Número de lote (manual)")
        st.write("Fecha de empaque: se fijará al confirmar la generación real de etiquetas.")
        st.write("Fecha de vencimiento: empaque + 30 días calendario (pendiente validación sanitaria).")
    st.markdown("#### Buscar un pedido en Supabase")
    numero_busqueda = st.text_input("Número de pedido guardado (ej. MC-2026-000001)", key="numero_busqueda")
    if st.button("Consultar pedido guardado"):
        if not numero_busqueda.strip():
            st.warning("Ingresa el número del pedido.")
        else:
            try:
                cabecera, lineas_guardadas = consultar_pedido_por_numero(numero_busqueda)
                if cabecera:
                    st.session_state.pedido_consultado = cabecera
                    st.session_state.lineas_consultadas = lineas_guardadas
                    st.success(f"Pedido {cabecera['numero_pedido']} encontrado. Estado: {cabecera['estado']}.")
                else:
                    st.session_state.pop("pedido_consultado", None)
                    st.session_state.pop("lineas_consultadas", None)
                    st.warning("No se encontró ese número en Supabase.")
            except (HTTPError, URLError, KeyError, ValueError, TimeoutError) as exc:
                st.error(f"No se pudo consultar Supabase: {exc}")
    if st.session_state.get("pedido_consultado"):
        st.caption("Pedido recuperado de la base de datos. Puedes revisar sus productos y generar sus etiquetas.")
    todos_los_pedidos = st.session_state.pedidos
    numeros = list(dict.fromkeys(p.get("Numero pedido", "SIN NÚMERO") for p in todos_los_pedidos))
    numero_seleccionado = st.selectbox("Selecciona el pedido para revisar, imprimir o eliminar", numeros) if numeros else None
    pedidos = [p for p in todos_los_pedidos if p.get("Numero pedido", "SIN NÚMERO") == numero_seleccionado] if numero_seleccionado else []
    if st.session_state.get("pedido_consultado"):
        pedidos = st.session_state.get("lineas_consultadas", [])
        numero_seleccionado = st.session_state["pedido_consultado"]["numero_pedido"]
    if numero_seleccionado and not st.session_state.get("pedido_consultado"):
        with st.expander("Eliminar pedido", expanded=False):
            st.warning("Solo se quita de esta vista. El pedido real permanece guardado en Supabase.")
            confirmar_borrado = st.checkbox("Confirmo que deseo eliminar este pedido", key="confirmar_borrado")
            if st.button("Quitar de esta vista", disabled=not confirmar_borrado):
                st.session_state.pedidos = [p for p in st.session_state.pedidos if p.get("Numero pedido", "SIN NÚMERO") != numero_seleccionado]
                st.rerun()
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
    if pedidos:
        st.markdown("#### Seleccionar etiquetas específicas")
        opciones_etiquetas = []
        for i, linea in enumerate(pedidos):
            for j, peso in enumerate(linea["Bolsas"]):
                opciones_etiquetas.append((i, j, f'{linea["Cliente"]} | {linea["Producto"]} | Bolsa {j+1}/{len(linea["Bolsas"])} | {peso} g'))
        claves = [f"{i}:{j}" for i,j,_ in opciones_etiquetas]
        titulos = {f"{i}:{j}": titulo for i,j,titulo in opciones_etiquetas}
        modo_impresion = st.radio("Qué etiquetas generar", ["Todas las etiquetas del pedido", "Solo las etiquetas seleccionadas"], horizontal=True)
        if modo_impresion == "Solo las etiquetas seleccionadas":
            elegidas = st.multiselect("Selecciona las bolsas que necesitas reimprimir", claves, format_func=lambda k: titulos[k])
            etiquetas_para_pdf = []
            for i,j,_ in opciones_etiquetas:
                if f"{i}:{j}" in elegidas:
                    copia = dict(pedidos[i])
                    copia["Bolsas"] = [pedidos[i]["Bolsas"][j]]
                    etiquetas_para_pdf.append(copia)
        else:
            etiquetas_para_pdf = pedidos
        if st.session_state.get("pedido_consultado"):
            with st.expander("Corregir cantidades del pedido guardado", expanded=False):
                st.warning("Las correcciones cambian el pedido en Supabase. Revisa los pesos antes de confirmar. No modifica el historial de impresiones.")
                for indice, linea in enumerate(pedidos):
                    if "Detalle ID" not in linea:
                        continue
                    with st.form(f"corregir_{linea['Detalle ID']}"):
                        st.write(f'{linea["Cliente"]} — {linea["Producto"]}')
                        nuevo_peso = st.text_input("Cantidad total en kg", value=linea["Kilos"], key=f'editar_{linea["Detalle ID"]}')
                        confirmar = st.checkbox("Confirmo esta corrección", key=f'confirmar_{linea["Detalle ID"]}')
                        if st.form_submit_button("Guardar corrección"):
                            if not confirmar:
                                st.error("Confirma la corrección antes de guardar.")
                            else:
                                try:
                                    gramos_nuevos = convertir_a_gramos(nuevo_peso)
                                    api_supabase("detalles_pedido", "PATCH", {"gramos": gramos_nuevos}, {"id": "eq."+str(linea["Detalle ID"])})
                                    cabecera, nuevas_lineas = consultar_pedido_por_numero(st.session_state["pedido_consultado"]["numero_pedido"])
                                    st.session_state.lineas_consultadas = nuevas_lineas
                                    st.success("Cantidad actualizada en Supabase. Se recalcularon las bolsas.")
                                    st.rerun()
                                except (HTTPError, URLError, ValueError, KeyError, TimeoutError) as exc:
                                    st.error(f"No se pudo guardar la corrección: {exc}")
    else:
        etiquetas_para_pdf = []
    st.divider()
    st.subheader("Imprimir etiquetas PDF - 10 x 10 cm")
    st.caption("Plantilla con logo y cuadrícula del diseño aprobado. Una página de 10 x 10 cm por bolsa. Confirmar vigencia sanitaria del código INVIMA, conservación y vencimiento antes de uso comercial.")
    with st.expander("Datos de las etiquetas", expanded=True):
        numero_preview = st.text_input("Número del pedido", value=numero_seleccionado or "", disabled=True)
        nit_preview = st.text_input("NIT del municipio (opcional)")
        st.text_input("Procesado y empacado por (predeterminado)", value=EMPACADOR, disabled=True)
        direccion_preview = st.text_input("Dirección de procesado y empacado (predeterminada)", value=DIRECCION, disabled=True)
        conservacion_preview = st.text_input("Condiciones de conservación (predeterminadas)", value="Mantener refrigerado entre 0 °C y 4 °C", disabled=True)
        instrucciones_preview = st.text_input("Instrucciones de uso (predeterminadas)", value=INSTRUCCIONES, disabled=True)
    if etiquetas_para_pdf:
        try:
            pdf = pdf_etiquetas_diseno(
                etiquetas_para_pdf, numero_pedido=numero_preview, lote=lote,
                fecha_beneficio=fecha_beneficio, nit=nit_preview,
                direccion=direccion_preview, conservacion=conservacion_preview,
                instrucciones=instrucciones_preview)
            st.download_button(
                "Descargar etiquetas en PDF (10 x 10 cm)",
                data=pdf,
                file_name="maxicarnes_etiquetas_100x100.pdf",
                mime="application/pdf",
                type="primary")
            st.info("Abre el PDF en el computador conectado a la impresora SAT TT448-2 USE. Selecciona papel 100 x 100 mm, escala 100 % o tamaño real, sin ajustar a página. Imprime primero una etiqueta de prueba.")
        except Exception as exc:
            st.error(f"No se pudo generar el archivo: {exc}")
    else:
        st.info("Selecciona al menos una etiqueta o consulta un pedido para generar el PDF.")
    st.warning("Pendiente: edición, anulación, historial de impresiones y control de acceso administrativo. No compartas aún esta vista con clientes.")

with tab_bandeja:
    st.subheader("Pedidos recibidos de todos los municipios")
    st.caption("Información consultada directamente desde Supabase, no desde esta sesión. El estado impreso solo cambia cuando se confirma una impresión; descargar un PDF no equivale a imprimir.")
    if st.button("Actualizar pedidos recibidos", type="primary"):
        st.rerun()
    try:
        registros = listar_pedidos_guardados()
        pendientes = [p for p in registros if p["Estado"] != "impreso"]
        impresos = [p for p in registros if p["Estado"] == "impreso"]
        a,b,c = st.columns(3)
        a.metric("Pedidos recibidos", len(registros))
        b.metric("Pendientes / sin confirmar", len(pendientes))
        c.metric("Marcados como impresos", len(impresos))
        filtro = st.selectbox("Mostrar pedidos", ["Todos","Pendientes / sin confirmar","Impresos"])
        visibles = registros if filtro == "Todos" else (impresos if filtro == "Impresos" else pendientes)
        if visibles:
            st.dataframe(visibles, hide_index=True, use_container_width=True)
            opciones = [p["Número"] for p in visibles]
            elegido = st.selectbox("Pedido que deseas abrir", opciones, key="pedido_bandeja")
            if st.button("Abrir pedido y ver productos", type="primary", key="abrir_pedido_bandeja"):
                try:
                    cabecera, lineas = consultar_pedido_por_numero(elegido)
                    if cabecera:
                        st.session_state["bandeja_abierto"] = cabecera
                        st.session_state["bandeja_lineas"] = lineas
                    else:
                        st.error("El pedido no se encontró en Supabase.")
                except (HTTPError, URLError, KeyError, ValueError, TimeoutError) as exc:
                    st.error(f"No se pudo abrir el pedido: {exc}")
            abierto = st.session_state.get("bandeja_abierto")
            if abierto:
                lineas = st.session_state.get("bandeja_lineas", [])
                st.markdown(f'### Pedido {abierto["numero_pedido"]}')
                st.write(f'**Fecha de creación:** {abierto.get("enviado_en") or "No registrada"}  |  **Estado:** {abierto.get("estado") or "Sin estado"}')
                if lineas:
                    st.dataframe([{
                        "Municipio":p["Municipio"], "Cliente":p["Cliente"],
                        "Producto":p["Producto"], "Kilos":p["Kilos"],
                        "Bolsas":len(p["Bolsas"]),
                        "Pesos (g)":", ".join(map(str,p["Bolsas"]))
                    } for p in lineas], use_container_width=True, hide_index=True)
                    st.metric("Etiquetas previstas",sum(len(p["Bolsas"]) for p in lineas))
                    st.markdown("#### Corregir una cantidad")
                    st.caption("Las correcciones se guardan en Supabase. Verifica la cantidad antes de confirmar.")
                    detalle_opciones = {str(p["Detalle ID"]):p for p in lineas if "Detalle ID" in p}
                    if detalle_opciones:
                        detalle_id = st.selectbox(
                            "Cliente y producto a modificar", list(detalle_opciones),
                            format_func=lambda k: detalle_opciones[k]["Cliente"]+" — "+detalle_opciones[k]["Producto"],
                            key="detalle_editar_bandeja")
                        linea_editar = detalle_opciones[detalle_id]
                        with st.form("editar_cantidad_bandeja"):
                            kilos_nuevos = st.text_input("Cantidad en kilos", value=linea_editar["Kilos"])
                            confirmar_cambio = st.checkbox("Confirmo la corrección de esta cantidad")
                            if st.form_submit_button("Guardar cantidad corregida"):
                                if not confirmar_cambio:
                                    st.error("Debes confirmar la corrección.")
                                else:
                                    try:
                                        gramos_nuevos = convertir_a_gramos(kilos_nuevos)
                                        if gramos_nuevos <= 0:
                                            raise ValueError("La cantidad debe ser mayor que cero.")
                                        api_supabase("detalles_pedido", "PATCH", {"gramos":gramos_nuevos},
                                                     {"id":"eq."+detalle_id})
                                        _, actualizadas = consultar_pedido_por_numero(abierto["numero_pedido"])
                                        st.session_state["bandeja_lineas"] = actualizadas
                                        st.success("Cantidad actualizada en Supabase.")
                                        st.rerun()
                                    except (HTTPError, URLError, KeyError, ValueError, TimeoutError) as exc:
                                        st.error(f"No se pudo guardar la corrección: {exc}")
                    st.markdown("#### Imprimir o reimprimir etiquetas")
                    opciones_bolsas = {}
                    for i,p in enumerate(lineas):
                        for j,peso in enumerate(p["Bolsas"]):
                            clave = f"{i}:{j}"
                            opciones_bolsas[clave] = f'{p["Cliente"]} — {p["Producto"]} — Bolsa {j+1} de {len(p["Bolsas"])} — {peso} g'
                    tipo = st.radio("Qué deseas imprimir", ["Pedido completo", "Solo etiquetas seleccionadas"],
                                    key="tipo_impresion_bandeja", horizontal=True)
                    elegidas = list(opciones_bolsas)
                    if tipo == "Solo etiquetas seleccionadas":
                        elegidas = st.multiselect("Elige las etiquetas",list(opciones_bolsas),
                                                  format_func=lambda k: opciones_bolsas[k],
                                                  key="etiquetas_bandeja")
                    seleccionadas = []
                    for clave in elegidas:
                        i,j = (int(x) for x in clave.split(":"))
                        linea = dict(lineas[i])
                        linea["Bolsas"] = [lineas[i]["Bolsas"][j]]
                        seleccionadas.append(linea)
                    # Recuperar los datos de la etiqueta por pedido, incluso en otra sesión.
                    numero_actual = abierto["numero_pedido"]
                    try:
                        guardados = api_supabase("datos_etiqueta_pedido", parametros={
                            "select":"numero_pedido,fecha_beneficio,lote,nit",
                            "numero_pedido":"eq."+numero_actual,"limit":"1"})
                    except HTTPError as exc:
                        if exc.code == 404:
                            guardados = []
                            st.warning("Falta crear la tabla de datos de etiquetas en Supabase para conservar estos campos entre sesiones.")
                        else:
                            raise
                    datos_previos = guardados[0] if guardados else {}
                    with st.form("datos_pdf_bandeja"):
                        fecha_anterior = date.fromisoformat(datos_previos["fecha_beneficio"]) if datos_previos.get("fecha_beneficio") else None
                        fecha_b = st.date_input("Fecha de beneficio",value=fecha_anterior,format="DD/MM/YYYY")
                        lote_b = st.text_input("Lote (obligatorio)",value=datos_previos.get("lote") or "")
                        nit_b = st.text_input("NIT del municipio (opcional)",value=datos_previos.get("nit") or "")
                        imprimir_pdf = st.form_submit_button("Guardar datos y preparar etiquetas seleccionadas")
                    if imprimir_pdf:
                        if not seleccionadas:
                            st.error("Selecciona al menos una etiqueta.")
                        elif not fecha_b or not lote_b.strip():
                            st.error("Completa la fecha de beneficio y el lote. El NIT es opcional.")
                        else:
                            try:
                                payload = {"numero_pedido":numero_actual,
                                           "fecha_beneficio":fecha_b.isoformat(),
                                           "lote":lote_b.strip(),"nit":nit_b.strip()}
                                if guardados:
                                    api_supabase("datos_etiqueta_pedido","PATCH",payload,
                                                 {"numero_pedido":"eq."+numero_actual})
                                else:
                                    api_supabase("datos_etiqueta_pedido","POST",payload)
                                st.session_state["pdf_bandeja"] = pdf_etiquetas_diseno(
                                    seleccionadas, numero_pedido=numero_actual,
                                    lote=lote_b, fecha_beneficio=fecha_b, nit=nit_b,
                                    conservacion="Mantener refrigerado entre 0 °C y 4 °C",
                                    instrucciones="Producto que requiere cocción para su consumo",
                                    direccion=DIRECCION)
                                st.session_state["pdf_bandeja_numero"] = numero_actual
                                st.success("Datos de la etiqueta guardados en Supabase para futuras modificaciones y reimpresiones.")
                            except (HTTPError, URLError, ValueError, KeyError, TimeoutError) as exc:
                                st.error(f"No se pudieron guardar los datos de la etiqueta: {exc}")
                    if (st.session_state.get("pdf_bandeja") and
                        st.session_state.get("pdf_bandeja_numero")==abierto["numero_pedido"]):
                        st.download_button("Descargar PDF de las etiquetas elegidas",
                                           data=st.session_state["pdf_bandeja"],
                                           file_name=abierto["numero_pedido"]+"_etiquetas.pdf",
                                           mime="application/pdf",type="primary")
                    st.caption("Descargar el PDF no marca el pedido como impreso. El registro de impresiones está pendiente.")

                else:
                    st.warning("Este pedido existe, pero no contiene productos guardados.")

        else:
            st.info("No hay pedidos en esta categoría.")
        st.warning("Esta bandeja es una vista inicial. Antes de compartir la aplicación con clientes debemos proteger el acceso a la información administrativa.")
    except (HTTPError, URLError, KeyError, ValueError, TimeoutError) as exc:
        st.error(f"No se pudieron cargar los pedidos de Supabase: {exc}")
