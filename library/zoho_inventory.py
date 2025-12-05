from colorama import Fore, init, Style
import requests
import json
import yaml
import os
from pprint import pprint
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
    def feed_data_zoho(self):
        print("Zoho a mongo DB")


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
    def get_zoho_orders(self, page=1, per_page=200):
        """
        Obtiene órdenes de venta desde Zoho Inventory y devuelve una lista de dicts limpios.
        """ 
        print(f"{Fore.BLUE}Obteniendo órdenes de zoho desde el canal {self.store}{Style.RESET_ALL}")
                        
        zoho_conf = self.data['zoho']
        url = f"{zoho_conf['api_domain']}/inventory/v1/salesorders"
        
        params = {
            "organization_id": zoho_conf['organization_id'],
            "page": page,
            "per_page": per_page
        }
        
        headers = {
            "Authorization": f"Zoho-oauthtoken {zoho_conf['access_token']}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers, params=params)
        data_consulted = response.json()

        # Validamos la respuesta
        if data_consulted.get("code") != 0:
            print(Fore.RED + f"⚠️ Error al obtener órdenes de Zoho: {data_consulted.get('message')}")

            # Intentamos refrescar token si el error indica falta de autorización
            if "not authorized" in str(data_consulted.get("message", "")).lower():
                new_token = self.refresh_zoho_token()
                if new_token:
                    headers["Authorization"] = f"Zoho-oauthtoken {new_token}"
                    response = requests.get(url, headers=headers, params=params)
                    data_consulted = response.json()
                    if data_consulted.get("code") == 0:
                        print(Fore.GREEN + "✅ Token actualizado y órdenes obtenidas correctamente.")
                        return data_consulted.get("salesorders", [])
                    else:
                        print(Fore.RED + f"❌ Error tras refrescar token: {data_consulted.get('message')}")
                        return []
                else:
                    return []
            return []

        # Si todo salió bien
        print(Fore.GREEN + f"✅ Órdenes obtenidas correctamente ({len(data_consulted.get('salesorders', []))} registros)")

        orders = data_consulted.get("salesorders", [])
        # Órdenes en zoho
        #pprint(orders)
        unique_orders = {o.get("salesorder_id"): o for o in orders}.values()
        print(f"🔄 Órdenes únicas obtenidas: {len(unique_orders)}")

        # Limpiamos los campos más importantes para comparación con Shopify
        data_cleaned = [{
            "salesorder_id": o.get("salesorder_id"),
            "salesorder_number": o.get("salesorder_number"),
            "date": o.get("date"),
            "customer_name": o.get("customer_name"),
            "status": o.get("status"),
            "total": o.get("total"),
            "currency_code": o.get("currency_code"),
            "line_items": [{
                "item_id": i.get("item_id"),
                "name": i.get("name"),
                "sku": i.get("sku"),
                "quantity": i.get("quantity"),
                "rate": i.get("rate"),
                "total": i.get("total")
            } for i in o.get("line_items", [])]
        } for o in unique_orders]

        print(f"✅ {len(data_cleaned)} órdenes de venta limpias obtenidas de Zoho (página {page})")
        return orders

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