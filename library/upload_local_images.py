import os
import re
import base64
from io import BytesIO
from PIL import Image
from pymongo import MongoClient
from datetime import datetime
from colorama import init, Fore, Style
from dotenv import load_dotenv
import yaml
import sys


class SHOPIFY_IMAGES: 
    def __init__(self, working_folder, yaml_data, store=None):
        init(autoreset=True)
        print(Fore.BLUE + "\tInicializando EL MÓDULO DE CARGA DE IMÁGENES" + Style.RESET_ALL)
        self.working_folder = working_folder
        self.data = yaml_data
        self.store = store
        self._location_id_cache: dict[str, int] = {}
        self.BASE_IMAGES_FOLDER = os.path.join(self.working_folder, "Imagenes_Productos")  # carpeta raíz
        # Mantengo este atributo, pero realmente usamos self.data["non_sql_database"]["url"]
        self.MONGO_URL = "mongodb://localhost:27017"

    # ================== HELPERS ==================

    def resize_image_to_max(self, image_path, max_size=1200):
        """
        Abre una imagen, la reescala manteniendo proporción
        para que el lado más grande sea max_size (px).
        Retorna (bytes_jpeg, width, height).
        """
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((max_size, max_size), Image.LANCZOS)

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        width, height = img.size
        return buffer.read(), width, height

    def folder_name_to_item_id(self, folder_name: str) -> str | None:
        """
        Extrae el item_id a partir del nombre de la carpeta.
        Regla simple: toma el primer bloque antes de '_' o espacio.
        Ejemplos:
        '1072824000000295013_Riafol' -> '1072824000000295013'
        '1072824000001156047 Riafol 20ml' -> '1072824000001156047'
        """
        folder_name = folder_name.strip()
        for sep in ["_", " "]:
            if sep in folder_name:
                return folder_name.split(sep)[0]
        return folder_name  # si no tiene separador, usamos todo

    def sanitize_name(self, name: str) -> str:
        """
        Limpia el 'name' para usarlo en nombres de carpetas:
        - Quita espacios extra.
        - Reemplaza caracteres no alfanuméricos por '_'.
        - Colapsa múltiples '_' seguidos.
        - Limita longitud.
        """
        if not name:
            return ""
        name = name.strip()
        # Reemplazar caracteres raros por '_'
        name = re.sub(r"[^A-Za-z0-9]+", "_", name)
        # Quitar '_' al inicio/fin y colapsar múltiples
        name = re.sub(r"_+", "_", name).strip("_")
        # Limitar longitud razonable
        return name[:60]

    def _get_mongo_client(self) -> MongoClient:
        mongo_url = self.data["non_sql_database"]["url"]
        return MongoClient(mongo_url)

    # ================== CASO 1: PRIMERA VEZ ==================

    def prepare_image_folders_from_zoho(self):
        """
        Primera vez:
        - Crea carpeta BASE_IMAGES_FOLDER si no existe.
        - Obtiene item_id y name de Zoho_Inventory.items (status='active').
        - Genera subcarpetas: item_id + '_' + nombre_sanitizado.
        - Sugiere al usuario agregar imágenes y volver.
        """
        client = self._get_mongo_client()
        zoho_db = client["Zoho_Inventory"]
        items_coll = zoho_db["items"]

        os.makedirs(self.BASE_IMAGES_FOLDER, exist_ok=True)

        # Solo items activos
        cursor = items_coll.find({"status": "active"})
        count = 0

        print("\n🧱 Generando estructura de carpetas para imágenes desde Zoho_Inventory.items...")
        for doc in cursor:
            item_id = str(doc.get("item_id") or "").strip()
            if not item_id:
                continue

            raw_name = doc.get("name") or doc.get("item_name") or ""
            clean_name = self.sanitize_name(raw_name)
            if clean_name:
                folder_name = f"{item_id}_{clean_name}"
            else:
                folder_name = item_id

            folder_path = os.path.join(self.BASE_IMAGES_FOLDER, folder_name)
            os.makedirs(folder_path, exist_ok=True)
            count += 1

        print(f"✅ Se crearon/aseguraron {count} carpetas en: {self.BASE_IMAGES_FOLDER}")
        print("👉 Agrega imágenes a las carpetas correspondientes y vuelve a ejecutar la sincronización local → mongo_db.")

    # ================== CASO 2 y 3: LOCAL → MONGO_DB ==================

    def load_images_to_mongo(self):
        """
        Local → MongoDB:
        - Recorre subcarpetas en BASE_IMAGES_FOLDER.
        - Para cada item_id detectado en el nombre de carpeta:
            - Lee imágenes válidas.
            - Reescala y convierte a JPEG.
            - Guarda/actualiza documento en management.product_images
              *reemplazando* el arreglo de imágenes existente.
        """
        base_folder = self.BASE_IMAGES_FOLDER
        client = self._get_mongo_client()
        db = client["management"]
        coll = db["product_images"]

        allowed_ext = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}

        if not os.path.exists(base_folder):
            print(f"⚠️ Carpeta base de imágenes no existe: {base_folder}")
            print("   Ejecuta primero prepare_image_folders_from_zoho() para generar la estructura.")
            return

        subfolders = [
            f for f in os.listdir(base_folder)
            if os.path.isdir(os.path.join(base_folder, f))
        ]

        if not subfolders:
            print(f"⚠️ No se encontraron subcarpetas en {base_folder}.")
            print("   Ejecuta primero prepare_image_folders_from_zoho() y agrega imágenes.")
            return

        for folder in subfolders:
            folder_path = os.path.join(base_folder, folder)
            if not os.path.isdir(folder_path):
                continue

            item_id = self.folder_name_to_item_id(folder)
            if not item_id:
                print(f"[SKIP] Carpeta {folder} sin item_id detectable")
                continue

            print(f"\n📂 Procesando carpeta {folder} → item_id={item_id}")

            images_docs = []
            position = 1

            for filename in sorted(os.listdir(folder_path)):
                _, ext = os.path.splitext(filename)
                if ext not in allowed_ext:
                    continue

                file_path = os.path.join(folder_path, filename)
                print(f"  🖼️ Reescalando {filename}...")

                img_bytes, width, height = self.resize_image_to_max(file_path)

                b64_str = base64.b64encode(img_bytes).decode("ascii")

                images_docs.append({
                    "filename": filename,
                    "attachment": b64_str,
                    "content_type": "image/jpeg",  # normalizamos a jpeg
                    "width": width,
                    "height": height,
                    "position": position,
                    "alt": filename,  # luego lo puedes mejorar
                    "created_at": datetime.utcnow(),
                })
                position += 1

            if not images_docs:
                print(f"  ⚠️ No se encontraron imágenes válidas en {folder}")
                continue

            # Upsert del documento por item_id
            result = coll.update_one(
                {"item_id": item_id},
                {
                    "$set": {
                        "item_id": item_id,
                        "images": images_docs,  # 🔁 Reemplaza TODAS las imágenes previas
                        "updated_at": datetime.utcnow(),
                    }
                },
                upsert=True,
            )

            if result.upserted_id:
                print(f"  ✅ Insertado documento nuevo para item_id={item_id}")
            else:
                print(f"  🔁 Actualizado documento existente para item_id={item_id} (imágenes reemplazadas)")

    # ================== CASO 3: MONGO_DB → LOCAL ==================

    def mongo_to_local(self):
        """
        MongoDB → Local:
        - Lee management.product_images.
        - Para cada item_id:
            - Busca una carpeta cuyo nombre comience con item_id.
              Si no existe, crea una.
            - Borra TODAS las imágenes actuales de esa carpeta.
            - Escribe las nuevas imágenes decodificando el base64.
        """
        base_folder = self.BASE_IMAGES_FOLDER
        client = self._get_mongo_client()
        db = client["management"]
        coll = db["product_images"]

        os.makedirs(base_folder, exist_ok=True)

        docs = list(coll.find({}))
        if not docs:
            print("⚠️ No hay documentos en management.product_images para sincronizar hacia local.")
            return

        print(f"\n🖼️ Sincronizando imágenes desde MongoDB → carpetas locales en {base_folder}...")

        for doc in docs:
            item_id = str(doc.get("item_id") or "").strip()
            if not item_id:
                continue

            # Buscar carpeta existente que empiece con item_id
            candidate_folder = None
            for folder in os.listdir(base_folder):
                folder_path = os.path.join(base_folder, folder)
                if os.path.isdir(folder_path) and folder.startswith(item_id):
                    candidate_folder = folder_path
                    break

            if candidate_folder is None:
                # Si no existe, creamos carpeta simple con item_id
                candidate_folder = os.path.join(base_folder, item_id)
                os.makedirs(candidate_folder, exist_ok=True)

            print(f"\n📂 item_id={item_id} → carpeta={candidate_folder}")

            # Borrar archivos existentes en la carpeta (reemplazo completo)
            for fname in os.listdir(candidate_folder):
                fpath = os.path.join(candidate_folder, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)

            images = doc.get("images", []) or []
            if not images:
                print("  ⚠️ Documento sin imágenes, carpeta quedará vacía.")
                continue

            # Escribir nuevas imágenes
            for img in images:
                attachment_b64 = img.get("attachment")
                if not attachment_b64:
                    continue

                try:
                    img_bytes = base64.b64decode(attachment_b64)
                except Exception as e:
                    print(f"  ⚠️ Error al decodificar imagen base64 para item_id={item_id}: {e}")
                    continue

                filename = img.get("filename")
                if not filename:
                    position = img.get("position", 1)
                    filename = f"{item_id}_{position}.jpg"

                file_path = os.path.join(candidate_folder, filename)
                with open(file_path, "wb") as f:
                    f.write(img_bytes)

                print(f"  💾 Guardada imagen {filename}")

        print("\n✅ Sincronización MongoDB → local completada.")


