import streamlit as st

st.title("Órdenes 🧾")

st.write("Aquí se listan y administran las órdenes de las distintas tiendas.")

st.divider()

st.page_link(
    "app.py",
    label="Volver al inicio",
    icon="🏠",
)