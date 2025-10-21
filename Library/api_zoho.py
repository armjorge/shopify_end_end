import requests
import json

class ZohoAPI:
    def __init__(self, config):
        self.base_url = config['zoho']['base_url']
        self.org_id = config['zoho']['organization_id']
        self.refresh_token = config['zoho']['refresh_token']
        self.client_id = config['zoho']['client_id']
        self.client_secret = config['zoho']['client_secret']
        self.access_token = self.refresh_access_token()

    def refresh_access_token(self):
        url = "https://accounts.zoho.com/oauth/v2/token"
        params = {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token"
        }
        response = requests.post(url, params=params)
        token = response.json().get("access_token")
        return token

    def get_items(self):
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}"}
        response = requests.get(f"{self.base_url}/items?organization_id={self.org_id}", headers=headers)
        return response.json()