# ================== SCRIPT CLI PRINCIPAL ==================



if __name__ == "__main__":
    BASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # Aseguramos que BASE_PATH esté en sys.path
    if BASE_PATH not in sys.path:
        sys.path.insert(0, BASE_PATH)

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
            print(f"✅ MAIN_PATH tomado desde .env: {working_folder}")
        else:
            print(
                f"⚠️ Se encontró .env en {env_file} pero la variable {folder_name} no está definida.\n"
                f"Se usará BASE_PATH como working_folder: {working_folder}"
            )

    else:
        # Probablemente estamos en Render.com (no hay .env en el repo)
        env_main_path = os.getenv(folder_name)

        if env_main_path:
            # Caso ideal: definiste MAIN_PATH en las environment vars de Render
            working_folder = env_main_path
            print(f"✅ MAIN_PATH tomado de variables de entorno del sistema: {working_folder}")
        else:
            # Último fallback: el directorio actual del proceso (repo en Render)
            working_folder = os.getcwd()
            print(
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
        print(f"✅ Se encontró configuración raíz: {root_yaml}")
    else:
        print(f"⚠️ No se encontró configuración raíz en: {root_yaml}")

    if pkg_exists:
        print(f"✅ Se encontró configuración de paquete: {pkg_yaml}")
    else:
        print(f"⚠️ No se encontró configuración de paquete en: {pkg_yaml}")

    # Si no existe ninguno, detenemos
    if not root_exists and not pkg_exists:
        print(
            "❌ No se encontró ningún archivo de configuración.\n"
            f"- {root_yaml}\n"
            f"- {pkg_yaml}"
        )
        sys.exit(1)

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

    # ====== Lógica de escenarios ======
    img_manager = SHOPIFY_IMAGES(working_folder, yaml_data)
    base_folder = img_manager.BASE_IMAGES_FOLDER

    client = img_manager._get_mongo_client()
    mgmt_db = client["management"]
    coll = mgmt_db["product_images"]

    try:
        mongo_has_docs = coll.estimated_document_count() > 0
    except Exception:
        mongo_has_docs = False

    base_exists = os.path.exists(base_folder)
    subfolders = []
    if base_exists:
        subfolders = [
            f for f in os.listdir(base_folder)
            if os.path.isdir(os.path.join(base_folder, f))
        ]
    has_subfolders = len(subfolders) > 0
    # --- Caso 1: primera vez (no carpeta o sin subcarpetas) y sin base en Mongo ---
    if (not base_exists or not has_subfolders) and not mongo_has_docs:
        print("\n🔰 Escenario detectado: primera vez (sin estructura de imágenes ni base en MongoDB).")
        img_manager.prepare_image_folders_from_zoho()
        # Aquí se termina: el usuario debe agregar imágenes y volver a correr.
        sys.exit(0)

    # --- Caso 2: ya hay carpetas con imágenes, pero MongoDB aún no tiene base ---
    if has_subfolders and not mongo_has_docs:
        print("\n📤 Escenario detectado: carpetas locales presentes, MongoDB sin base de imágenes.")
        print("    Se realizará sincronización local → mongo_db (creación de documentos).")
        img_manager.load_images_to_mongo()
        sys.exit(0)

    # --- Caso 3: carpetas + base Mongo existentes (maduro) ---
    if has_subfolders and mongo_has_docs:
        print("\n🔁 Escenario detectado: carpetas locales y base de imágenes en MongoDB (estado maduro).")
        print("Elige la dirección de sincronización:")
        print("  1) local → mongo_db  (reemplaza documentos en Mongo con las imágenes de las carpetas)")
        print("  2) mongo_db → local  (reemplaza archivos locales con las imágenes guardadas en Mongo)")
        choice = input("Opción [1/2] (default 1): ").strip() or "1"

        if choice == "2":
            img_manager.mongo_to_local()
        else:
            img_manager.load_images_to_mongo()

        sys.exit(0)

    # Caso raro: no hay subcarpetas pero sí Mongo (por ejemplo, se borró la carpeta base)
    if not has_subfolders and mongo_has_docs:
        print("\n⚠️ No se encontraron subcarpetas locales, pero sí existe base de imágenes en MongoDB.")
        print("    Se creará la carpeta base y se realizará mongo_db → local.")
        os.makedirs(base_folder, exist_ok=True)
        img_manager.mongo_to_local()
        sys.exit(0)
