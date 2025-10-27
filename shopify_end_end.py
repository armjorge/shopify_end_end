import os
from dotenv import load_dotenv
from colorama import Fore, Style, init
from Library.yaml_creator import YAMLCREATOR
from Library.zoho_inventory import ZOHO_INVENTORY
from pprint import pprint
from Library.shopify_management import SHOPIFY_MANAGEMENT

class SHOPIFY:
    # Orchstrate the main flow
    def run(self):
        init(autoreset=True)
        print(f"{Fore.RED}Shopify-Zoho Integration{Style.RESET_ALL}")
        
        # 1️⃣ Obtener productos activos en Zoho
        active_items = self.zoho_inventory.get_zoho_items()
        main_shopify_items = {"name": "Riafol"}
        main_store_items = [
            item for item in active_items
            if all(item.get(k) == v for k, v in main_shopify_items.items())
        ]
        print("\nProductos ZOHO finales\n")
        pprint(main_store_items)

        # 2️⃣ Inicializar gestor de Shopify
        store = "main_shopify"
        self.shopify_management = SHOPIFY_MANAGEMENT(self.working_folder, self.data_yaml, store)

        # 3️⃣ Obtener productos existentes en Shopify (1 sola llamada)
        shopify_products = self.shopify_management.get_shopify_products()
        pprint(shopify_products)
        shopify_dict = {}
        for p in shopify_products:
            if p.get("variants"):
                sku = p["variants"][0].get("sku")
                if sku:
                    shopify_dict[sku] = p

        # 4️⃣ Loop optimizado
        to_create, to_update, to_deactivate = [], [], []

        for item in main_store_items:
            sku = item["sku"] or item["item_id"]
            zoho_qty = int(item["available_stock"])
            zoho_status = item["status"]

            # Producto no existe en Shopify
            if sku not in shopify_dict:
                to_create.append(item)
                continue

            # Producto sí existe: comparar inventario
            variant = shopify_dict[sku]["variants"][0]
            shopify_qty = variant.get("inventory_quantity", 0)
            inventory_item_id = variant.get("inventory_item_id")

            if shopify_qty != zoho_qty:
                to_update.append({
                    "sku": sku,
                    "product_id": shopify_dict[sku]["id"],
                    "inventory_item_id": inventory_item_id,
                    "qty": zoho_qty
                })
            # Producto inactivo en Zoho
            if zoho_status != "active":
                to_deactivate.append(shopify_dict[sku])

        # 🔹 Combina los productos inactivos y los faltantes en Zoho
        total_to_deactivate = len(to_deactivate)

        # detecta los faltantes en Zoho antes de imprimir
        active_zoho_skus = set(item.get("sku") or item.get("item_id") for item in main_store_items)
        missing_in_zoho = [p for sku, p in shopify_dict.items() if sku not in active_zoho_skus]
        total_to_deactivate += len(missing_in_zoho)

        print(Fore.CYAN + f"Crear: {len(to_create)} | Actualizar: {len(to_update)} | Desactivar: {total_to_deactivate}")
        
        # 5️⃣ Ejecutar acciones necesarias
        if to_create:
            self.shopify_management.create_items(to_create, shopify_products)
        if to_update:
            for u in to_update:
                self.shopify_management.update_inventory_level(
                    u["inventory_item_id"],
                    u["sku"],  # corregido: antes usaba item_name
                    u["qty"]
                )
        # Deactivate Shopify products not present in Zoho
        # Build set of active Zoho SKUs
        active_zoho_skus = set(item.get("sku") or item.get("item_id") for item in main_store_items)
        missing_in_zoho = []
        for sku, prod in shopify_dict.items():
            if sku not in active_zoho_skus:
                missing_in_zoho.append(prod)
        if missing_in_zoho:
            for d in missing_in_zoho:
                self.shopify_management.deactivate_product(d["id"], d["title"])

        print(Fore.GREEN + "✅ Sincronización completa.")

    # Initialize the main components
    def __init__(self):
        self.folder_root = self.get_root_path()
        self.working_folder = os.path.join(self.folder_root, "Shopify_files")  
        os.makedirs(self.working_folder, exist_ok=True)
        self.data_yaml = YAMLCREATOR(self.working_folder).data
        # Initialize Sprint 1.1: Get product list
        self.zoho_inventory = ZOHO_INVENTORY(self.working_folder, self.data_yaml)
        

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
    app = SHOPIFY()
    app.run()