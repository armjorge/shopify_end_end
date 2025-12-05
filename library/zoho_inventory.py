from colorama import Fore, init, Style
import requests
import os
from pymongo import MongoClient
from colorama import Fore, Style
import requests


class ZOHO_INVENTORY:
    def __init__(self, working_folder, yaml_data, store=None):
        init(autoreset=True)
        print(Fore.BLUE + "\tInicializando ZOHO_INVENTORY"+ Style.RESET_ALL)
        self.working_folder = working_folder
        self.data = yaml_data
        self.yaml_path = os.path.join(self.working_folder, "config.yml")
        self.store = store

    def sync_zoho_inventory_to_mongo(self, logger=None):
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

        crm_target = "Zoho Inventory"      # Nombre "humano"
        db_name = crm_target.replace(" ", "_")  # Mongo no acepta espacios en el nombre de la DB

        zoho_conf = self.data["zoho"]
        mongo_db_url = self.data["non_sql_database"]["url"]

        # endpoint -> (primary_key, list_key_en_respuesta)
        endpoints_zoho = {
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
