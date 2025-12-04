import os
from dotenv import load_dotenv
from colorama import Fore, Style, init
from library.yaml_creator import YAMLCREATOR
from library.zoho_inventory import ZOHO_INVENTORY
from pprint import pprint

class APEX_SYNC:
    # Orchstrate the main flow
    def apex_sync_menu(self):
        init(autoreset=True)
        print(f"{Fore.RED}APEX SYNC{Style.RESET_ALL}")

        

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
    app = APEX_SYNC()
    app.apex_sync_menu()