from dataclasses import replace
import os
from pprint import pprint
from dotenv import load_dotenv
import sys

from library.zoho_inventory import ZOHO_INVENTORY
root_path = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, root_path)
from library.yaml_creator import YAMLCREATOR
from library.shopify_management import SHOPIFY_MANAGEMENT

class INCREMENTAL_DB:
    def __init__(self):
        self.folder_root = os.path.dirname(__file__)
        self.folder_root = os.path.join(self.folder_root, "..")
        load_dotenv()
        self.working_folder = os.getenv("MAIN_PATH")
        os.makedirs(self.working_folder, exist_ok=True)
        self.data_yaml = YAMLCREATOR(self.working_folder).data

    def incremental_menu(self):
        print("Incremental DB Menu")
        pprint(self.data_yaml)
        # Further implementation goes here
        self.feed_data_shopify()
        self.zoho_inventory = ZOHO_INVENTORY(self.working_folder, self.data_yaml)
        self.zoho_inventory.feed_data_zoho()

    def feed_data_shopify(self, extract_all=False):
        self.shopify_stores = ['managed_store_one', 'managed_store_two']

        ENDPOINTS_AVAILABLE = {
            'inventory_levels':   '/admin/api/{api_version}/inventory_levels.json',
            'locations':          '/admin/api/{api_version}/locations.json',
            'orders':             '/admin/api/{api_version}/orders.json?status=any',
            'products':           '/admin/api/{api_version}/products.json',
            'customers':          '/admin/api/{api_version}/customers.json',
        }

        EXCLUDED_ENDPOINTS = {'locations'}

        REQUESTED_ENDPOINTS = {
            ep: ENDPOINTS_AVAILABLE[ep]
            for ep in ENDPOINTS_AVAILABLE.keys()
            if ep not in EXCLUDED_ENDPOINTS
        }
        print(REQUESTED_ENDPOINTS.keys())

        for store in self.shopify_stores:
            if self.data_yaml.get(store):
                print(f"Mirroring data for store: {store}")

                store_dict = self.data_yaml[store]  # api_version, store_name, access_token, etc.

                # 👇 AQUÍ EL CAMBIO
                resolved_endpoints = {}
                for key, path in REQUESTED_ENDPOINTS.items():
                    try:
                        # usa todas las claves de store_dict, format ignora las que no necesita
                        resolved_endpoints[key] = path.format(**store_dict)
                    except KeyError as e:
                        # si falta algún placeholder, se salta ese endpoint
                        print(f"  ⚠️ Saltando endpoint '{key}': falta la clave {e} en store_dict")

                print("Resolved endpoints:")
                for k, v in resolved_endpoints.items():
                    print("  ", k, "=>", v)

                shopify_manager = SHOPIFY_MANAGEMENT(self.working_folder, self.data_yaml, store)
                shopify_manager.mirror_endpoints(resolved_endpoints, store, extract_all=extract_all)

                
                
                
                

if __name__ == "__main__":
    app = INCREMENTAL_DB()
    app.incremental_menu()