from pymongo import MongoClient
import pandas as pd
import os
import sys
import streamlit as st
import yaml
from dotenv import load_dotenv
import platform
import subprocess

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

# == Direcciones de las tiendas y Zoho Inventory ==
st.markdown("#### Direcciones de las tiendas y Zoho Inventory")

# Leemos los nombres de las tiendas desde el YAML
store1_cfg = yaml_data.get("managed_store_one", {})
store2_cfg = yaml_data.get("managed_store_two", {})

store1_domain = store1_cfg.get("store_name")
store2_domain = store2_cfg.get("store_name")

store1_url = f"https://{store1_domain}" if store1_domain else None
store2_url = f"https://{store2_domain}" if store2_domain else None

zoho_url = "https://inventory.zoho.com"


col1, col2, col3 = st.columns(3)
    
with col1:
    if store1_url:
        st.markdown(f"[🛍️ Shopify – Store 1]({store1_url})")
        st.caption(store1_domain)
    else:
        st.warning("No se encontró `store_name` para managed_store_one en el YAML.")

with col2:
    if store2_url:
        st.markdown(f"[🛒 Shopify – Store 2]({store2_url})")
        st.caption(store2_domain)
    else:
        st.warning("No se encontró `store_name` para managed_store_two en el YAML.")

with col3:
    st.markdown(f"[📦 Zoho Inventory]({zoho_url})")
    st.caption("inventory.zoho.com")



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

st.divider()
st.markdown("### Sincronizar inventario entre las tiendas")

stores = ["managed_store_one", "managed_store_two"]

st.title("Sincronización de inventario Zoho ↔ Shopify")

st.markdown(
    """
Este botón ejecuta el **pipeline completo** para que Shopify refleje el inventario real:

1. Zoho Inventory → Base interna (MongoDB)
2. Shopify → Base interna (estado inicial)
3. Ciclo 1: Base interna → Shopify (creación/ajustes de artículos)
4. Shopify → Base interna (reflejar cambios del ciclo 1)
5. Ciclo 2: Base interna → Shopify (estatus y afinado)
6. Shopify → Base interna (reflejar el último cambio)
"""
)

