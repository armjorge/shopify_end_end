from colorama import Fore, Style, init
from pymongo import MongoClient
import requests
import os
import sys
import yaml
from dotenv import load_dotenv


class SHOPIFY_MONGODB:
    def __init__(self, working_folder, yaml_data, store):
        init(autoreset=True)
        print(Fore.BLUE + f"\tINICIALIZANDO SHOPIFY_MONGODB {store}" + Style.RESET_ALL)

        self.working_folder = working_folder
        self.data = yaml_data
        self.shopify_conf = yaml_data[store]   # config de la tienda en el YAML
        self.store = store

        # REST Admin API base
        api_version = self.shopify_conf.get("api_version", "2024-10")
        self.base_url = f"https://{self.shopify_conf['store_name']}/admin/api/{api_version}"

        # Headers REST
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.shopify_conf["access_token"],
        }

        # Log file opcional si en algún momento quieres log a archivo
        self.log_file = os.path.join(self.working_folder, f"{store}_shopify_sync_log.json")

    def _get_single_location_id(self, logger=None):
        """
        Devuelve un único location_id para la tienda actual.
        Prioridad:
        1) Si existe self.shopify_conf['location_id'], usarlo.
        2) Si no, consultar /locations.json y si hay exactamente UNA location activa y no-legacy, usarla.
        3) Si no se puede determinar (0 o >1), devolver None.
        """
        def _log(msg: str):
            if callable(logger):
                logger(str(msg))

        # 1) Revisar si ya viene en el YAML
        conf_location = self.shopify_conf.get("location_id")
        if conf_location:
            msg = f"ℹ️ Usando location_id desde configuración de {self.store}: {conf_location}"
            print(Fore.BLUE + msg + Style.RESET_ALL)
            _log(msg)
            return conf_location

        # 2) Consultar /locations.json
        url = f"{self.base_url}/locations.json"
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
        except requests.RequestException as e:
            msg = f"❌ Error de conexión al obtener locations para {self.store}: {e}"
            print(Fore.RED + msg + Style.RESET_ALL)
            _log(msg)
            return None

        if response.status_code != 200:
            msg = f"⚠️ Error al obtener locations para {self.store}: HTTP {response.status_code} - {response.text}"
            print(Fore.RED + msg + Style.RESET_ALL)
            _log(msg)
            return None

        data = response.json()
        locations = data.get("locations", [])

        # Filtrar activas y no legacy (para evitar cosas tipo Syncee)
        candidates = [
            loc for loc in locations
            if loc.get("active", False) and not loc.get("legacy", False)
        ]

        if len(candidates) == 1:
            loc = candidates[0]
            loc_id = loc["id"]
            msg = f"✅ Detectada una única location activa/no-legacy para {self.store}: {loc_id} ({loc.get('name')})"
            print(Fore.GREEN + msg + Style.RESET_ALL)
            _log(msg)
            return loc_id

        # Si no hay candidates, pero sí hay locations, intenta fallback a cualquier activa
        if not candidates and locations:
            active_locs = [loc for loc in locations if loc.get("active", False)]
            if len(active_locs) == 1:
                loc = active_locs[0]
                loc_id = loc["id"]
                msg = f"✅ Detectada una única location activa (fallback) para {self.store}: {loc_id} ({loc.get('name')})"
                print(Fore.GREEN + msg + Style.RESET_ALL)
                _log(msg)
                return loc_id

        # Si llegamos aquí, no hay forma clara de elegir una sola
        msg = (
            f"⚠️ No se pudo determinar un único location_id para {self.store}. "
            f"Locations encontradas: {len(locations)}. "
            "Configura 'location_id' en el config.yml para esta tienda."
        )
        print(Fore.YELLOW + msg + Style.RESET_ALL)
        _log(msg)
        return None

    def sync_shopify_to_mongo(self, logger=None):
        """
        Consulta varios endpoints de Shopify (REST Admin API) y los sincroniza en MongoDB.

        - Base de datos: una por tienda (managed_store_one, managed_store_two, ...)
        - Colecciones: una por endpoint (orders, inventory_levels, ...)
        - Cada documento es un renglón único del endpoint, con PK = pk_field (id, inventory_item_id, ...)
        """

        def _log(msg: str):
            if callable(logger):
                logger(str(msg))

        mongo_db_url = self.data["non_sql_database"]["url"]
        client = MongoClient(mongo_db_url)

        # 👉 Cada tienda es una base de datos
        db_name = self.store   # "managed_store_one", "managed_store_two"
        db = client[db_name]

        endpoints = {
            "orders": {
                "pk": "id",
                "root_key": "orders",
                "extra_params": {"status": "any"},
            },
            "inventory_levels": {
                "pk": "inventory_item_id",
                "root_key": "inventory_levels",
                "extra_params": {},  # location_ids se resuelven dinámicamente
            },

            "products": {
            "pk": "id",
            "root_key": "products",
            "extra_params": {}
        }}

        summary = {}

        for endpoint, conf in endpoints.items():
            pk_field = conf["pk"]
            root_key = conf["root_key"]
            extra_params = dict(conf.get("extra_params", {}))  # copia

            # Si el endpoint requiere location_ids, los resolvemos dinámicamente
            if endpoint in ("inventory_levels", "inventory_items"):
                loc_id = self._get_single_location_id(logger=logger)
                if not loc_id:
                    msg = f"⚠️ No se pudo determinar location_id para {self.store}. Se omite sync de {endpoint}."
                    print(Fore.YELLOW + msg + Style.RESET_ALL)
                    _log(msg)
                    continue
                extra_params["location_ids"] = loc_id

            # 📁 Colección por endpoint dentro de la DB de la tienda
            collection = db[endpoint]

            # Índice único por el campo de Shopify (id, inventory_item_id, etc.)
            collection.create_index(pk_field, unique=True)

            msg = f"Sincronizando {endpoint} de Shopify para la tienda (DB): {self.store}"
            print(Fore.BLUE + msg + Style.RESET_ALL)
            _log(msg)

            total_docs = 0
            inserted = 0
            updated = 0

            url = f"{self.base_url}/{endpoint}.json"
            params = {"limit": 250}
            params.update(extra_params)

            while True:
                try:
                    response = requests.get(url, headers=self.headers, params=params, timeout=30)
                except requests.RequestException as e:
                    msg = f"❌ Error de conexión con Shopify ({endpoint}): {e}"
                    print(Fore.RED + msg + Style.RESET_ALL)
                    _log(msg)
                    break

                if response.status_code != 200:
                    msg = f"⚠️ Error al obtener {endpoint}: HTTP {response.status_code} - {response.text}"
                    print(Fore.RED + msg + Style.RESET_ALL)
                    _log(msg)
                    break

                data = response.json()
                records = data.get(root_key, [])

                if not records:
                    msg = f"⚠️ No se encontraron registros en {endpoint} en esta página."
                    print(Fore.YELLOW + msg + Style.RESET_ALL)
                    _log(msg)

                for rec in records:
                    if pk_field not in rec:
                        msg = f"⚠️ Registro sin campo '{pk_field}' en {endpoint}, se omite."
                        print(Fore.YELLOW + msg + Style.RESET_ALL)
                        _log(msg)
                        continue

                    filter_query = {pk_field: rec[pk_field]}
                    update_query = {"$set": rec}

                    result = collection.update_one(filter_query, update_query, upsert=True)
                    total_docs += 1

                    if result.upserted_id is not None:
                        inserted += 1
                    elif result.matched_count > 0:
                        updated += 1

                msg = f"✅ {endpoint}: página procesada. Registros en esta página: {len(records)}"
                print(Fore.GREEN + msg + Style.RESET_ALL)
                _log(msg)

                # Paginación con Link header
                link_header = response.headers.get("Link")
                if not link_header or 'rel="next"' not in link_header:
                    break

                next_url = None
                parts = link_header.split(",")
                for part in parts:
                    if 'rel="next"' in part:
                        segment = part.split(";")[0].strip()
                        next_url = segment.strip("<>")
                        break

                if not next_url:
                    break

                url = next_url
                params = {}  # page_info ya viene en la URL

            msg = (
                f"📊 Resumen {endpoint} ({self.store}): "
                f"total procesados={total_docs}, insertados nuevos={inserted}, actualizados={updated}"
            )
            print(Fore.CYAN + msg + Style.RESET_ALL)
            _log(msg)

            summary[endpoint] = {
                "processed": total_docs,
                "inserted": inserted,
                "updated": updated,
            }

        client.close()
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
        print(f"Sincronizando inventario para {store}...")
        app = SHOPIFY_MONGODB(working_folder, yaml_data, store)
        #from library.shopify_mongo_db import SHOPIFY_MONGODB
     
        app.sync_shopify_to_mongo(store)    
        