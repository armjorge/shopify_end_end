import streamlit as st
import os 
from dotenv import load_dotenv
import yaml

st.title("Inventarios 📦")

st.write("Vista para consultar y conciliar inventarios entre tiendas y ERP.")

st.divider()

st.page_link(
    "app.py",
    label="Volver al inicio",
    icon="🏠",
)

# Configuración para cargar las clases
# BASE_PATH = raíz del repo (un nivel arriba de /pages)
BASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

env_file = os.path.join(BASE_PATH, ".env")
folder_name = "MAIN_PATH"
working_folder = None
data_access = {}

if os.path.exists(env_file):
    load_dotenv(dotenv_path=env_file)
    working_folder = os.getenv(folder_name)
else:
    st.error("❌ No se encontró el archivo .env en la raíz del proyecto.")
    st.stop()

# Intentar primero en la raíz, luego en el subdirectorio shopify_end_end
root_yaml = os.path.join(BASE_PATH, "config.yml")
pkg_yaml = os.path.join(BASE_PATH, "shopify_end_end", "config.yml")
yaml_path = None
if os.path.exists(root_yaml):
    yaml_path = root_yaml
elif os.path.exists(pkg_yaml):
    yaml_path = pkg_yaml
else:
    st.error(
        f"❌ No se encontró config.yml ni en:\n- {root_yaml}\n- {pkg_yaml}"
    )
    st.stop()

with open(yaml_path, "r") as f:
    yaml_data = yaml.safe_load(f) or {}

if st.button("Iniciar Sincronización de Inventario"):
    from Inventory_Sync import SHOPIFY
    shopify_zoho = SHOPIFY(working_folder, yaml_data)
    shopify_zoho.run()