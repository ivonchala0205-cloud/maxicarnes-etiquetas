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
    try:
        with urlopen(req, timeout=25) as resp:
            texto = resp.read().decode("utf-8")
            return json.loads(texto) if texto else []
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")[:700]
        raise ValueError(f"Supabase rechazó la operación {metodo} en {tabla} (HTTP {exc.code}): {detalle}") from exc


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
    ["1. Formulario por municipio", "2. Municipios, clientes y productos", "3. Pendientes de impresión", "4. Impresos e historial"]
)

with st.expander("Importar Excel original de Cristian (por hojas)", expanded=False):
    st.caption("Reconoce cada hoja como municipio, identifica productos y cantidades y permite revisar antes de crear pedidos. No modifica pedidos existentes.")
    archivo = st.file_uploader("Subir el Excel original", type=["xlsx"], key="excel_pedidos")
    if archivo:
        import pandas as pd
        import unicodedata
        def normalizar(valor):
            txt = unicodedata.normalize("NFKD", str(valor or "").strip())
            return " ".join("".join(ch for ch in txt if not unicodedata.combining(ch)).upper().split())
        try:
            libro = pd.read_excel(archivo, sheet_name=None, header=None)
            mids, cids, pids = ids_catalogo()
            mapa_m = {normalizar(k): k for k in mids}
            mapa_p = {normalizar(k): k for k in pids}
            mapa_c = {(mid, normalizar(nombre)): nombre for (mid,nombre) in cids}
            grupos, errores_excel = {}, []
            for hoja, df in libro.items():
                if "TOTAL" in normalizar(hoja) or "RESUMEN" in normalizar(hoja):
                    continue
                municipio_excel = mapa_m.get(normalizar(hoja))
                if not municipio_excel:
                    errores_excel.append(f"Hoja {hoja}: municipio no registrado")
                    continue
                producto = None
                columnas = []
                for columna in range(df.shape[1]):
                    encabezado = df.iat[0,columna] if df.shape[0] else ""
                    if pd.notna(encabezado) and "CARNE" in normalizar(encabezado):
                        encabezado_normal = normalizar(encabezado)
                        producto = mapa_p.get(encabezado_normal)
                        if not producto and "MOLIDA" in encabezado_normal:
                            producto = next((nombre for nombre in pids if "MOLIDA" in normalizar(nombre)),None)
                        if not producto and "GOULASH" in encabezado_normal:
                            producto = next((nombre for nombre in pids if "GOULASH" in normalizar(nombre)),None)
                        if not producto:
                            errores_excel.append(f"Hoja {hoja}: producto no registrado: {encabezado}")
                            continue
                        columnas.append((columna, producto))
                if not columnas and normalizar(hoja) == "UBALA":
                    continue
                for col, producto in columnas:
                    for fila in range(3,df.shape[0]):
                        cliente_raw = df.iat[fila,col]
                        if pd.isna(cliente_raw) or not str(cliente_raw).strip():
                            continue
                        cliente_txt = normalizar(cliente_raw)
                        if "TOTAL" in cliente_txt or "OBSERVACION" in cliente_txt or "RECOMIENDA" in cliente_txt:
                            continue
                        col_gramos = col+1
                        col_kilos = col+2
                        gramos_raw = df.iat[fila,col_gramos] if col_gramos < df.shape[1] else None
                        kilos_raw = df.iat[fila,col_kilos] if col_kilos < df.shape[1] else None
                        try:
                            if pd.notna(gramos_raw) and str(gramos_raw).strip():
                                gramos = int(round(float(gramos_raw)))
                            elif pd.notna(kilos_raw) and str(kilos_raw).strip():
                                gramos = int(round(float(kilos_raw)*1000))
                            else:
                                continue
                            if gramos <= 0:
                                continue
                            cliente = mapa_c.get((mids[municipio_excel],cliente_txt))
                            if not cliente:
                                errores_excel.append(f"{hoja}, fila {fila+1}: cliente no registrado: {cliente_raw}")
                                continue
                            kilos = str(Decimal(gramos)/1000)
                            grupos.setdefault(municipio_excel,[]).append({
                                "Municipio":municipio_excel,"Cliente":cliente,
                                "Producto":producto,"Kilos":kilos,"Empaque":"Predeterminada",
                                "Bolsas":distribuir_por_destino(kilos,municipio_excel,producto),
                                "Capacidad especial":None})
                        except (ValueError,TypeError,InvalidOperation) as exc:
                            errores_excel.append(f"{hoja}, fila {fila+1}: cantidad inválida ({exc})")
            if errores_excel:
                st.error("Hay datos sin reconocer. No se permitirá guardar hasta corregirlos.")
                st.dataframe(pd.DataFrame({"Observaciones":errores_excel}),hide_index=True)
            elif not grupos:
                st.warning("No se encontraron cantidades para importar.")
            else:
                st.success(f"Reconocidos {len(grupos)} municipios y {sum(map(len,grupos.values()))} registros.")
                for municipio_revision, lineas_revision in grupos.items():
                    if normalizar(municipio_revision) == "SIBATE":
                        st.info("Sibaté — productos detectados: "+", ".join(
                            f"{producto}: {sum(Decimal(p['Kilos']) for p in lineas_revision if p['Producto']==producto)} kg"
                            for producto in dict.fromkeys(p["Producto"] for p in lineas_revision)))
                opciones = ["Todos los municipios"] + list(grupos)
                filtro = st.selectbox("Qué deseas cargar",opciones)
                seleccion = grupos if filtro == "Todos los municipios" else {filtro:grupos[filtro]}
                filas = [{"Municipio":m,"Cliente":p["Cliente"],"Producto":p["Producto"],"Kilos":float(p["Kilos"])}
                         for m,items in seleccion.items() for p in items]
                st.caption("Revisa y corrige las cantidades antes de generar el pedido.")
                editadas = st.data_editor(pd.DataFrame(filas),hide_index=True,use_container_width=True,
                                         disabled=["Municipio","Cliente","Producto"],num_rows="fixed",key="editor_excel")
                st.warning("Guardar crea pedidos nuevos. Verifica antes que el Excel no haya sido importado anteriormente.")
                if st.checkbox("Confirmo que revisé el Excel y quiero crear estos pedidos",key="confirmar_excel"):
                    if st.button("Generar y guardar pedidos",type="primary",key="guardar_excel"):
                        nuevos = {}
                        try:
                            for _,fila in editadas.iterrows():
                                m,cliente,producto = fila["Municipio"],fila["Cliente"],fila["Producto"]
                                kilos = str(fila["Kilos"])
                                gramos = convertir_a_gramos(kilos)
                                if gramos <= 0:
                                    raise ValueError(f"Cantidad no válida para {cliente}")
                                nuevos.setdefault(m,[]).append({
                                    "Municipio":m,"Cliente":cliente,"Producto":producto,
                                    "Kilos":kilos,"Empaque":"Predeterminada",
                                    "Bolsas":distribuir_por_destino(kilos,m,producto),
                                    "Capacidad especial":None})
                            for m,items in nuevos.items():
                                pedido = guardar_pedido_real(m,items,mids,cids,pids)
                                st.success(f'{m}: guardado como {pedido.get("numero_pedido") or pedido["id"]}')
                        except Exception as exc:
                            st.error(f"Importación detenida: {exc}. Si se guardaron municipios anteriores, no repitas el proceso sin revisar la bandeja.")
        except Exception as exc:
            st.error(f"No se pudo leer el Excel: {exc}")


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



