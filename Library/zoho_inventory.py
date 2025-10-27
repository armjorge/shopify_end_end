from colorama import Fore, init
import requests
import json
import yaml
import os


class ZOHO_INVENTORY:
    def __init__(self, working_folder, yaml_data):
        print(Fore.BLUE + "Inicializando ZOHO_INVENTORY")
        self.working_folder = working_folder
        self.data = yaml_data
        self.yaml_path = os.path.join(self.working_folder, "config.yml")

    def get_zoho_items(self, page=1, per_page=200):
        """
        Obtiene items del inventario de Zoho y devuelve una lista de dicts limpios.
        """ 
        zoho_conf = self.data['zoho']
        url = f"{zoho_conf['api_domain']}/inventory/v1/items"
        
        params = {
            "organization_id": zoho_conf['organization_id'],
            "page": page,
            "per_page": per_page
        }
        
        headers = {
            "Authorization": f"Zoho-oauthtoken {zoho_conf['access_token']}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(url, headers=headers, params=params)
        data_consulted = response.json()
        
        # Validamos la respuesta
        if data_consulted.get("code") != 0:
            print(Fore.RED + f"⚠️ Error al obtener datos de Zoho: {data_consulted.get('message')}")

            # Intentamos refrescar token si el error indica falta de autorización
            if "not authorized" in str(data_consulted.get("message", "")).lower():
                new_token = self.refresh_zoho_token()
                if new_token:
                    headers["Authorization"] = f"Zoho-oauthtoken {new_token}"
                    response = requests.get(url, headers=headers, params=params)
                    data_consulted = response.json()
                    if data_consulted.get("code") == 0:
                        print(Fore.GREEN + "✅ Token actualizado y datos obtenidos correctamente.")
                        return data_consulted.get("items", [])
                    else:
                        print(Fore.RED + f"❌ Error tras refrescar token: {data_consulted.get('message')}")
                        return []
                else:
                    return []

            return []

        # Si todo salió bien
        print(Fore.GREEN + f"✅ Datos obtenidos correctamente ({len(data_consulted.get('items', []))} items)")

        items = data_consulted.get("items", [])
        #if items:
        #    print(json.dumps(items[0], indent=2, ensure_ascii=False))
        
        # Unique field in items
        unique_items = {i.get("item_id"): i for i in items}.values()
        print(f"🔄 Items únicos obtenidos: {len(unique_items)}")
        # Limpiamos los campos más importantes
        """ 
        data_cleaned = [{
            "item_id": i.get("item_id"),
            "name": i.get("name"),
            "sku": i.get("sku"),
            "rate": i.get("rate"),
            "available_stock": i.get("available_stock"),
            "is_active": i.get("is_active"),
            "status": i.get("status")
        } for i in items]

        print(f"✅ {len(data_cleaned)} items obtenidos de Zoho (página {page})")
        """
        # Ahora filtramos para quedarnos solo con los items cuyo 'status' sea 'active'.
        data_filtered = [item for item in unique_items if item.get('status') == 'active']

        print(f"✅ {len(data_filtered)} items activos después del filtrado")
        return data_filtered
    
    def refresh_zoho_token(self):
        """Refresca el access_token de Zoho y actualiza el YAML."""
        try:
            with open(self.yaml_path, "r") as f:
                config = yaml.safe_load(f)

            zoho_conf = config.get("zoho", {})
            data = {
                "refresh_token": zoho_conf.get("refresh_token"),
                "client_id": zoho_conf.get("client_id"),
                "client_secret": zoho_conf.get("client_secret"),
                "grant_type": "refresh_token",
            }

            print(Fore.YELLOW + "🔄 Refrescando token de Zoho...")
            token_url = "https://accounts.zoho.com/oauth/v2/token"
            response = requests.post(token_url, data=data)
            token_data = response.json()

            if "access_token" not in token_data:
                print(Fore.RED + f"❌ Error al refrescar token: {token_data}")
                return None

            new_access_token = token_data["access_token"]
            config["zoho"]["access_token"] = new_access_token

            # Guardar YAML actualizado
            with open(self.yaml_path, "w") as f:
                yaml.safe_dump(config, f, sort_keys=False)

            # Actualizar en memoria
            self.data["zoho"]["access_token"] = new_access_token

            print(Fore.GREEN + "✅ Token renovado y YAML actualizado.")
            return new_access_token

        except Exception as e:
            print(Fore.RED + f"⚠️ Error al refrescar token: {e}")
            return None