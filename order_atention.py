import os
from dotenv import load_dotenv
from colorama import Fore, Style, init
from library.yaml_creator import YAMLCREATOR
from library.shopify_management import SHOPIFY_MANAGEMENT
from pprint import pprint
from library.zoho_inventory import ZOHO_INVENTORY
import pandas as pd
from library.helpers import HELPERS

class ORDER_ATTENTION:
    # Orchstrate the main flow
    def order_attention_menu(self):
        init(autoreset=True)
        print(f"{Fore.BLUE}\tINICIALIZANDO ATENCIÓN DE ÓRDENES{Style.RESET_ALL}")
        # Initialize Sprint 1.1: Get product list
        self.shopify_orders = print("\tÓrdenes de compra (clientes) obtenidas de Shopify")

        self.zoho_orders = print("\tÓrdenes de venta registradas en zoho")
        # Seleccionar tienda
        store = "managed_store_one"


        # Inicializar gestor de Zoho
        self.zoho_inventory = ZOHO_INVENTORY(self.working_folder, self.data_yaml, store)
        # 2️⃣ Inicializar gestor de Shopify
        self.shopify_management = SHOPIFY_MANAGEMENT(self.working_folder, self.data_yaml, store)
        
        self.shopify_orders = self.shopify_management.get_shopify_orders()
        print("\nÓrdenes de compra obtenidas de Shopify\n")


        orders_shopify = "orders_shopify"
        excel_path = os.path.join(self.working_folder, f"{orders_shopify}_{store}.xlsx")
        self.helpers.dict_to_excel(self.shopify_orders, excel_path) 

        
        Zoho_headers = ['Order Date', 'Shipping Date', 'SalesOrder Number', 'Status', 'Customer Name', 'PurchaseOrder', 'Template Name', 'Currency Code', 'Exchange Rate', 'Discount Type', 'Is Discount BeforeTax', 'Entity Discount Percent', 'Item Name', 'SKU', 'Item Desc', 'Quantity', 'Usage unit', 'Item Price', 'Is Inclusive Tax', 'Discount', 'Discount Amount', 'Item Tax', 'Item Tax %', 'Item Tax Type', 'Shipping Charge', 'Adjustment', 'Adjustment Description', 'Sales Person', 'Notes', 'Terms & Conditions', 'Delivery Method', 'Custom Field Value1', 'Custom Field Value2', 'Custom Field Value3', 'Custom Field Value4', 'Custom Field Value5', 'Custom Field Value6', 'Custom Field Value7', 'Custom Field Value8', 'Custom Field Value9', 'Custom Field Value10', 'Warehouse Name']
        self.zoho_orders = self.zoho_inventory.get_zoho_orders()
        orders_zoho = "orders_zoho"
        excel_path = os.path.join(self.working_folder, f"{orders_zoho}_{store}.xlsx")
        self.helpers.dict_to_excel(self.zoho_orders, excel_path)
        # 1️⃣ Normalizar los IDs de Shopify (forzar a str y eliminar notación científica)
        id_orders_channel = [
            str(int(float(d['id']))) if d.get('id') is not None else None
            for d in self.shopify_orders
        ]

        # 2️⃣ Filtrar Zoho por coincidencia exacta del reference_number
        channel_orders = [
            d for d in self.zoho_orders
            if str(d.get('reference_number')).strip() in id_orders_channel
        ]

        # Guardar filtrado a excel
        final_channel_orders = "channel_orders_shopify"
        excel_path = os.path.join(self.working_folder, f"{final_channel_orders}_{store}.xlsx")
        self.helpers.dict_to_excel(channel_orders, excel_path)

        print("\nÓrdenes de venta obtenidas de Zoho\n")
        #pprint(self.zoho_orders)

    # Initialize the main components
    def __init__(self):
        self.folder_root = self.get_root_path()
        self.working_folder = os.path.join(self.folder_root, "Shopify_files")  
        os.makedirs(self.working_folder, exist_ok=True)
        self.data_yaml = YAMLCREATOR(self.working_folder).data
        self.helpers = HELPERS()

        

    def get_root_path(self):
        # Get the directory where main.py lives (repo folder)
        repo_path = os.path.dirname(os.path.abspath(__file__))
        repo_name = os.path.basename(repo_path)
        print(f"Current script path: {os.path.abspath(__file__)}")
        env_file = ".env"
        # Load .env if it exists
        full_repo_path = None
        if os.path.exists(env_file):
            load_dotenv(env_file)
            full_repo_path = os.getenv("MAIN_PATH") or os.getenv("Main_path")
            if not full_repo_path:
                with open(env_file, "r") as env_handle:
                    for line in env_handle:
                        stripped = line.strip()
                        if not stripped or stripped.startswith("#"):
                            continue
                        if stripped.lower().startswith("main_path"):
                            if ":" in stripped:
                                _, value = stripped.split(":", 1)
                            elif "=" in stripped:
                                _, value = stripped.split("=", 1)
                            else:
                                value = ""
                            full_repo_path = value.strip()
                            break
        if not full_repo_path:
            path_user = input("Please paste the path where the repo files will be created or enter to use the root: ")
            if path_user.strip():
                if os.path.exists(path_user):
                    full_repo_path = os.path.join(path_user, repo_name)
                else:
                    print("Path does not exist, using root")
                    full_repo_path = os.path.join(repo_path, repo_name)
            else:
                full_repo_path = os.path.join(repo_path, repo_name)
            os.makedirs(full_repo_path, exist_ok=True)
            # Write to .env
            with open(env_file, "a+") as f:
                f.seek(0)
                content = f.read()
                if "MAIN_PATH=" not in content:
                    f.write(f"MAIN_PATH={full_repo_path}\n")
            # Check if full_repo_path is inside repo_path
            if full_repo_path.startswith(repo_path + os.sep):
                gitignore_path = ".gitignore"
                with open(gitignore_path, "r") as f:
                    content = f.read()
                if f"{repo_name}/" not in content:
                    with open(gitignore_path, "a") as f:
                        f.write(f"{repo_name}/\n")
        return full_repo_path


if __name__ == "__main__":
    app = ORDER_ATTENTION()
    app.order_attention_menu()