# 🔘 BOTÓN ÚNICO: Sincronizar Zoho y Shopify
if st.button("Sincronizar Zoho y Shopify", use_container_width=True, key="btn_full_sync"):
    from library.zoho_inventory import ZOHO_INVENTORY
    from library.shopify_mongo_db import SHOPIFY_MONGODB
    from library.inventory_automatization import INVENTORY_AUTOMATIZATION

    st.info("⏳ Iniciando pipeline completo Zoho ↔ Shopify...")

    # ------------------------------------------------------------------
    # 1) ZOHO Inventory → Base interna (MongoDB)
    # ------------------------------------------------------------------
    st.subheader("1️⃣ Zoho Inventory → Base interna")
    with st.spinner("Sincronizando Zoho Inventory con la base interna..."):
        zoho_inventory = ZOHO_INVENTORY(working_folder, yaml_data)
        zoho_summary = zoho_inventory.sync_zoho_inventory_to_mongo(
            logger=streamlit_logger
        )
    st.success("✅ Zoho Inventory sincronizado con la base interna.")
    st.json(zoho_summary)

    # Diccionarios para ir guardando resúmenes de Shopify
    shopify_sync_before = {}
    shopify_sync_after_cycle1 = {}
    shopify_sync_final = {}

    # ------------------------------------------------------------------
    # 2) Primer Shopify → Base interna (estado inicial)
    # ------------------------------------------------------------------
    st.subheader("2️⃣ Shopify → Base interna (estado inicial)")
    with st.spinner("Sincronizando Shopify → Base interna (antes de aplicar inventario)..."):
        for store in stores:
            st.write(f"📥 Shopify → Base interna (estado inicial) para **{store}**...")
            shopify_management = SHOPIFY_MONGODB(working_folder, yaml_data, store)
            shopify_sync_before[store] = shopify_management.sync_shopify_to_mongo(
                logger=streamlit_logger
            )
    st.success("✅ Primer barrido Shopify → Base interna completado.")
    st.json(shopify_sync_before)

    # ------------------------------------------------------------------
    # 3) Ciclo 1 de inventario: Base interna → Shopify (creación de artículos)
    # ------------------------------------------------------------------
    st.subheader("3️⃣ Ciclo 1: Base interna → Shopify (creación/ajustes principales)")
    with st.spinner("Aplicando inventario base interna → Shopify (ciclo 1)..."):
        for store in stores:
            st.write(f"🔄 Ciclo 1: sincronizando inventario Base interna → Shopify para **{store}**...")
            app = INVENTORY_AUTOMATIZATION(working_folder, yaml_data)
            # Si run_inventory_sync devuelve algo, puedes capturarlo y guardarlo
            app.run_inventory_sync(store, logger=streamlit_logger)
    st.success("✅ Ciclo 1 de inventario aplicado en todas las tiendas.")

    # ------------------------------------------------------------------
    # 4) Segundo Shopify → Base interna (reflejar cambios del ciclo 1)
    # ------------------------------------------------------------------
    st.subheader("4️⃣ Shopify → Base interna (después del ciclo 1)")
    with st.spinner("Actualizando base interna con los cambios del ciclo 1..."):
        for store in stores:
            st.write(f"📥 Shopify → Base interna (post ciclo 1) para **{store}**...")
            shopify_management = SHOPIFY_MONGODB(working_folder, yaml_data, store)
            shopify_sync_after_cycle1[store] = shopify_management.sync_shopify_to_mongo(
                logger=streamlit_logger
            )
    st.success("✅ Segundo barrido Shopify → Base interna completado.")
    st.json(shopify_sync_after_cycle1)

    # ------------------------------------------------------------------
    # 5) Ciclo 2 de inventario: Base interna → Shopify (estatus y afinado)
    # ------------------------------------------------------------------
    st.subheader("5️⃣ Ciclo 2: Base interna → Shopify (estatus / afinado de artículos)")
    with st.spinner("Aplicando inventario base interna → Shopify (ciclo 2)..."):
        for store in stores:
            st.write(f"🔄 Ciclo 2: actualizando estatus/artículos en Shopify para **{store}**...")
            app = INVENTORY_AUTOMATIZATION(working_folder, yaml_data)
            app.run_inventory_sync(store, logger=streamlit_logger)
    st.success("✅ Ciclo 2 de inventario aplicado en todas las tiendas.")

    # ------------------------------------------------------------------
    # 6) Tercer Shopify → Base interna (reflejar el último cambio)
    # ------------------------------------------------------------------
    st.subheader("6️⃣ Shopify → Base interna (reflejar último estado)")
    with st.spinner("Sincronizando por última vez Shopify → Base interna..."):
        for store in stores:
            st.write(f"📥 Shopify → Base interna (estado final) para **{store}**...")
            shopify_management = SHOPIFY_MONGODB(working_folder, yaml_data, store)
            shopify_sync_final[store] = shopify_management.sync_shopify_to_mongo(
                logger=streamlit_logger
            )
    st.success("✅ Tercer barrido Shopify → Base interna completado.")

    st.subheader("📊 Resumen final Shopify → Base interna (estado final)")
    st.json(shopify_sync_final)

    st.success("🎉 Pipeline completo Zoho ↔ Shopify finalizado correctamente.")


# (Opcional) Si quieres, aún puedes conservar abajo los 3 botones granulares
# para casos avanzados / debugging.
# Definimos las tiendas

