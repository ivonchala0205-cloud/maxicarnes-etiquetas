import streamlit as st
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

st.caption("Próximas etapas: importar Excel, completar datos de lote y generar etiquetas Zebra.")
