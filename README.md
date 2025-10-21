# shopify_end_end
El proyecto es una integración end-to-end Shopify ↔ Oracle ↔ PAQ (facturación mexicana) ↔ Gestor de Inventarios, con trazabilidad total del flujo operativo.

shopify_end_end/
│
├── Library/
│   ├── shopify_inventory.py        # Clase principal
│   ├── api_zoho.py                 # Cliente Zoho API
│   ├── api_shopify.py              # Cliente Shopify API
│   ├── utils.py                    # Logs, manejo de errores
│   └── config.yaml                 # Tokens y rutas
│
├── main.py                         # Entrada principal (CLI)
├── requirements.txt
└── README.md