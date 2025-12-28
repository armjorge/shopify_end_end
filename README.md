

# Shopify End-to-End Inventory & Catalog Sync

A Python automation system that integrates **Zoho Inventory (ERP)** with **multiple Shopify stores**, providing synchronization of inventory levels, product catalog fields, and images. The system can persist API payloads in MongoDB and execute reliable sync workflows to keep e-commerce listings consistent and up-to-date.

## Features

- **Multi-Store Support**: Manage multiple Shopify stores from a single Zoho Inventory instance
- **Inventory & Catalog Sync**: Synchronize product fields and inventory levels
- **Image Management**: Sync product images between Zoho and Shopify stores
- **Data Persistence**: Store API payloads and sync history in MongoDB
- **Error Handling**: Logging and recovery mechanisms
- **Configurable**: YAML-based configuration + environment variables for secrets

## Architecture

Zoho Inventory (ERP) ↔ Python Sync Engine ↔ Multiple Shopify Stores
↓
MongoDB (Persistence)
↓
PostgreSQL (Analytics)

## Project Structure

shopify_end_end/
│
├── Library/
│   ├── shopify_inventory.py        # Main integration class
│   ├── api_zoho.py                 # Zoho Inventory API client
│   ├── api_shopify.py              # Shopify API client
│   ├── utils.py                    # Logging and error handling utilities
│   ├── config.example.yaml         # ✅ Example config (NO secrets)
│   └── config.yaml                 # ❌ Local-only config (secrets) - gitignored
│
├── main.py                         # CLI entry point
├── requirements.txt                # Python dependencies
└── README.md

## Configuration

### 1) Create your local config (DO NOT COMMIT)

Copy the example file:

```bash
cp Library/config.example.yaml Library/config.yaml

Edit Library/config.yaml with your store identifiers, but keep secrets in env vars.

2) Set environment variables

Export your secrets in the shell (or use a .env file loaded by your app if you implemented it):

export SHOPIFY_STORE_ONE_ACCESS_TOKEN="YOUR_TOKEN"
export SHOPIFY_STORE_TWO_ACCESS_TOKEN="YOUR_TOKEN"
export SHOPIFY_STORE_TWO_API_KEY="YOUR_KEY"
export SHOPIFY_STORE_TWO_API_SECRET="YOUR_SECRET"

export ZOHO_ACCESS_TOKEN="YOUR_TOKEN"
export ZOHO_CLIENT_ID="YOUR_CLIENT_ID"
export ZOHO_CLIENT_SECRET="YOUR_CLIENT_SECRET"
export ZOHO_REFRESH_TOKEN="YOUR_REFRESH_TOKEN"

export MONGODB_URL="mongodb+srv://USER:PASSWORD@HOST/DB"
export POSTGRES_URL="postgresql://USER:PASSWORD@HOST:5432/DB"

3) Example configuration file (safe)

Library/config.example.yaml:

managed_store_one:
  store_name: "your-store-one.myshopify.com"
  api_version: "2024-10"
  access_token_env: "SHOPIFY_STORE_ONE_ACCESS_TOKEN"

managed_store_two:
  store_name: "your-store-two.myshopify.com"
  api_version: "2024-10"
  access_token_env: "SHOPIFY_STORE_TWO_ACCESS_TOKEN"
  api_key_env: "SHOPIFY_STORE_TWO_API_KEY"
  api_secret_env: "SHOPIFY_STORE_TWO_API_SECRET"

zoho:
  api_domain: "https://www.zohoapis.com"
  organization_id: "YOUR_ORG_ID"
  scope: "ZohoInventory.FullAccess.all"
  access_token_env: "ZOHO_ACCESS_TOKEN"
  client_id_env: "ZOHO_CLIENT_ID"
  client_secret_env: "ZOHO_CLIENT_SECRET"
  refresh_token_env: "ZOHO_REFRESH_TOKEN"

sql_database:
  url_env: "POSTGRES_URL"

non_sql_database:
  url_env: "MONGODB_URL"

Your Python code should read *_env and then fetch the real value from os.environ[...].

Installation

git clone https://github.com/armjorge/shopify_end_end.git
cd shopify_end_end
pip install -r requirements.txt

Usage

python main.py

Security Notes
	•	Never commit config.yaml, .env, or any token/secret to git.
	•	Rotate credentials immediately if any secret was exposed.
	•	Use GitHub push protection + repository rules to prevent accidental leaks.

License

This project is proprietary software for internal use.