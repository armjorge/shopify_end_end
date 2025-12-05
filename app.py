import streamlit as st

st.set_page_config(
    page_title="Organizador multistore",
    page_icon="🛒",
)

st.title("Organizador multistore")
st.write(f"🔎 Streamlit version: {st.__version__}")

page_purpose = """
- Al agregar un producto a la lista de la tienda y este ser activo, se carga el producto en la tienda tomando información de nuestro ERP.
- Se notifica al usuario del estatus de su pedido.
- Las tiendas reflejan en todo momento el inventario disponible.
- El inventario disponible se concilia con las compras y ventas en todo momento.
"""
st.markdown(page_purpose)

st.divider()

st.subheader("Navegación")

st.page_link(
    "pages/00_yaml.py",
    label="Editar YAML",
    icon="⚙️",
)

st.page_link(
    "pages/01_mongo_db.py",
    label="Sincronizar a MongoDB",
    icon="📦",
)

st.page_link(
    "pages/02_orders.py",
    label="Generar y actualizar órdenes",
    icon="🧾",
)

st.page_link(
    "pages/03_status.py",
    label="Estatus",
    icon="📊",
)