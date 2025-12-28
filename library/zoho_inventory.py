from colorama import Fore, init, Style
import requests
import os
from pymongo import MongoClient
from colorama import Fore, Style
import requests
import yaml
import sys
from dotenv import load_dotenv


class ZOHO_INVENTORY:
    
    def __init__(self, working_folder, yaml_data, store=None):
        init(autoreset=True)
        print(Fore.BLUE + "\tInicializando ZOHO_INVENTORY"+ Style.RESET_ALL)
        self.working_folder = working_folder
        self.data = yaml_data
        self.yaml_path = os.path.join(self.working_folder, "config.yml")
        self.store = store

    def refresh_zoho_token(self):
        """Refresca el access_token de Zoho y actualiza el YAML."""
        try:
            with open(self.yaml_path, "r") as f:
                config = yaml.safe_load(f)

            zoho_conf = config.get("zoho", {})
            data = {
                "refresh_token": zoho_conf.get("refresh_token"),
                "client_id": zoho_conf.get("client_id"),
                "client_secret": zoho_conf.get("client_secret"),
                "grant_type": "refresh_token",
            }

            print(Fore.YELLOW + "🔄 Refrescando token de Zoho...")
            token_url = "https://accounts.zoho.com/oauth/v2/token"
            response = requests.post(token_url, data=data)
            token_data = response.json()

            if "access_token" not in token_data:
                print(Fore.RED + f"❌ Error al refrescar token: {token_data}")
                return None

            new_access_token = token_data["access_token"]
            config["zoho"]["access_token"] = new_access_token

            # Guardar YAML actualizado
            with open(self.yaml_path, "w") as f:
                yaml.safe_dump(config, f, sort_keys=False)

            # Actualizar en memoria
            self.data["zoho"]["access_token"] = new_access_token

            print(Fore.GREEN + "✅ Token renovado y YAML actualizado.")
            return new_access_token

        except Exception as e:
            print(Fore.RED + f"⚠️ Error al refrescar token: {e}")
            return None
        
    def sync_zoho_inventory_to_mongo(self, logger=None, needed_endpoints = None):
        """
        Consulta varios endpoints de Zoho Inventory y los sincroniza en MongoDB.
        - Crea la base de datos si no existe.
        - Crea una colección por endpoint (items, purchaseorders, etc.).
        - Hace upsert por el campo id de Zoho (item_id, purchaseorder_id, ...).

        Si se pasa un logger (callable), además de imprimir en consola,
        enviará mensajes de texto plano al logger (por ejemplo, para Streamlit).
        """

        def _log(msg: str):
            # Solo usamos logger si es una función/callable
            if callable(logger):
                logger(str(msg))

        db_name = "Zoho_Inventory"

        zoho_conf = self.data["zoho"]
        mongo_db_url = self.data["non_sql_database"]["url"]

        # endpoint -> (primary_key, list_key_en_respuesta)
        full_endpoints_zoho = {
            "items": {
                "pk": "item_id",
                "list_key": "items"
            },
            "purchaseorders": {
                "pk": "purchaseorder_id",
                "list_key": "purchaseorders"
            },
            "salesorders": {
                "pk": "salesorder_number",
                "list_key": "salesorders"
            },
            "invoices": {
                "pk": "invoice_id",
                "list_key": "invoices"
            },
            "contacts": {
                "pk": "contact_id",
                "list_key": "contacts"
            }
        }
        full_keys = list(full_endpoints_zoho.keys())

        if needed_endpoints is None:
            endpoints_zoho = full_endpoints_zoho
            chosen_keys = full_keys[:]   # todos
        else:
            # opcional: valida que no pidan endpoints inexistentes
            invalid = [k for k in needed_endpoints if k not in full_endpoints_zoho]
            if invalid:
                raise ValueError(f"Endpoints inválidos: {invalid}. Válidos: {full_keys}")

            endpoints_zoho = {k: full_endpoints_zoho[k] for k in needed_endpoints}
            chosen_keys = list(endpoints_zoho.keys())

        removed_keys = [k for k in full_keys if k not in chosen_keys]

        print(
            "🔎 Zoho endpoints | "
            f"full={full_keys} | "
            f"chosen={chosen_keys} | "
            f"removed={removed_keys}"
        )

        # Conexión a Mongo
        client = MongoClient(mongo_db_url)
        db = client[db_name]

        summary = {}

        for endpoint, conf in endpoints_zoho.items():
            pk_field = conf["pk"]
            list_key = conf["list_key"]

            msg = f"Obteniendo {endpoint} de Zoho Inventory desde el canal {self.store}"
            print(Fore.BLUE + msg + Style.RESET_ALL)
            _log(msg)

            collection = db[endpoint]
            # Aseguramos índice único por el campo de Zoho
            collection.create_index(pk_field, unique=True)

            page = 1
            per_page = 200
            total_docs = 0
            inserted = 0
            updated = 0

            while True:
                url = f"{zoho_conf['api_domain']}/inventory/v1/{endpoint}"

                params = {
                    "organization_id": zoho_conf["organization_id"],
                    "page": page,
                    "per_page": per_page,
                }

                headers = {
                    "Authorization": f"Zoho-oauthtoken {zoho_conf['access_token']}",
                    "Content-Type": "application/json",
                }

                try:
                    response = requests.get(url, headers=headers, params=params, timeout=30)
                except requests.RequestException as e:
                    msg = f"❌ Error de conexión con Zoho: {e}"
                    print(Fore.RED + msg + Style.RESET_ALL)
                    _log(msg)
                    break

                data_consulted = response.json()

                # --- Manejo de error / token ---
                if data_consulted.get("code") != 0:
                    msg = str(data_consulted.get("message", ""))
                    msg_full = f"⚠️ Error al obtener {endpoint}: {msg}"
                    print(Fore.RED + msg_full + Style.RESET_ALL)
                    _log(msg_full)

                    # Intentamos refrescar token si es tema de autorización
                    if "not authorized" in msg.lower() or "oauth" in msg.lower():
                        new_token = self.refresh_zoho_token()
                        if not new_token:
                            msg2 = "❌ No se pudo refrescar el token de Zoho."
                            print(Fore.RED + msg2 + Style.RESET_ALL)
                            _log(msg2)
                            break

                        # Reintentamos una sola vez con el nuevo token
                        headers["Authorization"] = f"Zoho-oauthtoken {new_token}"
                        try:
                            response = requests.get(url, headers=headers, params=params, timeout=30)
                            data_consulted = response.json()
                        except requests.RequestException as e:
                            msg3 = f"❌ Error de conexión tras refrescar token: {e}"
                            print(Fore.RED + msg3 + Style.RESET_ALL)
                            _log(msg3)
                            break

                        if data_consulted.get("code") != 0:
                            msg4 = f"❌ Error al obtener {endpoint} incluso tras refrescar token: {data_consulted.get('message')}"
                            print(Fore.RED + msg4 + Style.RESET_ALL)
                            _log(msg4)
                            break  # salimos del while
                    else:
                        # Error no relacionado con token
                        break

                # --- Si todo salió bien, procesamos la página ---
                records = data_consulted.get(list_key, [])
                if not records:
                    msg = f"⚠️ No se encontraron registros en {endpoint} (página {page})."
                    print(Fore.YELLOW + msg + Style.RESET_ALL)
                    _log(msg)

                for doc in records:
                    if pk_field not in doc:
                        # Si algún registro no trae el pk esperado, lo saltamos
                        msg = f"⚠️ Registro sin '{pk_field}' en {endpoint}, se omite."
                        print(Fore.YELLOW + msg + Style.RESET_ALL)
                        _log(msg)
                        continue

                    filter_query = {pk_field: doc[pk_field]}
                    update_query = {"$set": doc}

                    result = collection.update_one(filter_query, update_query, upsert=True)
                    total_docs += 1
                    if result.upserted_id is not None:
                        inserted += 1
                    elif result.matched_count > 0:
                        updated += 1

                # Mensaje por página
                msg = f"✅ {endpoint}: página {page} procesada. Registros en esta página: {len(records)}"
                print(Fore.GREEN + msg + Style.RESET_ALL)
                _log(msg)

                # --- Paginación Zoho: revisamos page_context ---
                page_context = data_consulted.get("page_context", {})
                has_more = page_context.get("has_more_page")

                if not has_more:
                    # No hay más páginas
                    break

                page += 1

            # Resumen por endpoint
            msg = f"📊 Resumen {endpoint}: total procesados={total_docs}, insertados nuevos={inserted}, actualizados={updated}"
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


    app = ZOHO_INVENTORY(working_folder, yaml_data)
    #from library.shopify_mongo_db import SHOPIFY_MONGODB
    
    app.sync_zoho_inventory_to_mongo()    
        