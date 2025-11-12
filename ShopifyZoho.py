
import os
from dotenv import load_dotenv
from colorama import Fore, Style, init
from Library.yaml_creator import YAMLCREATOR
import yaml 

class SHOPIFY_ZOHO_ORCHESTRATOR:
    # Orchstrate the main flow
    def menu(self):
        init(autoreset=True)
        print(f"{Fore.BLUE}Orchestador de Shopify - Zoho{Style.RESET_ALL}")
        print(""" 
                Elige una opción: 
                    1️⃣ Alta, baja y actualización de inventario Zoho -> Shopify
                    2️⃣ Atención de órdenes de Shopify -> Zoho
                    3️⃣ Actualizar información a apex Oracle
                    4️⃣ Correr en apache airflow.
                    Continúa en APEX para completar las ventas de ZOHO. 
                    https://oracleapex.com/ords/r/apex/
                      """ )
        user_choice = input("Ingresa el número de la opción deseada: ")
        
        if user_choice == "1":
            from Inventory_Sync import SHOPIFY
            shopify_zoho = SHOPIFY()
            shopify_zoho.run()
        elif user_choice == "2":
            from order_atention import ORDER_ATTENTION
            order_sync = ORDER_ATTENTION()
            order_sync.order_attention_menu()
        elif user_choice == "3":
            from apex_sync import APEX_SYNC
            apex_sync = APEX_SYNC()
            apex_sync.apex_sync_menu()
        else:
            print("Opción no válida. Saliendo.")
        
    def __init__(self):
        self.folder_root = self.get_root_path()
        print(f"Root path set to: {self.folder_root}")
        self.working_folder = os.path.join(self.folder_root, "Shopify_files")  
        os.makedirs(self.working_folder, exist_ok=True)
        self.data_yaml = YAMLCREATOR(self.working_folder).data
        try:
            root_path = os.path.join(os.path.dirname(__file__))
            open_config_path = os.path.join(root_path, "config", "open_config.yml")
            with open(open_config_path, 'r') as f:
                open_config = yaml.safe_load(f) or {}
        except (FileNotFoundError, yaml.YAMLError):
            open_config = {}
            self.data_yaml.update(open_config)


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
    app = SHOPIFY_ZOHO_ORCHESTRATOR()
    app.menu()