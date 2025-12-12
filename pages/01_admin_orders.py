from pymongo import MongoClient
import pandas as pd
import os
import sys
import streamlit as st
import yaml
from dotenv import load_dotenv

# ================== TÍTULO / DESCRIPCIÓN ==================
st.title("Órdenes de venta (Zoho Inventory / CRM)")
st.write("Vista de negocio de la colección `Zoho_Inventory.salesorders`.")

st.divider()

# ================== RUTA BASE / .env / MAIN_PATH ==================
# BASE_PATH = raíz del repo (un nivel arriba de /pages)
BASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_PATH not in sys.path:
    sys.path.insert(0, BASE_PATH)  # insert(0, ...) = prioridad alta para imports

env_file = os.path.join(BASE_PATH, ".env")
folder_name = "MAIN_PATH"
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

# ================== YAML CONFIG ==================
root_yaml = os.path.join(BASE_PATH, "config", "open_config.yml")
pkg_yaml = os.path.join(working_folder, "config.yml")

root_exists = os.path.exists(root_yaml)
pkg_exists = os.path.exists(pkg_yaml)

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

# ================== CONEXIÓN A MONGODB ==================
mongo_db_url = yaml_data["non_sql_database"]["url"]

try:
    client = MongoClient(mongo_db_url)
    db = client["Zoho_Inventory"]
    collection = db["salesorders"]
except Exception as e:
    st.error(f"❌ Error al conectar con MongoDB: {e}")
    st.stop()

# ================== EXTRACCIÓN DE ORDENES ==================
fields = [
    "salesorder_number",
    "customer_name",
    "invoiced_status",
    "has_attachment",
    "order_status",   # <- vamos a filtrar por esta
    "paid_status",
    "is_emailed",
    "quantity",
    "total",
]

projection = {field: 1 for field in fields}
projection["_id"] = 0

try:
    cursor = collection.find({}, projection)
    docs = list(cursor)
    df = pd.DataFrame(docs, columns=fields)
except Exception as e:
    st.error(f"❌ Error al leer la colección 'salesorders': {e}")
    st.stop()

# ================== VISTA + FILTRO POR order_status ==================
if df.empty:
    st.warning("🔎 Sin datos en la colección `salesorders` con los campos seleccionados.")
else:
    # Columna de estado que vamos a usar
    status_col = "order_status"

    if status_col not in df.columns:
        st.warning(f"⚠️ La columna '{status_col}' no existe en el DataFrame. Mostrando todas las filas sin filtro.")
        df_view = df.copy()
    else:
        status_values = sorted(
            [s for s in df[status_col].dropna().unique().tolist()]
        )

        status_sel = st.selectbox(
            "Filtrar por estado de la orden",
            options=["Todos"] + status_values,
            index=0,
        )

        if status_sel != "Todos":
            df_view = df[df[status_col] == status_sel].copy()
        else:
            df_view = df.copy()

    if df_view.empty:
        st.info("📭 Sin datos para el filtro seleccionado.")
    else:
        st.write(f"Mostrando {len(df_view)} registros:")
        st.dataframe(df_view, use_container_width=True)

st.divider()
st.write("Elegir qué productos van a cada tienda")
st.write("store_1 = ")

st.divider()
st.write("Sincronizar inventarios Zoho → MongoDB")
st.write("store_1 = ")
