import sys
import streamlit as st
import os 
from dotenv import load_dotenv
import yaml
from library.zoho_inventory import ZOHO_INVENTORY
import io
import contextlib


st.title("Zoho y Shopify -> Repositorio en MongoDB 📦")

st.write("Vista para actualizar el repositorio de endpoints en MongoDB.")

st.divider()

st.page_link(
    "app.py",
    label="Volver al inicio",
    icon="🏠",
)

# Configuración para cargar las clases
# BASE_PATH = raíz del repo (un nivel arriba de /pages)
BASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_PATH not in sys.path:
    sys.path.insert(0, BASE_PATH)  # insert(0, ...) = prioridad alta para imports

env_file = os.path.join(BASE_PATH, ".env")
folder_name = "MAIN_PATH"
data_access = {}
working_folder = BASE_PATH

if os.path.exists(env_file):
    # Modo desarrollo local: leemos .env
    load_dotenv(dotenv_path=env_file)
    env_main_path = os.getenv(folder_name)

    if env_main_path:
        working_folder = env_main_path
        st.success(f"✅ MAIN_PATH tomado desde .env: {working_folder}")
    else:
        st.warning(
            f"⚠️ Se encontró .env en {env_file} pero la variable {folder_name} no está definida.\n"
            f"Se usará BASE_PATH como working_folder: {working_folder}"
        )

else:
    # Probablemente estamos en Render.com (no hay .env en el repo)
    env_main_path = os.getenv(folder_name)

    if env_main_path:
        # Caso ideal: definiste MAIN_PATH en las environment vars de Render
        working_folder = env_main_path
        st.success(f"✅ MAIN_PATH tomado de variables de entorno del sistema: {working_folder}")
    else:
        # Último fallback: el directorio actual del proceso (repo en Render)
        working_folder = os.getcwd()
        st.warning(
            "⚠️ No se encontró .env ni variable de entorno MAIN_PATH.\n"
            f"Se usará el directorio actual como working_folder: {working_folder}"
        )

# BASE_PATH y working_folder definidos antes
root_yaml = os.path.join(BASE_PATH, "config", "open_config.yml")
pkg_yaml = os.path.join(working_folder, "config.yml")

root_exists = os.path.exists(root_yaml)
pkg_exists = os.path.exists(pkg_yaml)

# Mensajes por archivo
if root_exists:
    st.success(f"✅ Se encontró configuración raíz: {root_yaml}")
else:
    st.warning(f"⚠️ No se encontró configuración raíz en: {root_yaml}")

if pkg_exists:
    st.success(f"✅ Se encontró configuración de paquete: {pkg_yaml}")
else:
    st.warning(f"⚠️ No se encontró configuración de paquete en: {pkg_yaml}")

# Si no existe ninguno, detenemos
if not root_exists and not pkg_exists:
    st.error(
        "❌ No se encontró ningún archivo de configuración.\n"
        f"- {root_yaml}\n"
        f"- {pkg_yaml}"
    )
    st.stop()

# Cargar y combinar data de ambos YAML
yaml_data = {}

if root_exists:
    with open(root_yaml, "r") as f:
        root_data = yaml.safe_load(f) or {}
        yaml_data.update(root_data)  # base

if pkg_exists:
    with open(pkg_yaml, "r") as f:
        pkg_data = yaml.safe_load(f) or {}
        yaml_data.update(pkg_data)   # sobreescribe claves si ya existen

if st.button("Iniciar Sincronización ZOHO Inventory"):
    from library.zoho_inventory import ZOHO_INVENTORY

    zoho_inventory = ZOHO_INVENTORY(working_folder, yaml_data)

    log_placeholder = st.empty()
    log_lines = []

    def streamlit_logger(msg):
        log_lines.append(str(msg))
        log_placeholder.text("\n".join(log_lines))

    st.info("⏳ Inicializando ZOHO Inventory...")

    with st.spinner("Sincronizando con Zoho..."):
        summary = zoho_inventory.sync_zoho_inventory_to_mongo(logger=streamlit_logger)

    st.subheader("📊 Resumen")
    st.json(summary)    
    
st.divider()


if st.button("Iniciar Sincronización SHOPIFY"):
    from library.shopify_mongo_db import SHOPIFY_MONGODB

    store1 = "managed_store_one"
    store2 = "managed_store_two"



    # Contenedor y buffer para el log en pantalla
    log_placeholder = st.empty()
    log_lines = []

    def streamlit_logger(msg):
        # acumulamos los mensajes y refrescamos el contenedor
        log_lines.append(str(msg))
        log_placeholder.text("\n".join(log_lines))

    st.info("⏳ Inicializando sincronización Shopify...")

    with st.spinner("Sincronizando con Shopify..."):
        shopify_management_one = SHOPIFY_MONGODB(working_folder, yaml_data, store1)
        summary_one = shopify_management_one.sync_shopify_to_mongo(logger=streamlit_logger)
        shopify_management_two = SHOPIFY_MONGODB(working_folder, yaml_data, store2)
        summary_two = shopify_management_two.sync_shopify_to_mongo(logger=streamlit_logger)

    st.subheader("📊 Resumen Shopify")
    st.json({
        store1: summary_one,
        store2: summary_two,
    })