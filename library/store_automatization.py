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

    def send_workload_to_shopify_api(self, list_bodies: list, store_key: str, method: str):
        """
        list_bodies: lista de dicts con el body listo para Shopify
        store_key:   'managed_store_one' | 'managed_store_two'
        method:      'POST' (crear) o 'PUT' (actualizar/archivar)
        """

        shop_conf = self.data[store_key]  # toma config de esa tienda del YAML

        api_version = shop_conf.get("api_version", "2024-10")
        base_url = f"https://{shop_conf['store_name']}/admin/api/{api_version}"

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": shop_conf["access_token"],
        }

        for body in list_bodies:
            product = body.get("product", {})
            product_id = product.get("id")

            # Crear (POST /products.json)
            if method.upper() == "POST":
                url = f"{base_url}/products.json"
                resp = requests.post(url, headers=headers, data=json.dumps(body))

            # Actualizar/archivar (PUT /products/{id}.json)
            elif method.upper() == "PUT":
                if not product_id:
                    raise ValueError("Para method='PUT' el body debe incluir product['id']")
                url = f"{base_url}/products/{product_id}.json"
                resp = requests.put(url, headers=headers, data=json.dumps(body))
            else:
                raise ValueError("method debe ser 'POST' o 'PUT'")

            # Aquí podrías loggear status:
            print(f"[{store_key}] {method} {url} -> {resp.status_code}")

    def _build_shopify_body(
        self,
        mode: str,
        *,
        zoho_item: dict | None = None,
        shopify_product: dict | None = None,
    ) -> dict:
        """
        Construye el body para el API de Shopify.

        mode:
            - "enable": crea/actualiza un producto ACTIVO a partir de un item de Zoho.
                        Requiere: zoho_item
            - "disable": archiva un producto existente en Shopify.
                        Requiere: shopify_product
        """

        mode = mode.lower()

        if mode == "enable":
            if zoho_item is None:
                raise ValueError("Para mode='enable' debes pasar zoho_item=...")

            # Extraer variables del diccionario de Zoho
            title = zoho_item.get("item_name") or zoho_item.get("name")
            description = zoho_item.get("description") or ""
            price = zoho_item.get("rate", 0)
            sku = zoho_item.get("sku") or zoho_item.get("item_id")
            vendor = zoho_item.get("manufacturer") or "Zoho Inventory"
            product_type = zoho_item.get("product_type") or "goods"

            product_payload = {
                "title": title,
                "body_html": description,
                "vendor": vendor,
                "product_type": product_type,
                "status": "active",
                "variants": [
                    {
                        "price": str(price),
                        "sku": sku,
                        "inventory_management": "shopify",
                        "inventory_policy": "deny",
                        "taxable": True,
                    }
                ],
            }

            # 👇 Si ya existe en Shopify, incluimos el id para reactivarlo con PUT
            if shopify_product is not None and "id" in shopify_product:
                product_payload["id"] = shopify_product["id"]

            return {"product": product_payload}

        elif mode == "disable":
            if shopify_product is None:
                raise ValueError("Para mode='disable' debes pasar shopify_product=...")

            body = {
                "product": {
                    "id": shopify_product["id"],
                    "status": "archived",
                    "published_at": None,
                }
            }
            return body

        else:
            raise ValueError("mode debe ser 'enable' o 'disable'")

    def shopify_items_automatization(self, logger=None):
        """
        Sincroniza catálogo Shopify con Zoho_Inventory.items:

        - Shopify solo puede tener productos que:
          * existan en Zoho, y
          * estén marcados como 'active' en Zoho.

        Acciones por tienda (managed_store_one / managed_store_two):
        1) Crear en Shopify todo item ACTIVO en Zoho que no exista en Shopify.
        2) Dar de baja en Shopify todo producto que:
           - no exista en Zoho, o
           - exista en Zoho pero con status != 'active'.

        Regresa un dict con los payloads para llamar al API de Shopify.
        """
        
        def _log(msg: str):
            if callable(logger):
                logger(str(msg))
            else:
                print(str(msg))
        # Actualiza la información 
        from library.shopify_mongo_db import SHOPIFY_MONGODB
        shopify_management_one = SHOPIFY_MONGODB(working_folder, yaml_data, "managed_store_one")
        summary_one = shopify_management_one.sync_shopify_to_mongo()        
        shopify_management_two = SHOPIFY_MONGODB(working_folder, yaml_data, "managed_store_two")
        summary_two = shopify_management_two.sync_shopify_to_mongo()        
        # ==== Conexión a Mongo ====
        mongo_db_url = self.data["non_sql_database"]["url"]
        client = MongoClient(mongo_db_url)

        db_collections = {
            "Zoho": {
                "database": "Zoho_Inventory",
                "collection": "items",
            },
            "Shopify_store1": {
                "database": "managed_store_one",
                "collection": "products",
            },
            "Shopify_store2": {
                "database": "managed_store_two",
                "collection": "products",
            },
        }

        # Aquí guardamos los resultados de cada origen
        docs_by_source = {}

        for source_name, cfg in db_collections.items():
            db_name = cfg["database"]
            coll_name = cfg["collection"]

            db = client[db_name]
            coll = db[coll_name]

            docs = list(coll.find({}))  # trae todos los documentos
            docs_by_source[source_name] = docs

            _log(f"{source_name}: {db_name}.{coll_name} → {len(docs)} documentos")

        # Asignaciones
        zoho_items   = docs_by_source["Zoho"]
        store1_items = docs_by_source["Shopify_store1"]
        store2_items = docs_by_source["Shopify_store2"]

        # Logs de longitud
        _log(f"managed_store_one.products → {len(store1_items)} documentos")
        _log(f"managed_store_two.products → {len(store2_items)} documentos")
        _log(f"Zoho_Inventory.items → {len(zoho_items)} documentos")

        # Campos clave de comparación
        shopify_item_pk = "title"      # campo en Shopify
        zoho_item_fk = "item_name"     # campo en Zoho

        shopify_key_field = shopify_item_pk
        zoho_key_field = zoho_item_fk

        # ===================== ZOHO: ACTIVOS =====================
        zoho_active_items = [
            item for item in zoho_items
            if item.get("status") == "active"
        ]
        _log(f"Items activos en Zoho: {len(zoho_active_items)}")

        # ===================== FILTRO POR TIENDA DESDE YAML =====================
        def _filter_zoho_items_for_store(store_key: str) -> list:
            """
            Usa self.data[store_key]['items'] para filtrar zoho_active_items.

            Ejemplo YAML:
            managed_store_two:
              ...
              items:
                name: Riafol
                sku: '010.0246.000.411'
                barcode: 001231231243121

            Para cada (campo -> valor) busca coincidencias exactas en Zoho:
                item[campo] == valor

            - Si encuentra, los conserva.
            - Si no encuentra, imprime: 'Item no disponible en Zoho {field}={value}'.
            - La lógica es una unión (si name y sku apuntan al mismo item, solo queda uno).
            """
            store_cfg = self.data.get(store_key, {})
            items_cfg = store_cfg.get("items", {})

            if not items_cfg:
                _log(f"[{store_key}] Sin filtro de items en config, se usarán todos los activos de Zoho.")
                return zoho_active_items

            store_items = []

            for field, value in items_cfg.items():
                # Permitimos que value también pueda ser lista/tupla en el futuro
                if isinstance(value, (list, tuple, set)):
                    matches = [
                        item for item in zoho_active_items
                        if item.get(field) in value
                    ]
                else:
                    matches = [
                        item for item in zoho_active_items
                        if item.get(field) == value
                    ]

                if not matches:
                    _log(f"[{store_key}] Item no disponible en Zoho: {field} = {value}")
                else:
                    store_items.extend(matches)

            # Eliminar duplicados tomando el campo de FK principal (item_name)
            unique_items = []
            seen_keys = set()
            for it in store_items:
                fk_val = it.get(zoho_key_field)
                if fk_val is not None:
                    if fk_val in seen_keys:
                        continue
                    seen_keys.add(fk_val)
                unique_items.append(it)

            _log(f"\t[{store_key}] Items Zoho activos tras filtro YAML: {len(unique_items)}")
            return unique_items

        # Items de Zoho relevantes para cada tienda según el YAML
        zoho_store1_items = _filter_zoho_items_for_store("managed_store_one")
        zoho_store2_items = _filter_zoho_items_for_store("managed_store_two")

        # ===================== ÍNDICES POR PK/FK =====================
        def _build_index(docs: list, key_field: str) -> dict:
            """
            Construye un índice simple:
                valor_de_key_field -> documento
            Solo usa igualdad exacta, sin normalizar.
            """
            index = {}
            for d in docs:
                val = d.get(key_field)
                if val is not None:
                    index[val] = d
            return index

        # Índices Shopify (por title) y Zoho (por item_name)
        shopify_store1_index = _build_index(store1_items, shopify_key_field)
        shopify_store2_index = _build_index(store2_items, shopify_key_field)

        zoho_store1_index = _build_index(zoho_store1_items, zoho_key_field)
        zoho_store2_index = _build_index(zoho_store2_items, zoho_key_field)

        # Índice con TODOS los items de Zoho (activos e inactivos) para validar bajas
        zoho_all_index = _build_index(zoho_items, zoho_key_field)

        # ===================== LÓGICA DE ANÁLISIS POR TIENDA =====================
        def _analyze_store(
            store_label: str,
            shopify_index: dict,
            active_zoho_index: dict,
        ) -> dict:
            """
            Compara usando:
                Shopify[shopify_key_field] ↔ Zoho[zoho_key_field]

            Reglas:
            - HABILITAR (enable): todo item que esté activo en Zoho
              y listado en el YAML de esta tienda:
                * si NO existe en Shopify → se crea
                * si existe en Shopify y no está 'active' → se reactiva
            - DESHABILITAR (disable):
                * keys que no existen en Zoho, o
                * existen en Zoho pero status != 'active', o
                * existen en Zoho y están activos, pero YA NO están en el YAML
                  de esta tienda.
            """
            shopify_keys     = set(shopify_index.keys())
            active_zoho_keys = set(active_zoho_index.keys())   # activos + elegidos en YAML
            all_zoho_keys    = set(zoho_all_index.keys())      # todos los de Zoho

            # ========= HABILITAR (crear o reactivar) =========
            enable_bodies = []
            for key in sorted(active_zoho_keys):
                zoho_item = active_zoho_index[key]
                shopify_product = shopify_index.get(key)

                # Caso 1: no existe en Shopify → crear (enable sin id)
                if shopify_product is None:
                    body = self._build_shopify_body(
                        "enable",
                        zoho_item=zoho_item,
                        shopify_product=None,
                    )
                    enable_bodies.append(body)
                    continue

                # Caso 2: existe en Shopify pero NO está activo → reactivar
                if shopify_product.get("status") != "active":
                    body = self._build_shopify_body(
                        "enable",
                        zoho_item=zoho_item,
                        shopify_product=shopify_product,  # incluye id
                    )
                    enable_bodies.append(body)
                    continue

                # Caso 3: ya existe y está activo → no hacemos nada (idempotente)
                # (si quisieras forzar update podrías también incluirlo aquí)

            # ========= DESHABILITAR =========
            to_disable_keys = []
            for key in shopify_keys:
                if key not in all_zoho_keys:
                    # 1) No existe en Zoho
                    to_disable_keys.append(key)
                else:
                    zoho_item = zoho_all_index[key]
                    if zoho_item.get("status") != "active":
                        # 2) Existe en Zoho pero ya no está activo
                        to_disable_keys.append(key)
                    elif key not in active_zoho_keys:
                        # 3) Sigue activo en Zoho, pero YA NO está en el YAML
                        #    de esta tienda → desactivarlo en esta tienda
                        to_disable_keys.append(key)

            disable_bodies = []
            for key in to_disable_keys:
                shopify_product = shopify_index[key]
                body = self._build_shopify_body(
                    "disable",
                    shopify_product=shopify_product,
                )
                disable_bodies.append(body)

            _log(
                f"[{store_label}] Comparando por "
                f"Shopify.{shopify_key_field} ↔ Zoho.{zoho_key_field}"
            )
            _log(
                f"\t[{store_label}] Enable (crear/reactivar): {len(enable_bodies)} | "
                f"Disable (archivar): {len(disable_bodies)}"
            )

            return {
                "enable": enable_bodies,
                "disable": disable_bodies,
            }        

        # ===================== EJECUTAR PARA CADA TIENDA =====================
        managed_store_one_workload = _analyze_store(
                "managed_store_one",
                shopify_store1_index,
                zoho_store1_index,
            )
        managed_store_two_workload = _analyze_store(
                "managed_store_two",
                shopify_store2_index,
                zoho_store2_index,
            )

        # Tienda 1
        self.send_workload_to_shopify_api(
            managed_store_one_workload["enable"],
            store_key="managed_store_one",
            method="POST",
        )
        self.send_workload_to_shopify_api(
            managed_store_one_workload["disable"],
            store_key="managed_store_one",
            method="PUT",
        )

        # Tienda 2
        self.send_workload_to_shopify_api(
            managed_store_two_workload["enable"],
            store_key="managed_store_two",
            method="POST",
        )
        self.send_workload_to_shopify_api(
            managed_store_two_workload["disable"],
            store_key="managed_store_two",
            method="PUT",
        )
        

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
    app = STORE_AUTOMATIZATION(working_folder, yaml_data, store=None)
    app.shopify_items_automatization()  
    app.shopify_order_automatization()  