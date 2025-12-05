import sys
import streamlit as st
import os 
from dotenv import load_dotenv
import yaml


st.title("Editar YAML ⚙️")
st.write("Aquí podrás configurar y editar los archivos YAML de las tiendas.")
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

# 🔹 NUEVO: widget para subir config.yml
st.subheader("Subir configuración de paquete (config.yml)")
uploaded_file = st.file_uploader(
    "Sube tu archivo config.yml",
    type=["yml", "yaml", "txt", "config", "yml"],
    help="Selecciona el archivo de configuración de la tienda desde tu computadora."
)

if uploaded_file is not None:
    try:
        # Aseguramos que el folder exista
        os.makedirs(os.path.dirname(pkg_yaml), exist_ok=True)

        # Guardar en disco exactamente en pkg_yaml
        with open(pkg_yaml, "wb") as f:
            f.write(uploaded_file.read())

        st.success(f"✅ Archivo guardado como: {pkg_yaml}")
    except Exception as e:
        st.error(f"❌ No se pudo guardar el archivo: {e}")

# 🔹 IMPORTANTE: calcular existencia DESPUÉS del posible upload
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

# 🔹 NUEVO: botón para descargar pkg_yaml
if pkg_exists:
    with open(pkg_yaml, "rb") as f:
        pkg_bytes = f.read()

    st.download_button(
        label="⬇️ Descargar config.yml",
        data=pkg_bytes,
        file_name="config.yml",
        mime="application/x-yaml",  # o "text/plain"
        help="Descarga la configuración actual de paquete a tu computadora."
    )

# Si no existe ninguno, detenemos
if not root_exists and not pkg_exists:
    st.error(
        "❌ No se encontró ningún archivo de configuración.\n"
        f"- {root_yaml}\n"
        f"- {pkg_yaml}\n\n"
        "Sube un config.yml para continuar."
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
        yaml_data.update(pkg_data)  