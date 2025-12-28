# library/shopify_images_sync.py

import requests
from pymongo import MongoClient
from colorama import init, Fore, Style
from typing import Callable, Optional
import os
import sys
import yaml
from dotenv import load_dotenv


class ShopifyImageSync:
    """
    Sincroniza imágenes desde MongoDB (management.product_images)
    hacia Shopify, usando el mapping Zoho_Inventory.items_per_store.

    Flujo:
      - Para cada item en items_per_store con item_id y shopify_id:
          * Buscar documento en management.product_images con ese item_id.
          * Si existe y tiene imágenes:
              - Borrar todas las imágenes actuales del producto en Shopify.
              - Subir las nuevas imágenes en orden 'position'.
          * Si no existe documento de imágenes → se omite.
    """

    def __init__(self, yaml_data: dict, store_key: str):
        """
        yaml_data: config.yml ya cargado (donde vienen non_sql_database y las tiendas).
        store_key: por ejemplo 'managed_store_one'
        """
        init(autoreset=True)
        self.data = yaml_data
        self.store_key = store_key

        # Mongo
        mongo_url = self.data["non_sql_database"]["url"]
        self.client = MongoClient(mongo_url)

        # Shopify config
        shop_conf = self.data[self.store_key]
        api_version = shop_conf.get("api_version", "2024-10")
        self.base_url = f"https://{shop_conf['store_name']}/admin/api/{api_version}"
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": shop_conf["access_token"],
        }

    def _log(self, msg: str, logger: Optional[Callable[[str], None]] = None):
        if callable(logger):
            logger(msg)
        else:
            print(msg)

    def _get_items_mapping(self):
        """
        Lee Zoho_Inventory.items_per_store y devuelve la lista de items
        para la store actual (self.store_key).
        """
        db_zoho = self.client["Zoho_Inventory"]
        coll = db_zoho["items_per_store"]

        doc = coll.find_one({"store": self.store_key})
        if not doc or "items" not in doc:
            return []

        return doc["items"]

    def _get_product_images_doc(self, item_id: str):
        """
        Devuelve el documento de imágenes para un item_id en management.product_images.
        """
        db_mgmt = self.client["management"]
        coll = db_mgmt["product_images"]
        return coll.find_one({"item_id": str(item_id)})

    def _delete_existing_images(self, shopify_id: str, logger=None):
        """
        Borra todas las imágenes actuales de un producto en Shopify.
        """
        # Listar imágenes actuales
        list_url = f"{self.base_url}/products/{shopify_id}/images.json"
        resp = requests.get(list_url, headers=self.headers)

        if not resp.ok:
            self._log(
                f"{Fore.RED}[IMG][{self.store_key}] ERROR {resp.status_code} al listar imágenes "
                f"de product_id={shopify_id}: {resp.text}{Style.RESET_ALL}",
                logger,
            )
            return

        images = resp.json().get("images", [])
        if not images:
            self._log(
                f"[IMG][{self.store_key}] product_id={shopify_id} no tiene imágenes previas.",
                logger,
            )
            return

        self._log(
            f"[IMG][{self.store_key}] product_id={shopify_id} → borrando {len(images)} imágenes previas...",
            logger,
        )

        for im in images:
            img_id = im.get("id")
            if not img_id:
                continue
            del_url = f"{self.base_url}/products/{shopify_id}/images/{img_id}.json"
            resp_del = requests.delete(del_url, headers=self.headers)
            if not resp_del.ok:
                self._log(
                    f"{Fore.RED}[IMG][{self.store_key}] ERROR {resp_del.status_code} al borrar image_id={img_id} "
                    f"de product_id={shopify_id}: {resp_del.text}{Style.RESET_ALL}",
                    logger,
                )
            else:
                self._log(
                    f"[IMG][{self.store_key}] Borrada image_id={img_id} de product_id={shopify_id}",
                    logger,
                )

    def _upload_new_images(self, shopify_id: str, images: list, logger=None):
        """
        Sube las imágenes proporcionadas (lista de dicts tal como vienen de Mongo)
        al producto en Shopify.
        """
        post_url = f"{self.base_url}/products/{shopify_id}/images.json"

        # Ordenamos por 'position' si existe
        images_sorted = sorted(images, key=lambda x: x.get("position", 9999))

        for img in images_sorted:
            attachment = img.get("attachment")
            if not attachment:
                self._log(
                    f"[IMG][{self.store_key}] item_id sin attachment base64, se omite una imagen.",
                    logger,
                )
                continue

            filename = img.get("filename")
            if not filename:
                position = img.get("position", 1)
                filename = f"{shopify_id}_{position}.jpg"

            payload = {
                "image": {
                    "attachment": attachment,
                    "filename": filename,
                    "position": img.get("position", 1),
                    "alt": img.get("alt") or filename,
                }
            }

            resp_post = requests.post(post_url, headers=self.headers, json=payload)
            if not resp_post.ok:
                self._log(
                    f"{Fore.RED}[IMG][{self.store_key}] ERROR {resp_post.status_code} al subir imagen "
                    f"para product_id={shopify_id} ({filename}): {resp_post.text}{Style.RESET_ALL}",
                    logger,
                )
            else:
                new_img = resp_post.json().get("image", {})
                self._log(
                    f"[IMG][{self.store_key}] OK subida imagen filename={filename} "
                    f"→ image_id={new_img.get('id')} en product_id={shopify_id}",
                    logger,
                )

    def sync_images(self, logger: Optional[Callable[[str], None]] = None) -> dict:
        """
        Método principal:
        - Para cada par item_id–shopify_id en items_per_store:
            * Si hay documento en management.product_images con ese item_id:
                - Borra imágenes previas en Shopify
                - Sube nuevas imágenes
            * Si NO hay documento → se omite.

        Devuelve un pequeño resumen.
        """
        self._log(
            f"{Fore.CYAN}\n[IMG][{self.store_key}] Iniciando sincronización MongoDB → Shopify...{Style.RESET_ALL}",
            logger,
        )

        items_mapping = self._get_items_mapping()
        total_pairs = len(items_mapping)
        self._log(
            f"[IMG][{self.store_key}] items_per_store → {total_pairs} items configurados.",
            logger,
        )

        processed = 0
        skipped_no_images = 0
        skipped_no_ids = 0
        errors = 0

        for it in items_mapping:
            item_id = str(it.get("item_id") or "").strip()
            shopify_id = str(it.get("shopify_id") or "").strip()

            if not item_id or not shopify_id:
                skipped_no_ids += 1
                continue

            img_doc = self._get_product_images_doc(item_id)
            if not img_doc or not img_doc.get("images"):
                # No hay doc de imágenes para ese item_id → se omite
                self._log(
                    f"[IMG][{self.store_key}] item_id={item_id}, shopify_id={shopify_id}: "
                    f"sin imágenes en management.product_images, se omite.",
                    logger,
                )
                skipped_no_images += 1
                continue

            images = img_doc["images"]
            self._log(
                f"\n[IMG][{self.store_key}] item_id={item_id}, shopify_id={shopify_id}: "
                f"{len(images)} imágenes encontradas → sincronizando...",
                logger,
            )

            try:
                # 1) Borrar imágenes existentes en Shopify
                self._delete_existing_images(shopify_id, logger=logger)
                # 2) Subir nuevas imágenes desde Mongo
                self._upload_new_images(shopify_id, images, logger=logger)
                processed += 1
            except Exception as e:
                self._log(
                    f"{Fore.RED}[IMG][{self.store_key}] ERROR inesperado con item_id={item_id}, "
                    f"shopify_id={shopify_id}: {e}{Style.RESET_ALL}",
                    logger,
                )
                errors += 1

        summary = {
            "store": self.store_key,
            "total_pairs_in_items_per_store": total_pairs,
            "processed_with_images": processed,
            "skipped_no_images_doc": skipped_no_images,
            "skipped_missing_ids": skipped_no_ids,
            "errors": errors,
        }

        self._log(
            f"\n[IMG][{self.store_key}] Resumen: {summary}",
            logger,
        )
        return summary

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
    # Lanza la función de automatización            
    stores = ["managed_store_one", "managed_store_two"]
    for store in stores: 
        print(f"Sincronizando Imágenes para {store}...")
        app = ShopifyImageSync(yaml_data, store)
        app.sync_images()

    
