import os
from colorama import Fore, init
import requests
import json


class ZOHO_INVENTORY:
    def __init__(self, working_folder, yaml_data):
        print(Fore.BLUE + "Inicializando ZOHO_INVENTORY")
        self.working_folder = working_folder
        self.data = yaml_data

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
            print("⚠️ Error al obtener datos de Zoho:", data_consulted.get("message"))
            return []

        items = data_consulted.get("items", [])

        # Limpiamos los campos más importantes
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

        # Ahora filtramos para quedarnos solo con los items cuyo 'status' sea 'active'.
        data_filtered = [item for item in data_cleaned if item.get('status') == 'active']

        print(f"✅ {len(data_filtered)} items activos después del filtrado")


        
        return data_filtered