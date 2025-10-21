import requests

class ShopifyAPI:
    def __init__(self, config):
        self.store_name = config['shopify']['store_name']
        self.api_version = config['shopify']['api_version']
        self.token = config['shopify']['access_token']
        self.base_url = f"https://{self.store_name}/admin/api/{self.api_version}"

    def update_inventory(self, inventory_item_id, location_id, available):
        url = f"{self.base_url}/inventory_levels/set.json"
        headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": self.token}
        payload = {
            "location_id": location_id,
            "inventory_item_id": inventory_item_id,
            "available": available
        }
        response = requests.post(url, json=payload, headers=headers)
        return response.json()