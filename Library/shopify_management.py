import os
from colorama import Fore, Style
import requests
import json
import time
from pprint import pprint
from datetime import datetime

class SHOPIFY_MANAGEMENT:
    def __init__(self, working_folder, yaml_data, store):
        print(Fore.BLUE + "Initializing SHOPIFY_MANAGEMENT")
        self.working_folder = working_folder
        self.data = yaml_data
        self.shopify_conf = yaml_data[store]
        self.base_url = f"https://{self.shopify_conf['store_name']}"
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.shopify_conf["access_token"]
        }
        self.log_file = os.path.join(self.working_folder, "shopify_sync_log.json")

    def _log_operation(self, action_type, sku, status_code, response_time):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action_type,
            "sku": sku,
            "status_code": status_code,
            "response_time": response_time
        }
        with open(self.log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

    # =====================================================
    # 1️⃣ Obtener productos existentes de Shopify
    # =====================================================
    def get_shopify_products(self, limit=250, verbose=True):
        """
        Obtiene todos los productos de Shopify con paginación automática.
        Optimizado con timeout y control de rate limit.
        """
        if verbose:
            print(Fore.YELLOW + "Fetching all products from Shopify...")

        endpoint = f"{self.base_url}{self.shopify_conf['endpoints']['products']}"
        params = {"limit": limit}
        products = []
        total_requests = 0
        start_time = time.time()

        while endpoint:
            total_requests += 1
            try:
                response = requests.get(endpoint, headers=self.headers, params=params, timeout=(5, 15))
            except requests.Timeout:
                print(Fore.RED + "⚠️ Timeout en la petición a Shopify.")
                break

            if response.status_code != 200:
                print(Fore.RED + f"⚠️ Error fetching products: {response.status_code}")
                print(response.text)
                break

            data = response.json()
            products.extend(data.get("products", []))

            # Manejo de rate limit: pausar si Shopify se acerca al límite
            if "X-Shopify-Shop-Api-Call-Limit" in response.headers:
                used, limit_calls = map(int, response.headers["X-Shopify-Shop-Api-Call-Limit"].split("/"))
                if used > limit_calls * 0.8:
                    if verbose:
                        print(Fore.YELLOW + f"⚠️ Rate limit {used}/{limit_calls}, esperando 2s...")
                    time.sleep(2)

            # Paginación
            next_link = None
            if "Link" in response.headers:
                for link in response.headers["Link"].split(","):
                    if 'rel="next"' in link:
                        next_link = link.split(";")[0].strip("<> ")
                        break
            endpoint = next_link

            # Espera mínima (solo si hay próxima página)
            if endpoint:
                time.sleep(0.1)

        elapsed = time.time() - start_time
        print(Fore.GREEN + f"🛍️ {len(products)} productos obtenidos en {total_requests} llamadas ({elapsed:.2f}s)")

        # Snapshot rápido (sin sangría para reducir I/O)
        snapshot_path = os.path.join(self.working_folder, "shopify_products_raw.json")
        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False)
        if verbose:
            print(Fore.CYAN + f"📦 Snapshot guardado en {snapshot_path}")

        return products

    # =====================================================
    # 2️⃣ Crear nuevos productos si no existen (estandarizado)
    # =====================================================
    def create_items(self, active_items, existing_products=None):
        print(Fore.CYAN + "Creating standardized items in Shopify...")
        if existing_products is None:
            existing_products = self.get_shopify_products()

        existing_skus = {
            p["variants"][0].get("sku")
            for p in existing_products if p.get("variants")
        }

        for item in active_items:
            sku = item.get("sku") or item.get("item_id")
            if sku not in existing_skus:
                # 🔹 Mapping Zoho → Shopify
                product_data = {
                    "product": {
                        "title": item.get("name", ""),
                        "body_html": f"<p>{item.get('description', item.get('name', ''))}</p>",
                        "vendor": item.get("manufacturer") or item.get("brand") or "Sin fabricante",
                        "product_type": item.get("product_type", "goods"),
                        "tags": ", ".join(item.get("tags", [])) if isinstance(item.get("tags"), list) else item.get("tags", ""),
                        "status": "active" if item.get("status") == "active" else "draft",
                        "variants": [{
                            "sku": sku,
                            "price": str(item.get("rate", 0)),
                            "inventory_quantity": int(item.get("available_stock", 0)),
                            "inventory_management": "shopify" if item.get("track_inventory", True) else None,
                            "weight": float(item.get("weight", 0) or 0),
                            "weight_unit": item.get("weight_unit", "kg")
                        }]
                    }
                }

                # 🔹 Crear producto
                endpoint = f"{self.base_url}{self.shopify_conf['endpoints']['products']}"
                print(Fore.CYAN + f"🧩 Creando producto SKU: {sku}")
                start_time = time.time()
                response = requests.post(endpoint, headers=self.headers, data=json.dumps(product_data))
                response_time = time.time() - start_time

                self._log_operation("create", sku, response.status_code, response_time)
                print(Fore.CYAN + f"⏱ Tiempo: {response_time:.2f}s")

                if response.status_code == 201:
                    print(Fore.GREEN + f"✅ Producto creado correctamente: {item.get('name', '')}")
                else:
                    print(Fore.RED + f"⚠️ Error al crear {item.get('name', '')}: {response.status_code}")
                    print(response.text)

    # =====================================================
    # 3️⃣ Actualizar inventario disponible (Zoho → Shopify)
    # =====================================================
    def update_inventory_level(self, inventory_item_id, sku, new_qty):
        """
        Actualiza el inventario disponible (Available) en Shopify
        basado en el campo available_stock de Zoho.
        """
        print(Fore.CYAN + f"🔄 Updating inventory for SKU: {sku}")

        # Cache del location_id
        if not hasattr(self, "_location_id_cache"):
            locations_endpoint = f"{self.base_url}/admin/api/2024-10/locations.json"
            response = requests.get(locations_endpoint, headers=self.headers)
            if response.status_code != 200:
                print(Fore.RED + f"⚠️ Error obteniendo location_id: {response.status_code}")
                print(response.text)
                return
            locations = response.json().get("locations", [])
            if not locations:
                print(Fore.RED + "⚠️ No se encontraron ubicaciones en Shopify.")
                return
            self._location_id_cache = locations[0]["id"]
            print(Fore.YELLOW + f"📍 Using location_id: {self._location_id_cache}")

        # Actualizar nivel de inventario
        endpoint = f"{self.base_url}/admin/api/2024-10/inventory_levels/set.json"
        payload = {
            "inventory_item_id": inventory_item_id,
            "location_id": self._location_id_cache,
            "available": new_qty
        }

        start_time = time.time()
        response = requests.post(endpoint, headers=self.headers, data=json.dumps(payload))
        response_time = time.time() - start_time

        self._log_operation("update_inventory", sku, response.status_code, response_time)
        print(Fore.CYAN + f"⏱ Tiempo: {response_time:.2f}s")

        if response.status_code in [200, 201]:
            print(Fore.GREEN + f"✅ Inventario actualizado: SKU {sku} → {new_qty}")
        else:
            print(Fore.RED + f"⚠️ Error al actualizar inventario de {sku}: {response.status_code}")
            print(response.text)

    # =====================================================
    # 4️⃣ Desactivar productos en Shopify (Zoho → Shopify)
    # =====================================================
    def deactivate_product(self, product_id, product_title):
        """
        Desactiva un producto en Shopify.
        """
        print(Fore.CYAN + f"🔄 Desactivando producto: {product_title}")

        endpoint = f"{self.base_url}/admin/api/2024-10/products/{product_id}.json"
        payload = {
            "product": {
                "id": product_id,
                "status": "draft"
            }
        }
        start_time = time.time()
        response = requests.put(endpoint, headers=self.headers, data=json.dumps(payload))
        response_time = time.time() - start_time

        if response.status_code == 200:
            print(Fore.GREEN + f"✅ Producto desactivado correctamente: {product_title}")
        else:
            print(Fore.RED + f"⚠️ Error al desactivar {product_title}: {response.status_code}")
            print(response.text)