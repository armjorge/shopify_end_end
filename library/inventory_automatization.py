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


class INVENTORY_AUTOMATIZATION:

    def __init__(self, working_folder, yaml_data, store=None):
        init(autoreset=True)
        print(Fore.BLUE + "\tInicializando EL MÓDULO DE AUTOMATIZACIÓN DE TIENDAS"+ Style.RESET_ALL)
        self.working_folder = working_folder
        self.data = yaml_data
        self.yaml_path = os.path.join(self.working_folder, "config.yml")
        self.store = store
        self._location_id_cache: dict[str, int] = {}
        
    def _get_location_id_for_store(self, store_key: str, base_url: str, headers: dict) -> int | None:
        """
        Obtiene el location_id de Shopify para esta tienda.
        - Si ya se consultó antes, usa caché.
        - Si hay solo una location, usa esa.
        - Si hay varias, toma la primera activa o la primera de la lista.
        """
        # Cache
        if store_key in self._location_id_cache:
            return self._location_id_cache[store_key]

        url = f"{base_url}/locations.json"
        resp = requests.get(url, headers=headers)

        if not resp.ok:
            print(
                f"[Shopify] ERROR {resp.status_code} al obtener locations "
                f"para store={store_key}: {resp.text}"
            )
            return None

        data = resp.json()
        locations = data.get("locations", [])

        if not locations:
            print(f"[Shopify] No se encontraron locations para store={store_key}")
            return None

        # Si solo hay una, usamos esa
        if len(locations) == 1:
            loc = locations[0]
            loc_id = loc["id"]
            print(f"[Shopify] Usando única location_id={loc_id} ({loc.get('name')}) para store={store_key}")
        else:
            # Varios locations: intentamos tomar uno activo
            active_locs = [loc for loc in locations if loc.get("active")]
            loc = active_locs[0] if active_locs else locations[0]
            loc_id = loc["id"]
            print(
                f"[Shopify] Hay {len(locations)} locations para store={store_key}. "
                f"Usando por defecto location_id={loc_id} ({loc.get('name')})."
            )

        # Guardar en caché
        self._location_id_cache[store_key] = loc_id
        return loc_id

    def send_workload_to_shopify_api(self, list_bodies: list, store_key: str, method: str):
        """
        list_bodies: lista de dicts con el body listo para Shopify
                     Cada body puede traer un campo interno "_meta"
        store_key:   'managed_store_one' | 'managed_store_two'
        method:      'POST' (crear), 'PUT' (update producto), 'UPDATE_NUMBER' (ajustar stock)
        """

        if not list_bodies:
            print(f"[Shopify] No hay bodies para enviar ({store_key}, method={method})")
            return

        shop_conf = self.data[store_key]

        api_version = shop_conf.get("api_version", "2024-10")
        base_url = f"https://{shop_conf['store_name']}/admin/api/{api_version}"

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": shop_conf["access_token"],
        }

        method_upper = method.upper()

        for body in list_bodies:
            meta = body.pop("_meta", {})
            mode = meta.get("mode")  # 'create' | 'update' | 'disable' | 'update_number'

            # Para productos (POST / PUT) seguimos usando 'product' como antes
            product = body.get("product", {})
            product_id = product.get("id")

            # ================== CREAR PRODUCTO ==================
            if method_upper == "POST":
                url = f"{base_url}/products.json"
                resp = requests.post(url, headers=headers, json=body)

            # ================== ACTUALIZAR PRODUCTO ==================
            elif method_upper == "PUT":
                if not product_id:
                    print("[Shopify] PUT sin product_id, se omite este body.")
                    continue
                url = f"{base_url}/products/{product_id}.json"
                resp = requests.put(url, headers=headers, json=body)

            # ================== AJUSTAR INVENTARIO ==================
            elif method_upper == "UPDATE_NUMBER":
                # body viene con: inventory_item_id, available
                inventory_item_id = body.get("inventory_item_id")
                available = body.get("available")

                # 🔹 Para UPDATE_NUMBER obtenemos una sola vez el location_id de Shopify
                location_id = None
                if method_upper == "UPDATE_NUMBER":
                    location_id = self._get_location_id_for_store(store_key, base_url, headers)
                    if not location_id:
                        print(
                            f"[Shopify] No se pudo determinar location_id para store={store_key}. "
                            "Se omiten las actualizaciones de inventario."
                        )
                        return

                inv_payload = {
                    "inventory_item_id": inventory_item_id,
                    "location_id": location_id,
                    "available": available,
                }

                url = f"{base_url}/inventory_levels/set.json"
                resp = requests.post(url, headers=headers, json=inv_payload)

            else:
                raise ValueError("method debe ser 'POST', 'PUT' o 'UPDATE_NUMBER'")

            if not resp.ok:
                print(
                    f"[Shopify] ERROR {resp.status_code} para {mode or method_upper}. "
                    f"Body: {json.dumps(body)}\nRespuesta: {resp.text}"
                )
                continue

            data = resp.json()

            # Para productos seguimos intentando leer 'product'
            if method_upper in ("POST", "PUT"):
                product_resp = data.get("product") or data.get("products", [{}])[0]
                new_id = product_resp.get("id")
                print(f"[Shopify] OK {mode or method_upper} product_id={new_id}")

                if mode == "create" and new_id and "zoho_item_id" in meta:
                    zoho_item_id = meta["zoho_item_id"]
                    self._link_zoho_to_shopify(store_key, str(zoho_item_id), new_id)

            elif method_upper == "UPDATE_NUMBER":
                print(
                    f"[Shopify] OK update_number "
                    f"inventory_item_id={body.get('inventory_item_id')} "
                    f"→ available={body.get('available')}"
                )

    def _link_zoho_to_shopify(self, store_key: str, zoho_item_id: str, shopify_id: int | str):
        """
        Guarda el vínculo item_id <-> shopify_id en Zoho_Inventory.items_per_store.
        """
        mongo_db_url = self.data["non_sql_database"]["url"]
        client = MongoClient(mongo_db_url)

        db = client["Zoho_Inventory"]
        coll = db["items_per_store"]

        result = coll.update_one(
            {
                "store": store_key,
                "items.item_id": str(zoho_item_id),
            },
            {
                "$set": {
                    "items.$.shopify_id": str(shopify_id),
                }
            },
        )

        if result.matched_count == 0:
            print(
                Fore.YELLOW
                + f"[items_per_store] No se encontró item_id={zoho_item_id} para store={store_key} al vincular shopify_id={shopify_id}"
                + Style.RESET_ALL
            )
        else:
            print(
                Fore.GREEN
                + f"[items_per_store] Vinculado item_id={zoho_item_id} → shopify_id={shopify_id}"
                + Style.RESET_ALL
            )

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
            - "enable": crea/actualiza un producto reflejando el status de Zoho.
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

            # 👇 aquí reflejamos el status de Zoho:
            zoho_status = (zoho_item.get("status") or "").lower()
            desired_status = "active" if zoho_status == "active" else "draft"

            product_payload = {
                "title": title,
                "body_html": description,
                "vendor": vendor,
                "product_type": product_type,
                "status": desired_status,
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

            # Si ya existe en Shopify, incluimos el id para actualizarlo con PUT
            if shopify_product is not None and "id" in shopify_product:
                product_payload["id"] = shopify_product["id"]

            return {"product": product_payload}

        elif mode == "disable":
            if shopify_product is None:
                raise ValueError("Para mode='disable' debes pasar shopify_product=...")

            body = {
                "product": {
                    "id": shopify_product["id"],
                    "status": "archived",  # o "draft" si prefieres
                    "published_at": None,
                }
            }
            return body

        else:
            raise ValueError("mode debe ser 'enable' o 'disable'")

    def shopify_items_automatization(self, store, logger=None):
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
        3) Alinear el inventario (actual_available_stock) de Zoho → Shopify.

        Regresa un dict con los payloads para llamar al API de Shopify.
        """
        print("\nIniciando automatización de items Shopify vs Zoho...")

        def _log(msg: str):
            if callable(logger):
                logger(str(msg))
            else:
                print(str(msg))

        # ==== 0) REFRESCAR datos de Shopify en Mongo ====


        # ==== 1) Conexión a Mongo ====
        mongo_db_url = self.data["non_sql_database"]["url"]
        client = MongoClient(mongo_db_url)

        db_collections = {
            "Zoho": {
                "database": "Zoho_Inventory",
                "collection": "items",
            },
            "Shopify": {
                "database": store,
                "collection": "products",
            }
        }

        docs_by_source = {}
        for source_name, cfg in db_collections.items():
            db_name = cfg["database"]
            coll_name = cfg["collection"]

            db = client[db_name]
            coll = db[coll_name]

            docs = list(coll.find({}))  # trae todos los documentos
            docs_by_source[source_name] = docs

            _log(f"{source_name}: {db_name}.{coll_name} → {len(docs)} documentos")

        zoho_items = docs_by_source["Zoho"]
        store_items = docs_by_source["Shopify"]

        _log(f"{store}.products → {len(store_items)} documentos")
        _log(f"Zoho_Inventory.items → {len(zoho_items)} documentos")

        shopify_item_pk = "id"      # campo en Shopify
        zoho_item_fk = "item_id"    # campo en Zoho

        # ===================== ITEMS CONFIGURADOS POR TIENDA =====================
        db = client["Zoho_Inventory"]
        coll_store = db["items_per_store"]

        doc = coll_store.find_one({"store": store})
        if not doc or "items" not in doc:
            _log(f"[items_per_store] No hay items configurados para la store={store}")
            return {
                "create_bodies": [],
                "update_bodies": [],
                "deactivate_bodies": [],
                "update_number_bodies": [],
            }

        # Lista de item_id configurados
        item_ids = [
            it["item_id"]
            for it in doc.get("items", [])
            if "item_id" in it
        ]
        configured_ids = set(item_ids)

        _log(f"Item_ids configurados para {store}: {len(item_ids)}")

        # Mapping Zoho -> Shopify ya vinculado (si existe)
        zoho_to_shopify_map = {
            it["item_id"]: it.get("shopify_id")
            for it in doc.get("items", [])
            if "item_id" in it
        }

        # Índices rápidos
        zoho_index = {
            str(item.get(zoho_item_fk)): item
            for item in zoho_items
            if zoho_item_fk in item
        }

        shopify_index = {
            str(prod.get(shopify_item_pk)): prod
            for prod in store_items
            if shopify_item_pk in prod
        }

        # ===================== 1) ITEMS A CREAR EN SHOPIFY =====================
        zoho_create_items = []
        for zoho_id in configured_ids:
            shopify_id = zoho_to_shopify_map.get(zoho_id)

            # Solo nos interesan los que NO están vinculados aún
            if shopify_id:
                continue

            z_item = zoho_index.get(str(zoho_id))
            if not z_item:
                _log(f"[WARN] item_id {zoho_id} está en items_per_store pero no en Zoho_Inventory.items")
                continue

            zoho_create_items.append({
                "zoho_item_id": zoho_id,
                "zoho_doc": z_item,
            })

        _log(f"zoho_create_items → {len(zoho_create_items)} items (crear en Shopify)")

        # ===================== 2) ITEMS PARA COMPARAR ESTATUS =====================
        zoho_update_status = []
        for zoho_id, shopify_id in zoho_to_shopify_map.items():
            if zoho_id not in configured_ids:
                continue
            if not shopify_id:
                continue  # estos van en create, no aquí

            z_item = zoho_index.get(str(zoho_id))
            s_prod = shopify_index.get(str(shopify_id))

            if not z_item or not s_prod:
                _log(f"[WARN] No se encontró doc Zoho ({zoho_id}) o Shopify ({shopify_id}) en índices")
                continue

            zoho_status = z_item.get("status")
            shopify_status = s_prod.get("status")

            zoho_update_status.append({
                "zoho_item_id": zoho_id,
                "shopify_id": shopify_id,
                "zoho_status": zoho_status,
                "shopify_status": shopify_status,
            })

        _log(f"zoho_update_status → {len(zoho_update_status)} items (comparar status)")

        # ===================== 3) ITEMS SHOPIFY SIN VÍNCULO (DESACTIVAR) =====================
        linked_shopify_ids = {
            str(sid) for sid in zoho_to_shopify_map.values() if sid
        }

        deactivate_products = []
        for prod in store_items:
            pid = str(prod.get(shopify_item_pk))
            if not pid:
                continue

            # Solo nos interesa si NO está vinculado a ningún item Zoho
            if pid not in linked_shopify_ids:
                shopify_status_raw = (prod.get("status") or "").lower()

                # 🔹 Regla nueva:
                # Si el producto YA está archived (o incluso draft, si quieres),
                # no necesitamos mandar un disable extra.
                if shopify_status_raw == "archived":
                    _log(
                        f"[DISABLE][SKIP] pid={pid} ya está archived en Shopify, "
                        "no se agrega a deactivate_products."
                    )
                    continue

                # Si quisieras excluir también 'draft', descomenta:
                # if shopify_status_raw in ("archived", "draft"):
                #     ...

                deactivate_products.append({
                    "shopify_id": prod.get(shopify_item_pk),
                    "shopify_status": prod.get("status"),
                })

        _log(f"deactivate_products → {len(deactivate_products)} items (sin vínculo con Zoho y no archived)")        
        # ===================== CONSTRUIR BODIES PARA SHOPIFY =====================
        bodies_create = []
        for rec in zoho_create_items:
            zoho_item = rec["zoho_doc"]
            body = self._build_shopify_body(
                "enable",
                zoho_item=zoho_item,
                shopify_product=None,
            )
            body["_meta"] = {
                "mode": "create",
                "zoho_item_id": rec["zoho_item_id"],
            }
            bodies_create.append(body)

        bodies_update = []
        for rec in zoho_update_status:
            zoho_id = str(rec["zoho_item_id"])
            shopify_id = str(rec["shopify_id"])

            zoho_item = zoho_index.get(zoho_id)
            shopify_product = shopify_index.get(shopify_id)

            if not zoho_item or not shopify_product:
                continue

            zoho_status_raw = (zoho_item.get("status") or "").lower()
            desired_status = "active" if zoho_status_raw == "active" else "draft"

            shopify_status_raw = (shopify_product.get("status") or "").lower() or "draft"

            if shopify_status_raw == desired_status:
                continue

            body = self._build_shopify_body(
                "enable",
                zoho_item=zoho_item,
                shopify_product=shopify_product,
            )
            body["_meta"] = {
                "mode": "update",
                "zoho_item_id": rec["zoho_item_id"],
                "shopify_id": rec["shopify_id"],
                "from_status": shopify_status_raw,
                "to_status": desired_status,
            }
            bodies_update.append(body)

        _log(f"bodies_update (status distintos Zoho vs Shopify): {len(bodies_update)}")

        bodies_deactivate = []
        for rec in deactivate_products:
            shopify_id = rec["shopify_id"]
            shopify_product = {"id": shopify_id}

            body = self._build_shopify_body(
                "disable",
                shopify_product=shopify_product,
            )
            body["_meta"] = {
                "mode": "disable",
                "shopify_id": shopify_id,
            }
            bodies_deactivate.append(body)

        # ===================== 4) INVENTARIO: actual_available_stock =====================
        stock_column = "stock_on_hand"  # columna en Zoho para stock actual
        bodies_update_number = []

        for zoho_id, shopify_id in zoho_to_shopify_map.items():
            if not shopify_id:
                continue
            if zoho_id not in configured_ids:
                continue

            z_item = zoho_index.get(str(zoho_id))
            s_prod = shopify_index.get(str(shopify_id))

            if not z_item or not s_prod:
                _log(f"[WARN][INV] No se encontró doc Zoho ({zoho_id}) o Shopify ({shopify_id}) para inventario")
                continue

            if stock_column not in z_item:
                _log(f"[WARN][INV] Zoho item_id={zoho_id} SIN columna '{stock_column}'. Claves disponibles: {list(z_item.keys())}")
                continue

            # Stock en Zoho
            try:
                zoho_stock = int(z_item.get(stock_column) or 0)
            except (TypeError, ValueError):
                _log(f"[WARN][INV] Valor inválido en Zoho '{stock_column}' para item_id={zoho_id}: {z_item.get(stock_column)!r}")
                zoho_stock = 0

            variants = s_prod.get("variants") or []
            if not variants:
                _log(f"[WARN][INV] Producto Shopify {shopify_id} sin variants")
                continue

            v0 = variants[0]
            try:
                shopify_stock = int(v0.get("inventory_quantity") or 0)
            except (TypeError, ValueError):
                _log(f"[WARN][INV] Valor inválido inventory_quantity para shopify_id={shopify_id}: {v0.get('inventory_quantity')!r}")
                shopify_stock = 0

            if zoho_stock == shopify_stock:
                # Debug fino opcional:
                # _log(f"[INV][OK] item_id={zoho_id} shopify_id={shopify_id} stock ya igual: {zoho_stock}")
                continue

            inventory_item_id = v0.get("inventory_item_id")
            if not inventory_item_id:
                _log(f"[WARN][INV] Variant de Shopify {shopify_id} sin inventory_item_id, no se puede actualizar stock")
                continue

            _log(
                f"[INV][DESALINEADO] item_id={zoho_id} shopify_id={shopify_id} "
                f"Zoho={zoho_stock} vs Shopify={shopify_stock}"
            )

            body = {
                "inventory_item_id": inventory_item_id,
                "available": zoho_stock,
                "_meta": {
                    "mode": "update_number",
                    "zoho_item_id": zoho_id,
                    "shopify_id": shopify_id,
                    "from": shopify_stock,
                    "to": zoho_stock,
                },
            }
            bodies_update_number.append(body)

        _log(f"bodies_create: {len(bodies_create)}")
        _log(f"bodies_update: {len(bodies_update)}")
        _log(f"bodies_deactivate: {len(bodies_deactivate)}")
        _log(f"bodies_update_number: {len(bodies_update_number)}")

        return {
            "create_bodies": bodies_create,
            "update_bodies": bodies_update,
            "deactivate_bodies": bodies_deactivate,
            "update_number_bodies": bodies_update_number,
        }

    def run_inventory_sync(self, store: str, logger=None):
        """
        Orquesta:
        1) Construir payloads de creación/actualización/desactivación.
        2) Enviar a Shopify.
        3) Guardar vínculos Zoho <-> Shopify al crear.
        """
        result = self.shopify_items_automatization(store, logger=logger)

        create_bodies         = result.get("create_bodies", [])
        update_bodies         = result.get("update_bodies", [])
        deactivate_bodies     = result.get("deactivate_bodies", [])
        update_number_bodies  = result.get("update_number_bodies", [])

        print(Fore.CYAN + f"\n=== Enviando a Shopify (store={store}) ===" + Style.RESET_ALL)
        print(f"Crear productos:          {len(create_bodies)}")
        print(f"Actualizar status:        {len(update_bodies)}")
        print(f"Desactivar productos:     {len(deactivate_bodies)}")
        print(f"Actualizar inventario #:  {len(update_number_bodies)}")

        self.send_workload_to_shopify_api(create_bodies, store, "POST")
        self.send_workload_to_shopify_api(update_bodies, store, "PUT")
        self.send_workload_to_shopify_api(deactivate_bodies, store, "PUT")
        self.send_workload_to_shopify_api(update_number_bodies, store, "UPDATE_NUMBER")



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
        from library.inventory_automatization import INVENTORY_AUTOMATIZATION
        app = INVENTORY_AUTOMATIZATION(working_folder, yaml_data, store)
        #from library.shopify_mongo_db import SHOPIFY_MONGODB
        #shopify_management = SHOPIFY_MONGODB(self.working_folder, self.data, store)
        #shopify_management.sync_shopify_to_mongo()        
        app.run_inventory_sync(store)