def datos_etiqueta_guardados(numero):
    """Lee metadatos incluso si la migración de fecha_empaque está pendiente."""
    parametros = {"numero_pedido":"eq."+numero,"limit":"1"}
    try:
        encontrados = api_supabase("datos_etiqueta_pedido",parametros={
            **parametros,"select":"numero_pedido,fecha_beneficio,fecha_empaque,lote,nit"})
    except ValueError as exc:
        if "fecha_empaque" not in str(exc) or "42703" not in str(exc):
            raise
        encontrados = api_supabase("datos_etiqueta_pedido",parametros={
            **parametros,"select":"numero_pedido,fecha_beneficio,lote,nit"})
        if encontrados:
            encontrados[0]["fecha_empaque"] = None
    return encontrados[0] if encontrados else {}


def guardar_datos_etiqueta(numero, fecha, lote, nit, fecha_empaque):
    payload = {"numero_pedido":numero,"fecha_beneficio":fecha.isoformat(),
               "lote":lote.strip(),"nit":nit.strip(),"fecha_empaque":fecha_empaque.isoformat()}
    existentes = datos_etiqueta_guardados(numero)
    try:
        if existentes:
            api_supabase("datos_etiqueta_pedido","PATCH",payload,{"numero_pedido":"eq."+numero})
        else:
            api_supabase("datos_etiqueta_pedido","POST",payload)
    except ValueError as exc:
        if "fecha_empaque" in str(exc) and ("PGRST204" in str(exc) or "42703" in str(exc)):
            raise ValueError(
                "Falta la columna fecha_empaque en Supabase. Ejecuta el archivo "
                "migracion_fecha_empaque.sql en el editor SQL; no se guardó este pedido."
            ) from exc
        raise


