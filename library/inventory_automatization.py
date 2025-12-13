import os
from colorama import Fore, init, Style
from pymongo import MongoClient
import sys
import yaml
from dotenv import load_dotenv
from pprint import pprint
from copy import deepcopy
from datetime import date
import requests
import json
from pprint import pprint
import os
import re
import ast
from pprint import pprint
from pymongo import MongoClient
from colorama import init, Fore, Style
import re, ast


class INVENTORY_AUTOMATIZATION:
    def __init__(self, working_folder, yaml_data, store=None):
        init(autoreset=True)
        print(Fore.BLUE + "\tInicializando EL MÓDULO DE AUTOMATIZACIÓN DE TIENDAS" + Style.RESET_ALL)
        self.working_folder = working_folder
        self.data = yaml_data
        self.yaml_path = os.path.join(self.working_folder, "config.yml")
        self.store = store
        self._location_id_cache: dict[str, int] = {}

        self.product_payload = """
            # Llenar en una sola acción como header
            "title": 'data_dict.get("name")',
            "body_html": 'data_dict.get("description")',
            "vendor": 'data_dict.get("manufacturer")',
            "product_type": 'data_dict.get("product_type")',
            "status": 'data_dict.get("status")',
            "variants": [
                # Llenar con loop for como variants_items
                {
                    "price": 'str(data_dict.get("rate", 0))',
                    "sku": 'data_dict.get("sku")',
                    "inventory_management": "shopify",
                    "inventory_policy": "deny",
                    "taxable": True,
                }
            ]
        """

    # -------------------------
    # Helpers
    # -------------------------
    @staticmethod
    def _safe_str(x):
        return None if x is None else str(x)

    @staticmethod
    def _strip_inline_comment(line: str) -> str:
        """Quita comentarios con #, pero solo si el # está fuera de comillas."""
        out = []
        in_single = False
        in_double = False
        escaped = False

        for ch in line:
            if ch == "\\" and not escaped:
                escaped = True
                out.append(ch)
                continue

            if ch == "'" and not in_double and not escaped:
                in_single = not in_single
            elif ch == '"' and not in_single and not escaped:
                in_double = not in_double

            if ch == "#" and not in_single and not in_double:
                break

            out.append(ch)
            escaped = False

        return "".join(out)


    def _template_to_schema(self, template: str) -> dict:
        """
        Convierte el template a un schema (estructura) de keys permitidas.
        - Ignora comentarios
        - No evalúa expresiones: solo necesita llaves
        """
        # 1) limpiar comentarios y líneas vacías
        cleaned_lines = []
        for raw in (template or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            line = self._strip_inline_comment(line).strip()
            if line:
                cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines)

        # 2) volver "seguras" las expresiones en comilla simple para literal_eval
        #    'data_dict.get("name")' -> "__EXPR__data_dict.get(\"name\")"
        def _mark_expr(m: re.Match) -> str:
            prefix = m.group(1)
            expr = m.group(2)
            expr_escaped = expr.replace("\\", "\\\\").replace('"', '\\"')
            return f'{prefix}"__EXPR__{expr_escaped}"'

        cleaned = re.sub(r"(:\s*)'([^']*)'", _mark_expr, cleaned)

        # 3) parsear a dict (no requiere que el template tenga { })
        dict_src = "{\n" + cleaned + "\n}"
        try:
            template_dict = ast.literal_eval(dict_src)
        except Exception as e:
            raise ValueError(f"Template inválido para schema. Error: {e}\n\nFuente:\n{dict_src}") from e

        # 4) construir schema (solo llaves)
        def _build_schema(node):
            if isinstance(node, dict):
                return {k: _build_schema(v) for k, v in node.items()}
            if isinstance(node, list):
                # si es lista de dicts, tomamos el schema del primer dict
                if node and isinstance(node[0], dict):
                    return [_build_schema(node[0])]
                return []  # lista simple (no dicts)
            # scalar -> hoja
            return None

        return _build_schema(template_dict)

    def _filter_by_schema(self, data, schema, keep_missing: bool = False):
        """
        Filtra data usando schema.
        - dict: conserva solo keys del schema
        - list de dicts: filtra cada elemento con el schema del primer elemento
        - scalar: devuelve tal cual
        """
        if schema is None:
            return data

        if isinstance(schema, dict):
            if not isinstance(data, dict):
                return {} if not keep_missing else {k: None for k in schema.keys()}

            out = {}
            for k, sub_schema in schema.items():
                if k in data:
                    out[k] = self._filter_by_schema(data[k], sub_schema, keep_missing=keep_missing)
                elif keep_missing:
                    out[k] = None
            return out

        if isinstance(schema, list):
            # schema de lista
            if not isinstance(data, list):
                return [] if not keep_missing else [None]
            if not schema:
                return data  # lista de escalares, no filtramos
            item_schema = schema[0]
            return [self._filter_by_schema(x, item_schema, keep_missing=keep_missing) for x in data]

        # fallback
        return data

    def _filter_keys(self, template: str, data_dict: dict, keep_missing: bool = False) -> dict:
        """
        Filtra data_dict con el schema derivado del template, incluyendo anidados (variants).
        """
        schema = self._template_to_schema(template)
        return self._filter_by_schema(data_dict, schema, keep_missing=keep_missing)    
    def _template_str_to_dict(self, template: str, data_dict: dict) -> dict:
        """
        Convierte el template string a dict final (header + variants):
        - Ignora comentarios (#) fuera de comillas
        - Values entre comillas simples '...' se evalúan como expresión
        - Values entre comillas dobles "..." se quedan literales
        - Separa header vs variants:
            * header se evalúa 1 vez
            * variants se evalúa en loop (si Zoho trae variantes)
        """

        # 1) limpiar comentarios y líneas vacías
        cleaned_lines = []
        for raw in (template or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            line = self._strip_inline_comment(line).strip()
            if line:
                cleaned_lines.append(line)

        cleaned = "\n".join(cleaned_lines)

        # 2) marcar valores con comilla simple como expresiones
        def _mark_expr(m: re.Match) -> str:
            prefix = m.group(1)   # ':\s*'
            expr = m.group(2)     # contenido entre '...'
            expr_escaped = expr.replace("\\", "\\\\").replace('"', '\\"')
            return f'{prefix}"__EXPR__{expr_escaped}"'

        cleaned = re.sub(r"(:\s*)'([^']*)'", _mark_expr, cleaned)

        # 3) parsear como dict literal (envolvemos en { })
        dict_src = "{\n" + cleaned + "\n}"
        try:
            template_dict = ast.literal_eval(dict_src)
        except Exception as e:
            raise ValueError(
                f"No pude convertir el template a dict. Error: {e}\n\nFuente:\n{dict_src}"
            ) from e

        # ---- helpers internos ----
        def _eval_node(node, ctx: dict, parent: dict):
            """Evalúa recursivamente __EXPR__... usando ctx como data_dict y parent_dict."""
            if isinstance(node, dict):
                return {k: _eval_node(v, ctx, parent) for k, v in node.items()}
            if isinstance(node, list):
                return [_eval_node(x, ctx, parent) for x in node]
            if isinstance(node, str) and node.startswith("__EXPR__"):
                expr = node[len("__EXPR__"):]
                safe_globals = {"__builtins__": {}}
                safe_locals = {
                    "data_dict": ctx,
                    "parent_dict": parent,  # 👈 item Zoho completo
                    "str": str,
                    "int": int,
                    "float": float,
                    "round": round,
                    "max": max,
                    "min": min,
                    "len": len,
                }
                return eval(expr, safe_globals, safe_locals)
            return node

        # 4) separar header y variants (body)
        variants_template = template_dict.pop("variants", [])
        # variants_template normalmente es [ { ... } ]
        variant_tpl = variants_template[0] if (isinstance(variants_template, list) and variants_template) else {}

        # 5) evaluar header 1 vez (ctx = item Zoho)
        header = _eval_node(template_dict, ctx=data_dict, parent=data_dict)

        # 6) detectar variantes Zoho (si existen)
        #    Ajusta/expande esta lista según tu estructura real en Zoho:
        candidate_keys = ["variants", "variant_items", "variants_items", "item_variants"]
        zoho_variants = None
        for k in candidate_keys:
            v = data_dict.get(k)
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                zoho_variants = v
                break

        # fallback: si no hay variantes Zoho, usamos 1 variante basada en el item
        if not zoho_variants:
            zoho_variants = [data_dict]

        # 7) poblar variants en loop
        variants_out = []
        for vdict in zoho_variants:
            payload_variant = _eval_node(variant_tpl, ctx=vdict, parent=data_dict)
            variants_out.append(payload_variant)

        # 8) reintegrar variants al header y retornar
        header["variants"] = variants_out
        return header
    # -------------------------
    # Tu función (fragmento)
    # -------------------------
    def shopify_update_items(self, store: str, logger=None):
        def _log(msg: str):
            if callable(logger):
                logger(str(msg))
            else:
                print(str(msg))

        mongo_db_url = self.data["non_sql_database"]["url"]
        client = MongoClient(mongo_db_url)

        zoho_items = list(client["Zoho_Inventory"]["items"].find({}))
        store_items = list(client[store]["products"].find({}))
        items_per_store_doc = client["Zoho_Inventory"]["items_per_store"].find_one({"store": store})

        if not items_per_store_doc:
            _log(f"❌ No existe items_per_store para store={store}")
            return

        # índices (ajusta keys según tu realidad)
        zoho_by_id = {str(x.get("item_id")): x for x in zoho_items if x.get("item_id") is not None}
        shopify_by_id = {str(x.get("id")): x for x in store_items if x.get("id") is not None}

        bridge_items = items_per_store_doc.get("items", [])
        missing_zoho, missing_shopify = [], []
        #zoho_doc = {}

        for link in bridge_items:
            zoho_id = self._safe_str(link.get("item_id"))
            shopify_id = self._safe_str(link.get("shopify_id"))

            zoho_doc = zoho_by_id.get(zoho_id) if zoho_id else None
            shopify_doc = shopify_by_id.get(shopify_id) if shopify_id else None

            if zoho_id and not zoho_doc:
                missing_zoho.append(zoho_id)
                continue
            if shopify_id and not shopify_doc:
                missing_shopify.append(shopify_id)
                continue

            # ✅ AQUÍ lo que pediste:
            item_zoho_version = self._template_str_to_dict(self.product_payload, data_dict=zoho_doc)


            pprint(item_zoho_version)
            item_shopif_version  = self._filter_keys(self.product_payload, data_dict=shopify_doc)
            pprint(item_shopif_version)
            return

        _log(f"missing_zoho={len(missing_zoho)} | missing_shopify={len(missing_shopify)}")

        
    def run_inventory_sync(self, store: str, logger=None):
        """
        Orquesta:
        1) Construir payloads de creación/actualización/desactivación.
        2) Enviar a Shopify.
        3) Guardar vínculos Zoho <-> Shopify al crear.
        """
        def _log(msg: str):
            if callable(logger):
                logger(str(msg))
            else:
                print(str(msg))


        products_to_update = self.shopify_update_items(store, logger=logger)
        """
        if products_to_update: 
            # lo que aplique 
            self.send_workload_to_shopify_api(products_to_update, store, "POST")
            self.send_workload_to_shopify_api(products_to_update, store, "PUT")
            self.send_workload_to_shopify_api(products_to_update, store, "PUT")
            self.send_workload_to_shopify_api(products_to_update, store, "UPDATE_NUMBER")
        """


if __name__ == "__main__":
    BASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # Aseguramos que BASE_PATH esté en sys.path
    if BASE_PATH not in sys.path:
        sys.path.insert(0, BASE_PATH) 
    env_file = os.path.join(BASE_PATH, ".env")
    folder_name = "MAIN_PATH"
    data_access = {}
    working_folder = BASE_PATH

    if os.path.exists(env_file):
        # Modo desarrollo local: leemos .env
        load_dotenv(dotenv_path=env_file)
        env_main_path = os.getenv(folder_name)
        if env_main_path:
            working_folder = env_main_path
            print(f"✅ MAIN_PATH tomado desde .env: {working_folder}")
        else:
            print(
                f"⚠️ Se encontró .env en {env_file} pero la variable {folder_name} no está definida.\n"
                f"Se usará BASE_PATH como working_folder: {working_folder}"
            )

    else:
        # Probablemente estamos en Render.com (no hay .env en el repo)
        env_main_path = os.getenv(folder_name)

        if env_main_path:
            # Caso ideal: definiste MAIN_PATH en las environment vars de Render
            working_folder = env_main_path
            print(f"✅ MAIN_PATH tomado de variables de entorno del sistema: {working_folder}")
        else:
            # Último fallback: el directorio actual del proceso (repo en Render)
            working_folder = os.getcwd()
            print(
                "⚠️ No se encontró .env ni variable de entorno MAIN_PATH.\n"
                f"Se usará el directorio actual como working_folder: {working_folder}"
            )

    # BASE_PATH y working_folder definidos antes
    root_yaml = os.path.join(BASE_PATH, "config", "open_config.yml")
    pkg_yaml = os.path.join(working_folder, "config.yml")

    root_exists = os.path.exists(root_yaml)
    pkg_exists = os.path.exists(pkg_yaml)

    # Mensajes por archivo
    if root_exists:
        print(f"✅ Se encontró configuración raíz: {root_yaml}")
    else:
        print(f"⚠️ No se encontró configuración raíz en: {root_yaml}")

    if pkg_exists:
        print(f"✅ Se encontró configuración de paquete: {pkg_yaml}")
    else:
        print(f"⚠️ No se encontró configuración de paquete en: {pkg_yaml}")

    # Si no existe ninguno, detenemos
    if not root_exists and not pkg_exists:
        print(
            "❌ No se encontró ningún archivo de configuración.\n"
            f"- {root_yaml}\n"
            f"- {pkg_yaml}"
        )
        sys.exit(1)

    # Cargar y combinar data de ambos YAML
    yaml_data = {}

    if root_exists:
        with open(root_yaml, "r") as f:
            root_data = yaml.safe_load(f) or {}
            yaml_data.update(root_data)  # base

    if pkg_exists:
        with open(pkg_yaml, "r") as f:
            pkg_data = yaml.safe_load(f) or {}
            yaml_data.update(pkg_data)   # sobreescribe claves si ya existen
    # Lanza la función de automatización            

    stores = ["managed_store_one", "managed_store_two"]
    for store in stores: 
        print(f"Sincronizando inventario para {store}...")
        from library.inventory_automatization import INVENTORY_AUTOMATIZATION
        app = INVENTORY_AUTOMATIZATION(working_folder, yaml_data, store)
        #from library.shopify_mongo_db import SHOPIFY_MONGODB
        #shopify_management = SHOPIFY_MONGODB(self.working_folder, self.data, store)
        #shopify_management.sync_shopify_to_mongo()        
        app.run_inventory_sync(store)