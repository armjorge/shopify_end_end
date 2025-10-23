import os
import yaml
from colorama import Fore, init

class YAMLCREATOR:
    def __init__(self, working_folder):
        print(Fore.BLUE + "Inicializando YAMLCREATOR")
        self.working_folder = working_folder
        self.yaml_path = os.path.join(working_folder, "config.yml")
        self.data = self.yaml_creation(working_folder)

    def yaml_creation(self, working_folder):
        output_yaml = self.yaml_path
        yaml_exists = os.path.exists(output_yaml)

        yaml_content = """
shopify:
  store_name: ".myshopify.com"
  api_version: "2024-10"
  access_token: "shpat_"  # Admin API token (⚠️ mantener privado)
  endpoints:
    products: "/admin/api/2024-10/products.json"
    inventory_levels: "/admin/api/2024-10/inventory_levels.json"
    orders: "/admin/api/2024-10/orders.json?status=any"
    locations: "/admin/api/2024-10/locations.json"
  headers:
    Content-Type: "application/json"
    X-Shopify-Access-Token: "${shopify.access_token}"

zoho:
  client_id: "100"
  client_secret: "8790"
  refresh_token: "1000..."
  api_domain: "https://www.zohoapis.com"
  access_token: "1000.."
  organization_id: "65"
  scope: "ZohoInventory.FullAccess.all"


"""
        expected_data = yaml.safe_load(yaml_content)
        expected_keys = set(expected_data.keys())

        if yaml_exists:
            # Abrir y cargar el contenido YAML en un diccionario
            with open(output_yaml, 'r', encoding='utf-8') as f:
                data_access = yaml.safe_load(f)
            if data_access is None:
                data_access = {}
            print(f"\t✅ YAML file loaded successfully: {os.path.basename(output_yaml)}")
            
            current_keys = set(data_access.keys())
            missing_keys = expected_keys - current_keys
            extra_keys = current_keys - expected_keys
            if extra_keys:
                print(f"\t⚠️  New keys found in YAML that are not in the expected config: {', '.join(extra_keys)}")
                print("\t⚠️ Please add them to the yaml_content string in the code for future runs.")
            if missing_keys:
                print(f"Missing keys in YAML: {', '.join(missing_keys)}")
                for key in missing_keys:
                    value = input(f"Enter value for {key}: ")
                    data_access[key] = value
                # Write back the updated YAML
                with open(output_yaml, "w", encoding="utf-8") as f:
                    yaml.dump(data_access, f, default_flow_style=False)
                print("YAML updated with new keys.")
            return data_access

        else: 
            print("\tValid YAML not found, creating one")
            
            # Crear directorio si no existe
            os.makedirs(working_folder, exist_ok=True)
            
            # Escribe el archivo YAML
            with open(output_yaml, "w", encoding="utf-8") as f:
                f.write(yaml_content)
            print("\tGenerated YAML for you to fill in, please rerun the script to open it.")
            
            # Since recently created, prompt for actual values
            data_access = yaml.safe_load(yaml_content)
            print("\tPlease enter actual values for the config:")
            for key in data_access.keys():
                value = input(f"\tEnter value for {key} ({data_access[key]}): ")
                if value.strip():
                    data_access[key] = value
            # Write back with updated values
            with open(output_yaml, "w", encoding="utf-8") as f:
                yaml.dump(data_access, f, default_flow_style=False)
            print("\tYAML created and updated with your inputs.")
            return data_access