st.divider()        
st.subheader("🖼 Gestión de imágenes de productos")
st.markdown("### Cargar imágenes a los productos en Shopify")
if st.button("Base interna -> Imágenes Shopify"):
    from library.upload_local_images import SHOPIFY_IMAGES

    # Contenedor y buffer para el log en pantalla
    log_placeholder = st.empty()
    log_lines = []

    st.info("⏳ Inicializando carga de imágenes a Shopify...")

    with st.spinner("Sincronizando imágenes con Shopify..."):
        for store in stores:
            st.write(f"📤 Sincronizando imágenes a Shopify para **{store}**...")
            from library.shopify_images_sync import ShopifyImageSync
            uploader = ShopifyImageSync(yaml_data, store)
            summary = uploader.sync_images()  # puedes pasar logger=streamlit_logger si quieres
            print(summary)
st.markdown("### Cargar imágenes a la base interna")
from library.upload_local_images import SHOPIFY_IMAGES
# Si ya creaste el módulo para subir de Mongo → Shopify:
# from library.shopify_images_sync import ShopifyImageSync
# Instancia del gestor de imágenes (nota el orden de argumentos)
img_manager = SHOPIFY_IMAGES(working_folder, yaml_data)

images_path = img_manager.BASE_IMAGES_FOLDER
st.write(f"Carpeta base de imágenes: `{images_path}`")

col1, col2, col3, col4 = st.columns(4)

# --- Botón 1: Abrir carpeta de imágenes en el sistema operativo ---
with col1:
    if os.path.exists(images_path):
        if st.button("Abrir carpeta de imágenes"):
            # Esto funciona cuando corres Streamlit LOCAL en tu máquina
            system = platform.system()
            try:
                if system == "Windows":
                    os.startfile(images_path)  # type: ignore[attr-defined]
                elif system == "Darwin":  # macOS
                    subprocess.Popen(["open", images_path])
                elif system == "Linux":
                    subprocess.Popen(["xdg-open", images_path])
                st.info("Se abrió la carpeta en el explorador de archivos (ejecución local).")
            except Exception as e:
                st.error(f"No se pudo abrir la carpeta automáticamente: {e}")
    else:
        st.info("La carpeta aún no existe. Usa 'Generar carpetas desde Zoho'.")

# --- Botón 2: Generar estructura de carpetas desde Zoho ---
with col2:
    if st.button("Generar carpetas desde Zoho"):
        img_manager.prepare_image_folders_from_zoho()
        st.success("Estructura de carpetas generada. Agrega imágenes y vuelve.")

# --- Botón 3: Local → Mongo (subir imágenes reescaladas) ---
with col3:
    if st.button("Local → Mongo (imagenes)"):
        img_manager.load_images_to_mongo()
        st.success("Sincronización local → Mongo completada.")

# --- Botón 4: Mongo → Local (bajar imágenes desde Mongo) ---
with col4:
    if st.button("Mongo → Local (imagenes)"):
        img_manager.mongo_to_local()
        st.success("Sincronización Mongo → local completada.")

st.markdown("### 📤 Subir imágenes desde el navegador a una carpeta local")

item_id = st.text_input("item_id de Zoho", "")
alias = st.text_input("Nombre corto (opcional, se usará en el nombre de la carpeta)", "")

uploaded_files = st.file_uploader(
    "Arrastra aquí una o varias imágenes",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if st.button("Guardar imágen a item"):
    if not item_id:
        st.error("Necesitas indicar al menos el item_id.")
    elif not uploaded_files:
        st.warning("No se seleccionó ningún archivo.")
    else:
        # usamos el mismo sanitizador que en la clase
        clean_alias = img_manager.sanitize_name(alias) if alias else ""
        folder_name = f"{item_id}_{clean_alias}" if clean_alias else item_id
        dest_folder = os.path.join(images_path, folder_name)
        os.makedirs(dest_folder, exist_ok=True)

        saved = 0
        for uf in uploaded_files:
            file_path = os.path.join(dest_folder, uf.name)
            with open(file_path, "wb") as out:
                out.write(uf.read())
            saved += 1

        st.success(f"Guardadas {saved} imágenes en: {dest_folder}")