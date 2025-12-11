from pymongo import MongoClient
import pandas as pd
import os
import sys
import streamlit as st
import yaml
from dotenv import load_dotenv

st.title("Items de Zoho Inventory")
st.write("Vista de negocio de la colección `Zoho_Inventory.items`.")

log_placeholder = st.empty()
log_lines = []
def streamlit_logger(msg):
    # acumulamos los mensajes y refrescamos el contenedor
    log_lines.append(str(msg))
    log_placeholder.text("\n".join(log_lines))

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
    collection = db["items"]
except Exception as e:
    st.error(f"❌ Error al conectar con MongoDB: {e}")
    st.stop()

# ================== EXTRACCIÓN DE ITEMS ==================
fields = [
    "item_name",
    "sku",
    "unit",
    "actual_available_stock",
    "available_stock",
    "stock_on_hand",
    "rate",
    "status",
    "item_id"

]

projection = {field: 1 for field in fields}
projection["_id"] = 0

try:
    cursor = collection.find({}, projection)
    docs = list(cursor)
    df = pd.DataFrame(docs, columns=fields)
except Exception as e:
    st.error(f"❌ Error al leer la colección 'items': {e}")
    st.stop()

# ================== VISTA + FILTRO POR STATUS ==================
if df.empty:
    st.warning("🔎 Sin datos en la colección `items` con los campos seleccionados.")
else:
    # Opciones de status (incluyendo 'Todos')
    status_values = sorted(
        [s for s in df["status"].dropna().unique().tolist()]
    )
    status_sel = st.selectbox(
        "Filtrar por status",
        options=["Todos"] + status_values,
        index=0,
    )

    if status_sel != "Todos":
        df_view = df[df["status"] == status_sel].copy()
    else:
        df_view = df.copy()

    if df_view.empty:
        st.info("📭 Sin datos para el status seleccionado.")
    else:
        st.write(f"Mostrando {len(df_view)} registros:")
        st.dataframe(df_view, use_container_width=True)

# ================== ITEMS POR TIENDA ==================
st.divider()
st.header("Asignación de productos por tienda")

items_per_store_coll = db["items_per_store"]

# Claves internas -> etiqueta amigable
stores = {
    "managed_store_one": "Tienda 1 (managed_store_one)",
    "managed_store_two": "Tienda 2 (managed_store_two)",
}

tabs = st.tabs(list(stores.values()))

for tab, (store_key, store_label) in zip(tabs, stores.items()):
    with tab:
        st.subheader(store_label)

        # --- Leer o inicializar documento de la tienda ---
        store_doc = items_per_store_coll.find_one({"store": store_key}) or {
            "store": store_key,
            "items": [],
        }
        items_list = store_doc.get("items", [])
        assigned_ids = [it["item_id"] for it in items_list if "item_id" in it]

        # --- DataFrame de productos ya asignados a esta tienda ---
        df_assigned = df[df["item_id"].isin(assigned_ids)].copy()

        if df_assigned.empty:
            st.info("📭 Esta tienda no tiene productos asignados todavía.")
        else:
            st.write(f"Productos actuales en {store_label}: {len(df_assigned)}")
            st.dataframe(
                df_assigned[
                    [
                        "item_id",
                        "item_name",
                        "sku",
                        "status",
                        "rate",
                        "actual_available_stock",
                        "available_stock",
                        "stock_on_hand",
                    ]
                ],
                use_container_width=True,
            )

        st.markdown("---")

        # ====== AGREGAR PRODUCTOS A LA TIENDA ======
        st.markdown("### Agregar productos a la tienda")

        available_df = df[~df["item_id"].isin(assigned_ids)].copy()

        if available_df.empty:
            st.success("✅ Todos los productos disponibles ya están asignados a esta tienda.")
        else:
            # mapa item_id -> etiqueta legible
            labels_add = {
                row["item_id"]: f"{row['item_name']} [{row['sku']}]"
                for _, row in available_df.iterrows()
            }

            to_add_ids = st.multiselect(
                "Selecciona productos para agregar",
                options=list(labels_add.keys()),
                format_func=lambda x, m=labels_add: m.get(x, str(x)),
                key=f"add_{store_key}",
            )

            if st.button("Agregar a la tienda", key=f"btn_add_{store_key}") and to_add_ids:
                # Recargar documento para evitar condiciones de carrera
                store_doc = items_per_store_coll.find_one({"store": store_key}) or {
                    "store": store_key,
                    "items": [],
                }
                items_list = store_doc.get("items", [])
                existing_ids = {it["item_id"] for it in items_list if "item_id" in it}

                for item_id in to_add_ids:
                    if item_id in existing_ids:
                        continue
                    row = df.loc[df["item_id"] == item_id].iloc[0]
                    items_list.append(
                        {
                            "item_id": item_id,
                            "name": row["item_name"],  # snapshot del nombre actual
                        }
                    )
                    existing_ids.add(item_id)

                items_per_store_coll.update_one(
                    {"store": store_key},
                    {"$set": {"store": store_key, "items": items_list}},
                    upsert=True,
                )
                st.success(f"Se agregaron {len(to_add_ids)} productos a {store_label}.")
                st.rerun()

        st.markdown("---")

        # ====== RETIRAR PRODUCTOS DE LA TIENDA ======
        st.markdown("### Retirar productos de la tienda")

        if assigned_ids:
            df_assigned = df[df["item_id"].isin(assigned_ids)].copy()

            labels_remove = {
                row["item_id"]: f"{row['item_name']} [{row['sku']}]"
                for _, row in df_assigned.iterrows()
            }

            to_remove_ids = st.multiselect(
                "Selecciona productos para retirar",
                options=list(labels_remove.keys()),
                format_func=lambda x, m=labels_remove: m.get(x, str(x)),
                key=f"remove_{store_key}",
            )

            if st.button("Retirar de la tienda", key=f"btn_remove_{store_key}") and to_remove_ids:
                store_doc = items_per_store_coll.find_one({"store": store_key}) or {
                    "store": store_key,
                    "items": [],
                }
                items_list = [
                    it for it in store_doc.get("items", [])
                    if it.get("item_id") not in to_remove_ids
                ]

                items_per_store_coll.update_one(
                    {"store": store_key},
                    {"$set": {"store": store_key, "items": items_list}},
                    upsert=True,
                )
                st.success(f"Se retiraron {len(to_remove_ids)} productos de {store_label}.")
                st.rerun()
        else:
            st.info("No hay productos que retirar en esta tienda.")
st.markdown("---")

# ====== RETIRAR PRODUCTOS DE LA TIENDA ======
st.markdown("### Sincronizar inventario entre las tiendas")
if st.button("Sincronización de inventario"):
    stores = ["managed_store_one", "managed_store_two"]
    for store in stores: 
        st.write(f"Sincronizando inventario para {store}...")
        from library.inventory_automatization import INVENTORY_AUTOMATIZATION
        app = INVENTORY_AUTOMATIZATION(working_folder, yaml_data)
        app.run_inventory_sync(store, logger=streamlit_logger)