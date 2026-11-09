import streamlit as st
from datetime import date, timedelta
from empaque import distribuir_por_destino

st.set_page_config(page_title="Maxi Carnes | Etiquetas", page_icon="🏷️")
st.title("Maxi Carnes | Pedidos y etiquetas")
st.caption("Prototipo universitario — cálculo de empaque (sin impresión todavía)")

with st.form("pedido"):
    municipio = st.selectbox("Municipio", ["Gama", "Sibaté", "Villagómez", "El Peñón", "Otro"])
    if municipio == "Otro":
        municipio = st.text_input("Nombre del municipio")
    producto = st.selectbox("Producto", ["GOULASH", "CARNE MOLIDA", "OTRO"])
    if producto == "OTRO":
        producto = st.text_input("Nombre del producto")
    kilos = st.text_input("Cantidad solicitada (kg)", value="5,5")
    calcular = st.form_submit_button("Calcular bolsas", type="primary")

if calcular:
    if not municipio.strip() or not producto.strip():
        st.error("Debes indicar el municipio y el producto.")
    else:
        try:
            bolsas = distribuir_por_destino(kilos, municipio, producto)
            st.success(f"Se necesitan {len(bolsas)} etiquetas.")
            st.write(f"**Municipio:** {municipio} · **Producto:** {producto}")
            st.dataframe(
                [{"Bolsa": i, "Peso (kg)": f"{gramos / 1000:.3f}".replace(".", ",")}
                 for i, gramos in enumerate(bolsas, start=1)],
                use_container_width=True,
                hide_index=True,
            )
            st.info(f"Total: {sum(bolsas)/1000:.3f} kg")
        except ValueError as exc:
            st.error(str(exc))

st.divider()
st.subheader("Datos para futuras etiquetas")
st.caption("Esta sección es una vista previa: aún no crea ni imprime etiquetas.")
fecha_beneficio = st.date_input("Fecha de beneficio (registrada por Cristian)", value=date.today(), format="DD/MM/YYYY")
lote = st.text_input("Número de lote")
if st.button("Ver fechas previstas de etiquetas"):
    if not lote.strip():
        st.warning("Ingresa el número de lote.")
    else:
        fecha_empaque = date.today()
        fecha_vencimiento = fecha_empaque + timedelta(days=30)
        st.write(f"**Lote:** {lote}")
        st.write(f"**Beneficio:** {fecha_beneficio:%d/%m/%Y}")
        st.write(f"**Empaque:** {fecha_empaque:%d/%m/%Y}")
        st.write(f"**Vencimiento (30 días calendario):** {fecha_vencimiento:%d/%m/%Y}")
        st.warning("La vida útil de 30 días requiere validación sanitaria antes de imprimir etiquetas comerciales.")

st.caption("Próximas etapas: importar Excel, configurar textos fijos y generar etiquetas Zebra.")
