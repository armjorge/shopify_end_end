import os
from colorama import Fore, init, Style
from pymongo import MongoClient
import sys
import yaml
from dotenv import load_dotenv
from pprint import pprint
from copy import deepcopy
from datetime import date
import requests
import json


class STORE_AUTOMATIZATION:
    """
    This class takes the info from zoho and shopify stored at mongo_db and create orders, update orders and manage items.
    """
    def __init__(self, working_folder, yaml_data, store=None):
        init(autoreset=True)
        print(Fore.BLUE + "\tInicializando EL MÓDULO DE AUTOMATIZACIÓN DE TIENDAS"+ Style.RESET_ALL)
        self.working_folder = working_folder
        self.data = yaml_data
        self.yaml_path = os.path.join(self.working_folder, "config.yml")
        self.store = store
    
    def shopify_order_automatization(self, logger=None):
        def _log(msg: str):
            # Solo usamos logger si es una función/callable
            if callable(logger):
                logger(str(msg))
            else:
                print(str(msg))
        ####                                                             ###
        #### 1. Extraemos cada documento por colección de zoho y shopify ###
        ####                                                             ###
        # Conexión a Mongo
        mongo_db_url = self.data["non_sql_database"]["url"]
        client = MongoClient(mongo_db_url)

        databases = {
            "Zoho": ["Zoho_Inventory"],
            "Shopify": ["managed_store_one", "managed_store_two"],
        }
        collections = {
            "Zoho": ["salesorders"],
            "Shopify": ["orders"],
        }

        # Solicitamos los documentos de cada colección 
        # Listas donde guardaremos los documentos (list[dict])
        store1_orders = []
        store2_orders = []
        zoho_salesorders = []

        # Recorremos los sistemas (Zoho / Shopify) y sus bases
        for system, db_list in databases.items():
            for db_name in db_list:
                db = client[db_name]
                for coll_name in collections[system]:
                    coll = db[coll_name]
                    docs = list(coll.find({}))  # trae todos los documentos

                    # Ruteamos según base y colección
                    if system == "Zoho" and db_name == "Zoho_Inventory" and coll_name == "salesorders":
                        zoho_salesorders = docs
                    elif system == "Shopify" and coll_name == "orders":
                        if db_name == "managed_store_one":
                            store1_orders = docs
                        elif db_name == "managed_store_two":
                            store2_orders = docs

        # Logs de longitud
        _log(f"managed_store_one.orders → {len(store1_orders)} documentos")
        _log(f"managed_store_two.orders → {len(store2_orders)} documentos")
        _log(f"Zoho_Inventory.salesorders → {len(zoho_salesorders)} documentos")     


        # ==== 2. Comparar Primary Key de shopify (id) vs foreign key zoho (reference_number) ====
        # reference_number es string, Shopify id suele ser int → los llevamos ambos a str
        zoho_keys = {
            str(doc.get("reference_number"))
            for doc in zoho_salesorders
            if doc.get("reference_number") is not None
        }
        _log(f"Claves únicas en Zoho (reference_number) → {len(zoho_keys)}")

        # Helper interno que regresa órdenes a crear y órdenes a actualizar
        def comparar_store_con_zoho(store_orders, store_name: str):
            if not zoho_salesorders or not store_orders:
                _log(
                    f"\t{store_name}: no hay suficientes datos para comparar "
                    f"\t(zoho={len(zoho_salesorders)}, store={len(store_orders)})"
                )
                return [], []

            # Right set: ids de Shopify
            shopify_ids = {
                str(o.get("id"))
                for o in store_orders
                if o.get("id") is not None
            }
            _log(f"\t{store_name}: claves únicas en Shopify (id) → {len(shopify_ids)}")

            # Right join / inner join:
            # - orders_to_create: están en Shopify pero NO en Zoho (id ∉ zoho_keys)
            # - orders_to_update: están en ambos (id ∈ zoho_keys)

            orders_to_create = [
                o for o in store_orders
                if str(o.get("id")) not in zoho_keys
            ]
            orders_to_update = [
                o for o in store_orders
                if str(o.get("id")) in zoho_keys
            ]

            _log(f"\t{store_name}: órdenes para CREAR en Zoho (no presentes en salesorders) → {len(orders_to_create)}")
            _log(f"\t{store_name}: órdenes para ACTUALIZAR en Zoho (ya presentes en salesorders) → {len(orders_to_update)}")
            
            return orders_to_create, orders_to_update

        # ==== 3. Primera iteración: Zoho vs managed_store_one ====
        orders_to_create_store1, orders_to_update_store1 = comparar_store_con_zoho(
            store1_orders, "managed_store_one"
        )

        # ==== 4. Segunda iteración: Zoho vs managed_store_two ====
        orders_to_create_store2, orders_to_update_store2 = comparar_store_con_zoho(
            store2_orders, "managed_store_two"
        )
        # ==== 5. crear nuevas órdenes ====
        _log("\nCreando plantillas con nuevas órdenes para Zoho...")
        new_orders = []  # lista plana con plantillas ya “resueltas” para Zoho

        if orders_to_create_store1:
            new_orders.extend(
                self.create_new_order_template(
                    dict_with_orders=orders_to_create_store1,
                    template_name="new_order",
                )
            )

        if orders_to_create_store2:
            new_orders.extend(
                self.create_new_order_template(
                    dict_with_orders=orders_to_create_store2,
                    template_name="new_order",
                )
            )

        _log(f"Total de plantillas generadas para Zoho: {len(new_orders)}")

    def get_template(self, template_name: str) -> dict:
        """
        Devuelve una copia de un template base para payloads de Zoho.
        Por ahora sólo 'new_order'.
        Usa placeholders tipo:
          {"__from__": "campo.subcampo"}
          {"__today__": "iso"}
        """
        today_str = date.today().isoformat()

        templates = {
            "new_order": {
                # Campos mínimos (Zoho espera al menos customer_id + line_items)
                "customer_id": None,           # se resolverá después (Zoho contact_id)
                "reference_number": {"__from__": "id"},  # Shopify order.id
                "date": {"__today__": "iso"},  # por ahora usamos hoy

                # Campo opcional pero útil:
                "notes": {"__from__": "name"},  # "#1002" en tu ejemplo

                # IMPORTANTE: en vez de line_items directo, definimos una PLANTILLA de líneas
                # que luego se aplica a cada line_item de Shopify:
                "line_items": {
                    "item_id": None,          # se resolverá con SKU -> Zoho item_id
                    "name": {"__from__": "title"},
                    "description": {"__from__": "title"},
                    "rate": {"__from__": "price"},
                    "quantity": {"__from__": "quantity"},
                    "unit": "Piezas",        # o "qty", como lo tengas en Zoho
                    # dejamos impuestos y demás en None por ahora
                    "tax_id": None,
                    "tax_name": None,
                    "tax_percentage": None,
                },
            }
        }

        if template_name not in templates:
            raise ValueError(f"Template '{template_name}' no definido.")

        # deepcopy para no compartir referencias entre órdenes
        return deepcopy(templates[template_name])

    def _get_by_path(self, data: dict, path: str):
        """
        Lee algo tipo 'customer.default_address.country' desde data.
        Si en algún punto falta, regresa None.
        """
        current = data
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None
        return current

    def resolve_placeholders(self, template_fragment, main_dict: dict):
        """
        Recorre recursivamente un fragmento del template y:
        - si ve {"__from__": "path"} → lo reemplaza por main_dict[path]
        - si ve {"__today__": "iso"} → lo reemplaza por date.today().isoformat()
        - si ve listas/dicts normales → baja recursivamente
        """
        # Placeholder especial: viene como dict con una clave reservada
        if isinstance(template_fragment, dict):
            if "__from__" in template_fragment:
                path = template_fragment["__from__"]
                return self._get_by_path(main_dict, path)
            if "__today__" in template_fragment:
                # por ahora sólo soportamos formato ISO
                return date.today().isoformat()

            # Si no es placeholder especial, resolvemos cada campo
            return {
                k: self.resolve_placeholders(v, main_dict)
                for k, v in template_fragment.items()
            }

        # Si es lista, resolvemos elemento por elemento
        if isinstance(template_fragment, list):
            return [
                self.resolve_placeholders(v, main_dict)
                for v in template_fragment
            ]

        # Si es valor simple, lo devolvemos tal cual
        return template_fragment

    def create_new_order_template(self, dict_with_orders: list[dict], template_name: str, logger = None) -> list[dict]:
        """
        dict_with_orders: lista de órdenes Shopify.
        template_name: nombre del template en el repositorio ('new_order').
        Devuelve una lista de payloads listos para Zoho (sin haber resuelto aún customer_id/item_id).
        """
        def _log(msg: str):
            # Solo usamos logger si es una función/callable
            if callable(logger):
                logger(str(msg))
            else:
                print(str(msg))        
        if not dict_with_orders:
            _log("\tNo hay órdenes para generar plantillas.")
            return []

        push_list: list[dict] = []

        # Template base a nivel cabecera
        base_template = self.get_template(template_name)
        #print("\nBase template:")
        #pprint(base_template)
        # asignamos el template de base_template a line_item_template y al mismo tiempo lo removemos del diccionario.

        line_item_template = base_template.pop("line_items")

        for order_dict in dict_with_orders:
            # 1) Cabecera: resolvemos placeholders contra order_dict (Shopify order)
            header = self.resolve_placeholders(base_template, order_dict)

            # 2) Construimos las líneas:
            line_items = []
            # Para cada item en order_dict["line_items"]
            for line_item in order_dict.get("line_items", []):
                # Aplicamos el template de línea usando CADA line_item de Shopify como main_dict
                line_body = self.resolve_placeholders(line_item_template, line_item)
                line_items.append(line_body)

            # 3) Armamos el body final de la sales order Zoho
            body = header
            body["line_items"] = line_items

            # 4) Por ahora sólo imprimimos la plantilla
            _log("\nPlantilla generada para orden Shopify "
                      f"{order_dict.get('name') or order_dict.get('id')}:")
            pprint(body)

            push_list.append(body)
        #pprint(push_list)
        return push_list

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
        from library.store_automatization import STORE_AUTOMATIZATION
        app = STORE_AUTOMATIZATION(working_folder, yaml_data, store) 
        app.shopify_order_automatization()
    
      