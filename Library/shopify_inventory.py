import os
import yaml
from colorama import Fore, init, Style

class SHOPIFY_ZOHO:
    def __init__(self, working_folder, data_yaml):
        self.working_folder = working_folder
        self.data_yaml = data_yaml


    def shopify_zoho_integration(self):
        init(autoreset=True)
        print("\tThis script will integrate Shopify inventory with Zoho Inventory.")
