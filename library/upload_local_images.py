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
import unicodedata
import shutil


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



    def sanitize_name(self, raw: str, max_len: int = 60) -> str:
        """
        Sanitiza para nombre de carpeta cross-platform:
        - Normaliza unicode (quita acentos)
        - Remueve caracteres inválidos Windows/macOS
        - Colapsa espacios/guiones bajos
        - Evita trailing dots/spaces
        - Limita longitud (solo para el nombre, no incluye item_id)
        """
        if not raw:
            return ""

        # 1) normalize unicode -> ascii
        s = unicodedata.normalize("NFKD", str(raw))
        s = s.encode("ascii", "ignore").decode("ascii")

        # 2) remove invalid filesystem chars (Windows set + control chars)
        s = re.sub(r'[<>:"/\\|?*\x00-\x1F]', " ", s)

        # 3) collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()

        # 4) replace spaces with underscore (opcional, consistente)
        s = s.replace(" ", "_")

        # 5) collapse multiple underscores
        s = re.sub(r"_+", "_", s).strip("_")

        # 6) Windows: folder names cannot end with dot/space
        s = s.rstrip(". ").strip()

        # 7) reserved device names (Windows)
        reserved = {
            "CON","PRN","AUX","NUL",
            "COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
            "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9",
        }
        if s.upper() in reserved:
            s = f"{s}_item"

        # 8) enforce max length
        if max_len and len(s) > max_len:
            s = s[:max_len].rstrip("_").rstrip(". ")

        return s


    def _get_zoho_item_name_by_id(self, client, item_id: str) -> str:
        zoho_db = client["Zoho_Inventory"]
        items_coll = zoho_db["items"]
        doc = items_coll.find_one({"item_id": item_id}, {"name": 1, "item_name": 1})
        if not doc:
            return ""
        return (doc.get("name") or doc.get("item_name") or "").strip()


    def _desired_folder_name(self, client, item_id: str) -> str:
        raw_name = self._get_zoho_item_name_by_id(client, item_id)
        clean = self.sanitize_name(raw_name, max_len=60)  # ajusta a gusto
        if not clean:
            clean = "unnamed"
        return f"{item_id}_{clean}"


    def _find_candidate_folders(self, base_folder: str, item_id: str):
        """
        Devuelve lista de carpetas (nombres) que "pertenecen" a ese item_id.
        Existencia se determina SOLO por item_id:
        - exact match: item_id
        - prefix match: item_id + "_"
        """
        out = []
        if not os.path.exists(base_folder):
            return out

        for f in os.listdir(base_folder):
            p = os.path.join(base_folder, f)
            if not os.path.isdir(p):
                continue
            if f == item_id or f.startswith(item_id + "_"):
                out.append(f)

        # orden estable (para que merge sea determinista)
        return sorted(out)
    def resize_image_to_max(self, image_path, max_size=300):
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

    def _get_mongo_client(self) -> MongoClient:
        mongo_url = self.data["non_sql_database"]["url"]
        return MongoClient(mongo_url)

    # ================== CASO 1: PRIMERA VEZ ==================

    def prepare_image_folders_from_zoho(self):
        client = self._get_mongo_client()
        zoho_db = client["Zoho_Inventory"]
        items_coll = zoho_db["items"]

        os.makedirs(self.BASE_IMAGES_FOLDER, exist_ok=True)

        cursor = items_coll.find({"status": "active"}, {"item_id": 1})
        created = 0
        renamed = 0
        merged = 0
        skipped = 0

        print("\n🧱 Generando/normalizando estructura de carpetas para imágenes desde Zoho_Inventory.items...")

        for doc in cursor:
            item_id = str(doc.get("item_id") or "").strip()
            if not item_id:
                continue

            desired = self._desired_folder_name(client, item_id)
            desired_path = os.path.join(self.BASE_IMAGES_FOLDER, desired)

            candidates = self._find_candidate_folders(self.BASE_IMAGES_FOLDER, item_id)

            # Caso: no hay nada => crear
            if not candidates:
                os.makedirs(desired_path, exist_ok=True)
                created += 1
                continue

            # Si ya existe la deseada, ok (pero si hay extras, mergearlos)
            if desired in candidates:
                # merge extras -> desired
                extras = [c for c in candidates if c != desired]
                for old in extras:
                    old_path = os.path.join(self.BASE_IMAGES_FOLDER, old)
                    if os.path.isdir(old_path):
                        for fname in os.listdir(old_path):
                            src = os.path.join(old_path, fname)
                            dst = os.path.join(desired_path, fname)
                            if os.path.isfile(src):
                                # si existe mismo nombre, no lo pisamos: lo versionamos
                                if os.path.exists(dst):
                                    root, ext = os.path.splitext(fname)
                                    dst = os.path.join(desired_path, f"{root}__dup{ext}")
                                shutil.move(src, dst)
                        # intenta borrar si quedó vacía
                        try:
                            os.rmdir(old_path)
                        except OSError:
                            pass
                        merged += 1
                continue

            # Si hay un candidato (ej. item_id solo, o item_id_otro) => renombrar/merge
            # Nota: si hay varios candidatos y ninguno es desired, mergeamos todo hacia desired.
            os.makedirs(desired_path, exist_ok=True)

            for old in candidates:
                old_path = os.path.join(self.BASE_IMAGES_FOLDER, old)
                if not os.path.isdir(old_path):
                    continue

                # mover contenido hacia desired
                for fname in os.listdir(old_path):
                    src = os.path.join(old_path, fname)
                    dst = os.path.join(desired_path, fname)
                    if os.path.isfile(src):
                        if os.path.exists(dst):
                            root, ext = os.path.splitext(fname)
                            dst = os.path.join(desired_path, f"{root}__dup{ext}")
                        shutil.move(src, dst)

                # borrar carpeta vieja si queda vacía
                try:
                    os.rmdir(old_path)
                    renamed += 1
                except OSError:
                    # no estaba vacía o algo raro
                    skipped += 1

        print(f"✅ Carpetas creadas: {created} | renombradas/absorbidas: {renamed} | merges extra: {merged} | skips: {skipped}")
        print(f"📁 Base: {self.BASE_IMAGES_FOLDER}")
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
        base_folder = self.BASE_IMAGES_FOLDER
        client = self._get_mongo_client()

        mgmt_db = client["management"]
        coll = mgmt_db["product_images"]

        zoho_db = client["Zoho_Inventory"]
        items_coll = zoho_db["items"]

        os.makedirs(base_folder, exist_ok=True)

        docs = list(coll.find({}, {"item_id": 1, "images": 1}))
        if not docs:
            print("⚠️ No hay documentos en management.product_images para sincronizar hacia local.")
            return

        print(f"\n🖼️ Sincronizando imágenes desde MongoDB → carpetas locales en {base_folder}...")

        # Para saber qué ya está en Mongo (con o sin imágenes)
        mongo_item_ids = set()
        wrote_images = 0
        empty_docs = 0

        for doc in docs:
            item_id = str(doc.get("item_id") or "").strip()
            if not item_id:
                continue

            mongo_item_ids.add(item_id)

            # Buscar carpeta existente que empiece con item_id (exact o prefix)
            candidates = self._find_candidate_folders(base_folder, item_id)

            if candidates:
                # preferimos la que ya esté normalizada (tiene "_")
                chosen = None
                for c in candidates:
                    if c.startswith(item_id + "_"):
                        chosen = c
                        break
                if chosen is None:
                    chosen = candidates[0]
                candidate_folder = os.path.join(base_folder, chosen)
            else:
                # crear carpeta estándar con nombre desde Zoho
                desired = self._desired_folder_name(client, item_id)
                candidate_folder = os.path.join(base_folder, desired)
                os.makedirs(candidate_folder, exist_ok=True)

            # (Opcional pero útil) si la carpeta elegida no es la "desired", normaliza/mergea
            # para que siempre quede item_id_{name}
            try:
                desired = self._desired_folder_name(client, item_id)
                desired_path = os.path.join(base_folder, desired)
                if os.path.basename(candidate_folder) != desired:
                    # Crea destino y mueve contenido (sin borrar aún por si algo falla)
                    os.makedirs(desired_path, exist_ok=True)
                    for fname in os.listdir(candidate_folder):
                        src = os.path.join(candidate_folder, fname)
                        dst = os.path.join(desired_path, fname)
                        if os.path.isfile(src):
                            if os.path.exists(dst):
                                root, ext = os.path.splitext(fname)
                                dst = os.path.join(desired_path, f"{root}__dup{ext}")
                            shutil.move(src, dst)
                    # intenta borrar carpeta vieja si vacía
                    try:
                        os.rmdir(candidate_folder)
                    except OSError:
                        pass
                    candidate_folder = desired_path
            except Exception:
                # si Zoho no tiene nombre o algo falla, dejamos candidate_folder como estaba
                pass

            print(f"\n📂 item_id={item_id} → carpeta={candidate_folder}")

            # Borrar archivos existentes en la carpeta (reemplazo completo)
            for fname in os.listdir(candidate_folder):
                fpath = os.path.join(candidate_folder, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)

            images = doc.get("images", []) or []
            if not images:
                print("  ⚠️ Documento sin imágenes, carpeta quedará vacía.")
                empty_docs += 1
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
                wrote_images += 1

        # =======================
        # NUEVO: crear carpetas vacías para Zoho items activos no presentes en Mongo
        # =======================
        print("\n📦 Creando carpetas vacías para items activos en Zoho que NO están en management.product_images...")

        zoho_cursor = items_coll.find(
            {"status": "active"},
            {"item_id": 1}
        )

        created_empty = 0
        already_had_folder = 0
        skipped_no_id = 0

        for it in zoho_cursor:
            item_id = str(it.get("item_id") or "").strip()
            if not item_id:
                skipped_no_id += 1
                continue

            # Si ya está en Mongo, lo saltamos (ya se gestionó arriba)
            if item_id in mongo_item_ids:
                continue

            # Si ya existe alguna carpeta por item_id (aunque sea vieja), la normalizamos al desired
            candidates = self._find_candidate_folders(base_folder, item_id)
            desired = self._desired_folder_name(client, item_id)
            desired_path = os.path.join(base_folder, desired)

            if not candidates:
                os.makedirs(desired_path, exist_ok=True)
                print(f"  📁 (vacía) creada: {desired}")
                created_empty += 1
                continue

            # Existe algo: mergea todo hacia desired y deja la carpeta final vacía o con lo que hubiera
            os.makedirs(desired_path, exist_ok=True)
            moved_any = False

            for old in candidates:
                old_path = os.path.join(base_folder, old)
                if old_path == desired_path:
                    continue
                for fname in os.listdir(old_path):
                    src = os.path.join(old_path, fname)
                    dst = os.path.join(desired_path, fname)
                    if os.path.isfile(src):
                        if os.path.exists(dst):
                            root, ext = os.path.splitext(fname)
                            dst = os.path.join(desired_path, f"{root}__dup{ext}")
                        shutil.move(src, dst)
                        moved_any = True
                try:
                    os.rmdir(old_path)
                except OSError:
                    pass

            print(f"  🧱 normalizada: {desired} (moved_files={moved_any})")
            already_had_folder += 1

        print("\n✅ Sincronización MongoDB → local completada.")
        print(f"📌 Resumen:")
        print(f"  - item_ids en Mongo (procesados): {len(mongo_item_ids)}")
        print(f"  - imágenes escritas: {wrote_images}")
        print(f"  - docs en Mongo sin imágenes: {empty_docs}")
        print(f"  - carpetas vacías creadas (Zoho activos no en Mongo): {created_empty}")
        print(f"  - carpetas ya existentes normalizadas (Zoho activos no en Mongo): {already_had_folder}")
        if skipped_no_id:
            print(f"  - items Zoho sin item_id: {skipped_no_id}")
        
    
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