def generar_pdf_pedidos(numeros):
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for numero in numeros:
        meta = datos_etiqueta_guardados(numero)
        if not meta.get("fecha_beneficio") or not meta.get("lote") or not meta.get("fecha_empaque"):
            raise ValueError("Faltan fecha de beneficio y lote en "+numero)
        cabecera, lineas = consultar_pedido_por_numero(numero)
        if not cabecera or not lineas:
            raise ValueError("No hay productos para "+numero)
        archivo = pdf_etiquetas_diseno(
            lineas, numero_pedido=numero, lote=meta["lote"],
            fecha_beneficio=date.fromisoformat(meta["fecha_beneficio"]),
            fecha_empaque=date.fromisoformat(meta["fecha_empaque"]),
            nit=meta.get("nit") or "",direccion=DIRECCION,
            conservacion="Mantener refrigerado entre 0 °C y 4 °C",
            instrucciones="Producto que requiere cocción para su consumo")
        for pagina in PdfReader(BytesIO(archivo)).pages:
            writer.add_page(pagina)
    salida = BytesIO()
    writer.write(salida)
    return salida.getvalue(),len(writer.pages)


with tab_revision:
    st.subheader("Pedidos pendientes de generar e imprimir etiquetas")
    st.caption("Selecciona únicamente los pedidos que deseas procesar. Los nuevos no se seleccionan automáticamente.")
    try:
        registros = listar_pedidos_guardados()
        pendientes = [p for p in registros if p["Estado"] not in ("impreso","anulado")]
        st.metric("Pedidos pendientes",len(pendientes))
        if pendientes:
            st.dataframe(pendientes,hide_index=True,use_container_width=True)
            mapa = {p["Número"]:p for p in pendientes}
            seleccion = st.multiselect(
                "Buscar y seleccionar pedidos pendientes",list(mapa),
                format_func=lambda n:mapa[n]["Municipio"]+" — "+n,
                key="pendientes_seleccion",placeholder="Selecciona uno o varios pedidos")
            if seleccion:
                st.write("**Pedidos elegidos:** "+str(len(seleccion)))
                st.caption("Si todos comparten fecha y lote, puedes guardar esos datos en conjunto. Si son diferentes, usa la edición individual.")
                with st.expander("Asignar fecha, lote y Fabricado para a los seleccionados",expanded=True):
                    with st.form("metadatos_pendientes"):
                        fecha_comun = st.date_input("Fecha de beneficio",value=date.today(),format="DD/MM/YYYY")
                        empaque_comun = st.date_input("Fecha de empaque (fecha de generación de la etiqueta)",value=date.today(),format="DD/MM/YYYY")
                        lote_comun = st.text_input("Lote (obligatorio)")
                        nit_comun = st.text_input("Fabricado para (NIT opcional)")
                        confirmar = st.checkbox("Confirmo que estos mismos datos corresponden a todos los pedidos seleccionados")
                        guardar = st.form_submit_button("Guardar fecha, lote y Fabricado para")
                    if guardar:
                        if not lote_comun.strip() or not confirmar:
                            st.error("Completa el lote y confirma que los datos aplican a todos los seleccionados.")
                        else:
                            guardados = []
                            try:
                                for numero in seleccion:
                                    guardar_datos_etiqueta(numero,fecha_comun,lote_comun,nit_comun,empaque_comun)
                                    guardados.append(numero)
                                st.success(f"Datos guardados en {len(guardados)} pedidos.")
                            except Exception as exc:
                                st.error(f"Error: {exc}. Se guardaron {len(guardados)} pedidos; revisa antes de repetir.")
                with st.expander("Editar fecha, lote o Fabricado para de un pedido específico"):
                    numero_individual = st.selectbox("Pedido",seleccion,key="pendiente_individual")
                    datos = datos_etiqueta_guardados(numero_individual)
                    with st.form("datos_individual_pendiente_"+numero_individual):
                        fecha_individual = st.date_input(
                            "Fecha de beneficio",value=date.fromisoformat(datos["fecha_beneficio"])
                            if datos.get("fecha_beneficio") else date.today(),format="DD/MM/YYYY")
                        empaque_individual = st.date_input("Fecha de empaque",value=date.fromisoformat(datos["fecha_empaque"]) if datos.get("fecha_empaque") else date.today(),format="DD/MM/YYYY")
                        lote_individual = st.text_input("Lote",value=datos.get("lote") or "")
                        nit_individual = st.text_input("Fabricado para (NIT opcional)",value=datos.get("nit") or "")
                        if st.form_submit_button("Guardar datos de este pedido"):
                            if lote_individual.strip():
                                guardar_datos_etiqueta(numero_individual,fecha_individual,lote_individual,nit_individual,empaque_individual)
                                st.success("Datos guardados en Supabase.")
                            else:
                                st.error("El lote es obligatorio.")
                with st.expander("Verificar productos y kilos que saldrán en el PDF"):
                    for numero_revision in seleccion:
                        try:
                            _, lineas_revision = consultar_pedido_por_numero(numero_revision)
                            resumen_revision = {}
                            for linea_revision in lineas_revision:
                                nombre_producto = linea_revision["Producto"]
                                resumen_revision[nombre_producto] = resumen_revision.get(nombre_producto,Decimal(0))+Decimal(linea_revision["Kilos"])
                            st.write(f"**{numero_revision}** — "+", ".join(
                                f"{producto}: {kilos} kg" for producto,kilos in resumen_revision.items()))
                            st.caption(f"{sum(len(linea['Bolsas']) for linea in lineas_revision)} etiquetas; "+
                                       f"{sum(Decimal(linea['Kilos']) for linea in lineas_revision)} kg en total.")
                        except Exception as exc:
                            st.error(f"No se pudo revisar {numero_revision}: {exc}")
                if st.button("Preparar PDF de los pedidos seleccionados",type="primary",key="generar_pendientes"):
                    try:
                        pdf,paginas = generar_pdf_pedidos(seleccion)
                        st.session_state["pdf_pendientes"] = pdf
                        st.session_state["pdf_pendientes_numeros"] = tuple(seleccion)
                        st.success(f"PDF listo: {paginas} etiquetas.")
                    except Exception as exc:
                        st.session_state.pop("pdf_pendientes",None)
                        st.error(str(exc)+". Completa los datos faltantes antes de generar.")
                if (st.session_state.get("pdf_pendientes") and
                    st.session_state.get("pdf_pendientes_numeros")==tuple(seleccion)):
                    st.download_button("Descargar PDF conjunto de etiquetas",st.session_state["pdf_pendientes"],
                                       file_name="MaxiCarnes_pedidos_pendientes.pdf",mime="application/pdf",type="primary")
                    st.warning("Después de imprimir físicamente, confirma cuáles pedidos se imprimieron correctamente.")
                    confirmar_impresion = st.checkbox("Confirmo que todas las etiquetas de estos pedidos ya fueron impresas",
                                                       key="confirmacion_impresion_pendientes")
                    if st.button("Marcar pedidos como impresos y pasar al módulo 4",
                                 disabled=not confirmar_impresion,key="marcar_impresos"):
                        try:
                            for numero in seleccion:
                                api_supabase("pedidos","PATCH",{"estado":"impreso","impreso_en":date.today().isoformat()},
                                             {"numero_pedido":"eq."+numero})
                            st.session_state.pop("pdf_pendientes",None)
                            st.success("Pedidos marcados como impresos. Ya aparecerán en el módulo 4.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"No se pudo confirmar toda la impresión: {exc}. Revisa los estados antes de repetir.")
        else:
            st.success("No hay pedidos pendientes.")
    except Exception as exc:
        st.error(f"No se pudieron consultar los pendientes: {exc}")


with tab_bandeja:
    st.subheader("Pedidos impresos e historial")
    st.caption("Aquí puedes consultar pedidos ya confirmados como impresos, corregir cantidades y reimprimir etiquetas.")
    try:
        registros = listar_pedidos_guardados()
        impresos = [p for p in registros if p["Estado"]=="impreso"]
        st.metric("Pedidos impresos",len(impresos))
        if impresos:
            st.dataframe(impresos,hide_index=True,use_container_width=True)
            mapa_impresos = {p["Número"]:p for p in impresos}
            numero = st.selectbox("Buscar pedido impreso",list(mapa_impresos),
                                  format_func=lambda n:mapa_impresos[n]["Municipio"]+" — "+n,
                                  key="numero_impreso")
            cabecera, lineas = consultar_pedido_por_numero(numero)
            if lineas:
                st.dataframe([{"Cliente":p["Cliente"],"Producto":p["Producto"],
                               "Kilos":p["Kilos"],"Bolsas":len(p["Bolsas"])}
                              for p in lineas],hide_index=True,use_container_width=True)
                with st.expander("Modificar cantidad de un producto"):
                    detalles = {str(p["Detalle ID"]):p for p in lineas}
                    detalle = st.selectbox("Cliente y producto",list(detalles),
                                           format_func=lambda d:detalles[d]["Cliente"]+" — "+detalles[d]["Producto"])
                    with st.form("corregir_impreso_"+numero):
                        kilos = st.text_input("Cantidad total en kg",value=detalles[detalle]["Kilos"])
                        confirma = st.checkbox("Confirmo el cambio del pedido ya impreso")
                        if st.form_submit_button("Guardar corrección"):
                            if not confirma:
                                st.error("Confirma la corrección.")
                            else:
                                try:
                                    gramos = convertir_a_gramos(kilos)
                                    if gramos <= 0:
                                        raise ValueError("El peso debe ser positivo.")
                                    api_supabase("detalles_pedido","PATCH",{"gramos":gramos},{"id":"eq."+detalle})
                                    st.success("Cantidad actualizada en Supabase.")
                                    st.rerun()
                                except Exception as exc:
                                    st.error(str(exc))
                opciones_bolsas = {}
                for i,p in enumerate(lineas):
                    for j,peso in enumerate(p["Bolsas"]):
                        opciones_bolsas[f"{i}:{j}"] = f'{p["Cliente"]} — {p["Producto"]} — Bolsa {j+1} — {peso} g'
                modo = st.radio("Reimprimir",["Todas las etiquetas","Solo etiquetas específicas"],horizontal=True)
                elegidas = list(opciones_bolsas) if modo=="Todas las etiquetas" else st.multiselect(
                    "Seleccionar etiquetas",list(opciones_bolsas),format_func=lambda k:opciones_bolsas[k])
                seleccionadas = []
                for clave in elegidas:
                    i,j = (int(x) for x in clave.split(":"))
                    copia = dict(lineas[i])
                    copia["Bolsas"] = [lineas[i]["Bolsas"][j]]
                    copia["Número bolsa original"] = j + 1
                    copia["Total bolsas original"] = len(lineas[i]["Bolsas"])
                    seleccionadas.append(copia)
                datos = datos_etiqueta_guardados(numero)
                with st.form("reimprimir_"+numero):
                    fecha = st.date_input("Fecha de beneficio",value=date.fromisoformat(datos["fecha_beneficio"])
                                          if datos.get("fecha_beneficio") else date.today(),format="DD/MM/YYYY")
                    empaque = st.date_input("Fecha de empaque",value=date.fromisoformat(datos["fecha_empaque"]) if datos.get("fecha_empaque") else date.today(),format="DD/MM/YYYY")
                    lote = st.text_input("Lote (obligatorio)",value=datos.get("lote") or "")
                    nit = st.text_input("Fabricado para (NIT opcional)",value=datos.get("nit") or "")
                    pesos = []
                    for i,etiqueta in enumerate(seleccionadas):
                        st.caption(f'{etiqueta["Cliente"]} — {etiqueta["Producto"]}')
                        pesos.append(st.number_input("Peso de etiqueta "+str(i+1)+" (g)",
                                                     min_value=1,value=int(etiqueta["Bolsas"][0]),
                                                     key="peso_impreso_"+numero+"_"+str(i)))
                    generar = st.form_submit_button("Preparar PDF de reimpresión")
                if generar:
                    if not lote.strip() or not seleccionadas:
                        st.error("Indica el lote y selecciona al menos una etiqueta.")
                    else:
                        try:
                            guardar_datos_etiqueta(numero,fecha,lote,nit,empaque)
                            editadas = [dict(p,Bolsas=[peso]) for p,peso in zip(seleccionadas,pesos)]
                            st.session_state["pdf_reimpreso"] = pdf_etiquetas_diseno(
                                editadas,numero_pedido=numero,lote=lote,fecha_beneficio=fecha,fecha_empaque=empaque,
                                nit=nit,conservacion="Mantener refrigerado entre 0 °C y 4 °C",
                                instrucciones="Producto que requiere cocción para su consumo",direccion=DIRECCION)
                            st.session_state["pdf_reimpreso_numero"] = numero
                            st.success("PDF preparado. Las correcciones de peso de una etiqueta solo afectan esta reimpresión.")
                        except Exception as exc:
                            st.error(f"No se pudo generar el PDF: {exc}")
                if st.session_state.get("pdf_reimpreso") and st.session_state.get("pdf_reimpreso_numero")==numero:
                    st.download_button("Descargar PDF para reimprimir",st.session_state["pdf_reimpreso"],
                                       file_name=numero+"_reimpresion.pdf",mime="application/pdf",type="primary")
        else:
            st.info("Todavía no hay pedidos confirmados como impresos.")
    except Exception as exc:
        st.error(f"No se pudo consultar el historial: {exc}")
