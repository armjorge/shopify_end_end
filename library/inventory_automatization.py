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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import time
from datetime import datetime, timezone


class INVENTORY_AUTOMATIZATION:
    def __init__(self, working_folder, yaml_data, store=None):
        init(autoreset=True)
        print(Fore.BLUE + f"\tInicializando EL MÓDULO DE AUTOMATIZACIÓN DE TIENDA {store}" + Style.RESET_ALL)
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
                    "price": 'str(data_dict.get("rate", 00))',
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
        if not isinstance(data_dict, dict):
            raise TypeError(f"data_dict debe ser dict, recibí {type(data_dict)}")

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

        # 2) marcar expresiones en comilla simple como __EXPR__
        def _mark_expr(m: re.Match) -> str:
            prefix = m.group(1)
            expr = m.group(2)
            expr_escaped = expr.replace("\\", "\\\\").replace('"', '\\"')
            return f'{prefix}"__EXPR__{expr_escaped}"'

        cleaned = re.sub(r"(:\s*)'([^']*)'", _mark_expr, cleaned)

        # 3) parsear a dict literal
        dict_src = "{\n" + cleaned + "\n}"
        template_dict = ast.literal_eval(dict_src)

        # 4) separar header y variants
        variants_template = template_dict.pop("variants", [])
        variant_tpl = variants_template[0] if (isinstance(variants_template, list) and variants_template) else {}

        # 5) eval helper
        def _eval_node(node, ctx: dict, parent: dict):
            if isinstance(node, dict):
                return {k: _eval_node(v, ctx, parent) for k, v in node.items()}
            if isinstance(node, list):
                return [_eval_node(x, ctx, parent) for x in node]
            if isinstance(node, str) and node.startswith("__EXPR__"):
                expr = node[len("__EXPR__"):]
                safe_globals = {"__builtins__": {}}
                safe_locals = {
                    "data_dict": ctx,
                    "parent_dict": parent,
                    "str": str,
                    "int": int,
                    "float": float,
                    "round": round,
                    "len": len,
                    "max": max,
                    "min": min,
                }
                return eval(expr, safe_globals, safe_locals)
            return node

        # 6) evaluar header (una vez)
        header = _eval_node(template_dict, ctx=data_dict, parent=data_dict)

        # 7) poblar variants (loop)
        # si no tienes variantes en Zoho, usamos 1 “fallback”
        zoho_variants = None
        for k in ("variants", "variant_items", "variants_items", "item_variants"):
            v = data_dict.get(k)
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                zoho_variants = v
                break
        if not zoho_variants:
            zoho_variants = [data_dict]

        variants_out = []
        for vdict in zoho_variants:
            variants_out.append(_eval_node(variant_tpl, ctx=vdict, parent=data_dict))

        header["variants"] = variants_out

        # ✅ IMPORTANTÍSIMO: return explícito
        return header    
    # Sección para comparar diccionarios y construir lista de actualización

    def _deep_diff(self, a, b, path=""):
        """
        Devuelve lista de diferencias: [(path, a_value, b_value), ...]
        Comparación literal (strings exactos, incluyendo saltos de línea).
        """
        diffs = []

        # Tipos distintos → diferencia directa
        if type(a) != type(b):
            diffs.append((path, a, b))
            return diffs

        # Dict
        if isinstance(a, dict):
            keys = set(a.keys()) | set(b.keys())
            for k in sorted(keys):
                p = f"{path}.{k}" if path else k
                if k not in a:
                    diffs.append((p, None, b.get(k)))
                elif k not in b:
                    diffs.append((p, a.get(k), None))
                else:
                    diffs.extend(self._deep_diff(a[k], b[k], p))
            return diffs

        # List
        if isinstance(a, list):
            if len(a) != len(b):
                diffs.append((path + ".__len__", len(a), len(b)))
            # comparamos por índice hasta el mínimo común
            n = min(len(a), len(b))
            for i in range(n):
                p = f"{path}[{i}]"
                diffs.extend(self._deep_diff(a[i], b[i], p))
            return diffs

        # Scalars (str, int, bool, None, etc.)
        if a != b:
            diffs.append((path, a, b))
        return diffs

    def _build_shopify_update_payload(
        self,
        *,
        shopify_doc: dict,
        desired: dict,
        current: dict,
        match_variant_by: str = "sku",
    ) -> dict | None:
        """
        Construye body de actualización SOLO con campos que difieren.

        Reglas:
        - Si Zoho trae '' o None -> NO intentamos borrar en Shopify (skip)
        - '' y None se consideran equivalentes (no es diferencia)
        - price se compara numérico a 2dp
        - status: draft ≡ inactive
        - variants: solo agrega si hay cambios reales (además del id)
        """
        def _is_empty(v):
            return v is None or (isinstance(v, str) and v == "")

        def _empty_equal(a, b):
            return _is_empty(a) and _is_empty(b)

        def _equal(k: str, a, b) -> bool:
            # vacíos equivalentes
            if _empty_equal(a, b):
                return True
            # price
            if k == "price":
                return self._norm_price_2dp(a) == self._norm_price_2dp(b)
            # status
            if k == "status":
                return self._norm_status(a) == self._norm_status(b)
            # default literal
            return a == b

        if not isinstance(desired, dict) or not isinstance(current, dict):
            return None

        product_id = shopify_doc.get("id")
        if not product_id:
            raise ValueError("shopify_doc no trae 'id' (product_id).")

        # 1) Header changes (top-level excepto variants)
        header_updates = {}
        for k, desired_val in desired.items():
            if k == "variants":
                continue

            cur = current.get(k)

            # si Zoho viene vacío, NO intentar borrar
            if _is_empty(desired_val):
                continue

            if not _equal(k, desired_val, cur):
                header_updates[k] = desired_val

        # 2) Variants changes
        desired_variants = desired.get("variants") or []
        current_variants = current.get("variants") or []
        full_shopify_variants = (shopify_doc.get("variants") or [])

        # Index por SKU (full shopify) para ubicar variant_id real
        shopify_variant_by_sku = {}
        for sv in full_shopify_variants:
            sku = sv.get("sku")
            if sku is not None:
                shopify_variant_by_sku[str(sku)] = sv

        variant_updates = []

        for i, dv in enumerate(desired_variants):
            if not isinstance(dv, dict):
                continue

            cv = current_variants[i] if i < len(current_variants) and isinstance(current_variants[i], dict) else {}

            # si ya coincide (ojo: esta comparación es literal; si quieres más fino, pásales normalizados)
            if dv == cv:
                continue

            # ubicar variant_id real
            sv_full = None
            if match_variant_by == "sku":
                sku = dv.get("sku")
                if sku is not None and str(sku) != "":
                    sv_full = shopify_variant_by_sku.get(str(sku))

            if sv_full is None:
                # fallback por índice
                if i < len(full_shopify_variants):
                    sv_full = full_shopify_variants[i]

            if not sv_full or not sv_full.get("id"):
                raise ValueError(
                    f"No pude ubicar variant_id en Shopify para la variante #{i}. "
                    f"SKU desired={dv.get('sku')}."
                )

            vupd = {"id": sv_full["id"]}

            for k, desired_val in dv.items():
                if k == "id":
                    continue

                cur = cv.get(k)

                # si Zoho viene vacío, NO intentar borrar
                if _is_empty(desired_val):
                    continue

                if not _equal(k, desired_val, cur):
                    vupd[k] = desired_val

            # ✅ solo si hay cambios reales además del id
            if len(vupd) > 1:
                variant_updates.append(vupd)

        # 3) Si no hay cambios, no payload
        if not header_updates and not variant_updates:
            return None

        payload = {"product": {"id": product_id, **header_updates}}
        if variant_updates:
            payload["product"]["variants"] = variant_updates

        return payload    
    

    def _norm_price_2dp(self, v):
        """
        Normaliza precios para comparación:
        - '218.0' -> Decimal('218.00')
        - '218.00' -> Decimal('218.00')
        - None -> None
        """
        if v is None:
            return None
        try:
            d = Decimal(str(v).strip())
            return d.quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return v  # si no se puede parsear, compara literal

    def _norm_status(self, v):
        """
        Normaliza status para comparación:
        inactive ≡ draft  -> ambos se vuelven 'inactive'
        """
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("draft", "inactive"):
            return "inactive"
        return s

    def _normalized_for_compare(self, d: dict):
        """
        Copia normalizada SOLO para comparación (no para payload):
        - '' -> None (en todos los niveles)
        - status: draft ≡ inactive
        - price: Decimal a 2dp (0 == 0.00, .5 == .50)
        """
        if not isinstance(d, dict):
            return d

        def _is_empty(v):
            return v is None or (isinstance(v, str) and v == "")

        def _norm_any(node):
            # dict
            if isinstance(node, dict):
                out = {}
                for k, v in node.items():
                    # normaliza vacío
                    if isinstance(v, str) and v == "":
                        v = None

                    # status
                    if k == "status":
                        out[k] = self._norm_status(v)
                        continue

                    # price
                    if k == "price":
                        out[k] = self._norm_price_2dp(v)
                        continue

                    out[k] = _norm_any(v)
                return out

            # list
            if isinstance(node, list):
                return [_norm_any(x) for x in node]

            # scalar
            if isinstance(node, str) and node == "":
                return None

            return node

        return _norm_any(d)

    def send_workload_to_shopify_api(self, products_to_update: list[dict], store: str, logger=None) -> list[dict]:
        """
        products_to_update: lista como la que ya generas:
        [{
            "shopify_product_id": ...,
            "payload": {"product": {...}}
        }, ...]
        store: "managed_store_one" | "managed_store_two" (key en tu YAML)
        """
        def _log(msg: str):
            if callable(logger):
                logger(str(msg))
            else:
                print(str(msg))

        if not products_to_update:
            _log("ℹ️ No hay productos para actualizar.")
            return []

        # ===== config simple desde YAML (estructura que me diste) =====
        shop_conf = self.data[store]
        api_version = shop_conf.get("api_version", "2024-10")
        store_name = shop_conf["store_name"].strip().replace("https://", "").replace("http://", "").strip("/")

        base_url = f"https://{store_name}/admin/api/{api_version}"
        headers = {
            "Content-Type": "application/json",
            # SIEMPRE usar access_token (no depender de headers en YAML con placeholders)
            "X-Shopify-Access-Token": shop_conf["access_token"],
        }

        # ===== comparadores equivalentes (SIN helpers de clase) =====
        def _norm_price_2dp(v):
            if v is None:
                return None
            try:
                d = Decimal(str(v).strip())
                return d.quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)
            except (InvalidOperation, ValueError):
                return v  # si no parsea, literal

        def _norm_status(v):
            if v is None:
                return None
            s = str(v).strip().lower()
            return "inactive" if s in ("draft", "inactive") else s

        def _payload_mismatches(payload_product: dict, fetched_product: dict) -> list[dict]:
            mismatches = []

            def _cmp(path: str, expected, actual):
                def _is_empty(v):
                    return v is None or (isinstance(v, str) and v == "")

                def _empty_equal(a, b):
                    return _is_empty(a) and _is_empty(b)     
                if _empty_equal(expected, actual):
                    return
                                           
                if path.endswith(".price"):
                    if _norm_price_2dp(expected) != _norm_price_2dp(actual):
                        mismatches.append({"path": path, "expected": expected, "actual": actual})
                    return
                if path.endswith(".status"):
                    if _norm_status(expected) != _norm_status(actual):
                        mismatches.append({"path": path, "expected": expected, "actual": actual})
                    return
                if expected != actual:
                    mismatches.append({"path": path, "expected": expected, "actual": actual})

            # header (except id/variants)
            for k, v in (payload_product or {}).items():
                if k in ("id", "variants"):
                    continue
                _cmp(k, v, (fetched_product or {}).get(k))

            # variants: match por id
            pv_list = (payload_product or {}).get("variants") or []
            fv_list = (fetched_product or {}).get("variants") or []
            fv_by_id = {str(v.get("id")): v for v in fv_list if v.get("id") is not None}

            for pv in pv_list:
                if not isinstance(pv, dict):
                    continue
                vid = pv.get("id")
                if vid is None:
                    mismatches.append({"path": "variants[].id", "expected": "<missing id in payload>", "actual": None})
                    continue
                fv = fv_by_id.get(str(vid))
                if not fv:
                    mismatches.append({"path": f"variants[{vid}]", "expected": "<variant exists>", "actual": None})
                    continue
                for kk, vv in pv.items():
                    if kk == "id":
                        continue
                    _cmp(f"variants[{vid}].{kk}", vv, fv.get(kk))

            return mismatches

        session = requests.Session()
        session.headers.update(headers)

        results = []

        for job in products_to_update:
            pid = job.get("shopify_product_id") or job.get("product_id")
            payload = job.get("payload")
            zoho_item_id = job.get("zoho_item_id")  # 👈 nuevo (para linkeo)


            if not isinstance(payload, dict) or "product" not in payload:
                _log(f"⚠️ Job inválido, lo salto: pid={repr(pid)} keys={list(job.keys())}")
                results.append({"product_id": pid, "ok": False, "error": "invalid_job", "job": job})
                continue
            if not pid:
                post_url = f"{base_url}/products.json"
                try:
                    r = session.post(post_url, json=payload, timeout=60)
                except Exception as e:
                    _log(f"❌ POST error (create) zoho_item_id={repr(zoho_item_id)}: {repr(e)}")
                    results.append({"zoho_item_id": zoho_item_id, "product_id": None, "ok": False, "created": False, "error": str(e)})
                    continue

                if not r.ok:
                    _log(f"❌ POST failed (create) zoho_item_id={repr(zoho_item_id)} status={r.status_code}")
                    _log(f"   response: {getattr(r, 'text', '')[:2000]}")
                    results.append({"zoho_item_id": zoho_item_id, "product_id": None, "ok": False, "created": False, "status": r.status_code, "response": getattr(r, "text", "")})
                    continue

                created_product = (r.json() or {}).get("product", {}) or {}
                created_id = created_product.get("id")
                _log(f"✅ Creado product_id={created_id} (zoho_item_id={repr(zoho_item_id)})")

                results.append({
                    "zoho_item_id": zoho_item_id,
                    "product_id": created_id,
                    "ok": True,
                    "created": True,
                    "product": created_product,
                })
                continue

            put_url = f"{base_url}/products/{pid}.json"

            # ===== GET BEFORE (confirmación por API, no por Mongo) =====
            before = {}
            try:
                gb = session.get(f"{base_url}/products/{pid}.json", timeout=60)
                if gb.ok:
                    before = gb.json().get("product", {}) or {}
                else:
                    _log(f"⚠️ GET BEFORE status={gb.status_code} product_id={pid}")
            except Exception as e:
                _log(f"⚠️ GET BEFORE falló product_id={pid}: {repr(e)}")

            # ===== PUT =====
            try:
                r = session.put(put_url, json=payload, timeout=60)
            except Exception as e:
                _log(f"❌ PUT error product_id={pid}: {repr(e)}")
                results.append({"product_id": pid, "ok": False, "error": str(e)})
                continue

            if not r.ok:
                _log(f"❌ PUT failed product_id={pid} status={r.status_code}")
                _log(f"   response: {getattr(r, 'text', '')[:2000]}")
                results.append({"product_id": pid, "ok": False, "status": r.status_code, "response": getattr(r, "text", "")})
                continue
            # ===== verificación GET =====
            get_url = f"{base_url}/products/{pid}.json"
            try:
                g = session.get(get_url, timeout=60)
            except Exception as e:
                _log(f"⚠️ GET verify error product_id={pid}: {repr(e)}")
                results.append({"product_id": pid, "ok": True, "verified": False, "verify_error": str(e)})
                continue

            if not g.ok:
                _log(f"⚠️ GET verify failed product_id={pid} status={g.status_code}")
                results.append({"product_id": pid, "ok": True, "verified": False, "verify_status": g.status_code})
                continue

            fetched_product = g.json().get("product", {})
            payload_product = payload.get("product", {})

            # header
            for k in payload_product.keys():
                if k in ("id", "variants"):
                    continue
                _log(f"   {k}: BEFORE={repr(before.get(k))} AFTER={repr(fetched_product.get(k))}")

            # variants (por id)
            pv_list = payload_product.get("variants") or []
            fv_list = fetched_product.get("variants") or []
            fv_by_id = {str(v.get("id")): v for v in fv_list if v.get("id") is not None}

            for pv in pv_list:
                vid = pv.get("id")
                fv = fv_by_id.get(str(vid)) if vid is not None else None
                if not fv:
                    continue
                for kk in pv.keys():
                    if kk == "id":
                        continue
                    _log(f"   variants[{vid}].{kk}: BEFORE=<unknown> AFTER={repr(fv.get(kk))}")            
            mismatches = _payload_mismatches(payload_product, fetched_product)

            if mismatches:
                _log(f"⚠️ Actualizado pero NO coincide verificación product_id={pid}")
                for mm in mismatches:
                    _log(f"   - {mm['path']} | expected={repr(mm['expected'])} | actual={repr(mm['actual'])}")
                results.append({"product_id": pid, "ok": True, "verified": False, "mismatches": mismatches})
            else:
                _log(f"✅ Actualización verificada product_id={pid}")
                results.append({"product_id": pid, "ok": True, "verified": True})

        return results

    # Constructor de dos diccionarios idénticos basados en el template, para comparar
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
            return []

        # índices
        zoho_by_id = {str(x.get("item_id")): x for x in zoho_items if x.get("item_id") is not None}
        shopify_by_id = {str(x.get("id")): x for x in store_items if x.get("id") is not None}

        bridge_items = items_per_store_doc.get("items", [])

        missing_zoho, missing_shopify = [], []
        broken_links = 0
        bad_templates = 0

        # ✅ IMPORTANTÍSIMO: fuera del loop
        update_bodies = []
        not_listed_archives = 0

        for i, link in enumerate(bridge_items):
            zoho_id = self._safe_str(link.get("item_id"))
            shopify_id = self._safe_str(link.get("shopify_id"))
            print(f"{i} Producto procesado: ID_zoho {zoho_id}, shopify_id {shopify_id}")
            # ✅ vínculo roto
            if not shopify_id:
                broken_links += 1
                _log("⚠️ VÍNCULO INCOMPLETO en Zoho_Inventory.items_per_store")
                _log(f"   store: {store} | index: {i}")
                _log(f"   item_id (zoho): {repr(link.get('item_id'))}")
                _log(f"   shopify_id    : {repr(link.get('shopify_id'))}")
                _log(f"   name          : {repr(link.get('name'))}")
                _log(f"   link completo : {link}")
                continue

            zoho_doc = zoho_by_id.get(zoho_id)
            shopify_doc = shopify_by_id.get(shopify_id)

            # ✅ CASO NUEVO: hay shopify_id pero NO hay zoho_id → archivar en Shopify
            if zoho_id is None or zoho_id == "":
                shopify_doc = shopify_by_id.get(shopify_id)
                if not shopify_doc:
                    missing_shopify.append(shopify_id)
                    _log(f"⚠️ No encontré shopify_doc para product_id={shopify_id} (index={i})")
                    continue

                current_status = (shopify_doc.get("status") or "").lower()
                if current_status == "archived":
                    _log(f"✅ Ya estaba archived | product_id={shopify_doc.get('id')}")
                    continue

                payload = {
                    "product": {
                        "id": shopify_doc.get("id"),
                        "status": "archived",
                    }
                }

                update_bodies.append({
                    "shopify_product_id": shopify_doc.get("id"),
                    "shopify_admin_graphql_api_id": shopify_doc.get("admin_graphql_api_id"),
                    "zoho_item_id": None,
                    "diff_count": 1,
                    "payload": payload,
                    "reason": "missing_zoho_id_in_items_per_store",
                })

                _log(f"🗄️ Archivando en Shopify (sin zoho_id) | product_id={shopify_doc.get('id')} | link_index={i}")
                continue

            if not shopify_doc:
                missing_shopify.append(shopify_id)
                _log(f"⚠️ No encontré shopify_doc para product_id={shopify_id} (index={i})")
                continue

            # 1) construir versiones comparables
                      
            item_zoho_version = self._template_str_to_dict(self.product_payload, data_dict=zoho_doc)
            item_shopif_version = self._filter_keys(self.product_payload, data_dict=shopify_doc)
            #item_zoho_version = self._debug_template_build(self.product_payload, zoho_doc, store, i)
            # ✅ si algo salió raro (None), NO crashear: log y seguir
            if not isinstance(item_zoho_version, dict):
                bad_templates += 1
                _log("⚠️ item_zoho_version inválido (no es dict).")
                _log(f"   store: {store} | index: {i} | zoho_id={zoho_id} | shopify_id={shopify_id}")
                _log(f"   item_zoho_version: {repr(item_zoho_version)}")
                _log(f"   zoho_doc.name: {repr(zoho_doc.get('name'))}")
                continue

            if not isinstance(item_shopif_version, dict):
                bad_templates += 1
                _log("⚠️ item_shopif_version inválido (no es dict).")
                _log(f"   store: {store} | index: {i} | zoho_id={zoho_id} | shopify_id={shopify_id}")
                _log(f"   item_shopif_version: {repr(item_shopif_version)}")
                continue

            # 2) diff
            #diffs = self._deep_diff(item_zoho_version, item_shopif_version)
            zoho_cmp = self._normalized_for_compare(item_zoho_version)
            shopify_cmp = self._normalized_for_compare(item_shopif_version)

            diffs = self._deep_diff(zoho_cmp, shopify_cmp)            

            if not diffs:
                _log(f"✅ Sin diferencias | product_id={shopify_doc.get('id')} | zoho_id={zoho_id}")
                continue

            # 3) imprimir diff claro
            _log(f"🧾 DIFERENCIAS DETECTADAS | product_id={shopify_doc.get('id')} | zoho_id={zoho_id}")
            for p, a, b in diffs:
                _log(f" - {p}")
                _log(f"   desired: {repr(a)}")
                _log(f"   current: {repr(b)}")

            # 4) payload
            payload = self._build_shopify_update_payload(
                shopify_doc=shopify_doc,
                desired=item_zoho_version,
                current=item_shopif_version,
                match_variant_by="sku",
            )

            if not payload:
                _log(f"⚠️ No se generó payload (aunque hubo diffs) | product_id={shopify_doc.get('id')}")
                continue

            update_bodies.append({
                "shopify_product_id": shopify_doc.get("id"),
                "shopify_admin_graphql_api_id": shopify_doc.get("admin_graphql_api_id"),
                "zoho_item_id": zoho_doc.get("item_id") or zoho_doc.get("id"),
                "diff_count": len(diffs),
                "payload": payload,
            })

        # =========================================================
        # 2) EXTRA: Archivar productos que están en Shopify (store_items)
        #    pero NO están listados en items_per_store (bridge_items)
        # =========================================================

        bridge_shopify_ids = {
            self._safe_str(x.get("shopify_id"))
            for x in bridge_items
            if self._safe_str(x.get("shopify_id"))
        }

        store_shopify_ids = set(shopify_by_id.keys())  # ya son str(id)

        not_listed_shopify_ids = store_shopify_ids - bridge_shopify_ids

        

        for shopify_id in sorted(not_listed_shopify_ids):
            shopify_doc = shopify_by_id.get(shopify_id)

            if not shopify_doc:
                missing_shopify.append(shopify_id)
                _log(f"⚠️ No encontré shopify_doc para product_id={shopify_id} (not_listed)")
                continue

            current_status = (shopify_doc.get("status") or "").lower()
            if current_status == "archived":
                _log(f"✅ Ya estaba archived | product_id={shopify_doc.get('id')} (not_listed)")
                continue

            payload = {
                "product": {
                    "id": shopify_doc.get("id"),
                    "status": "archived",
                }
            }

            update_bodies.append({
                "shopify_product_id": shopify_doc.get("id"),
                "shopify_admin_graphql_api_id": shopify_doc.get("admin_graphql_api_id"),
                "zoho_item_id": None,
                "diff_count": 1,
                "payload": payload,
                "reason": "not_listed_in_items_per_store",
            })

            not_listed_archives += 1
            _log(f"🗄️ Archivando en Shopify (no listado en items_per_store) | product_id={shopify_doc.get('id')}")

        # resumen final
        _log(
        f"🔎 Resumen {store}: update_bodies={len(update_bodies)} | "
        f"broken_links={broken_links} | missing_zoho={len(missing_zoho)} | "
        f"missing_shopify={len(missing_shopify)} | bad_templates={bad_templates} | "
        f"not_listed_archives={not_listed_archives}"
        )

        # ✅ esto alimenta products_to_update
        return update_bodies
    

    ###################################    
    ## SECCIÓN PARA CREAR INVENTARIO ##
    ###################################
 
    def shopify_create_items(self, store: str, logger=None):
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
            return []

        zoho_by_id = {str(x.get("item_id")): x for x in zoho_items if x.get("item_id") is not None}
        shopify_by_id = {str(x.get("id")): x for x in store_items if x.get("id") is not None}

        bridge_items = items_per_store_doc.get("items", [])

        broken_links = 0
        create_jobs = []  # 👈 jobs (no dict suelto)

        for i, link in enumerate(bridge_items):
            zoho_id_raw = link.get("item_id")           # 👈 guarda raw para update Mongo
            zoho_id = str(zoho_id_raw) if zoho_id_raw is not None else None
            shopify_id = link.get("shopify_id")

            if shopify_id is None or str(shopify_id).strip() == "":
                zoho_doc = zoho_by_id.get(zoho_id)
                if not zoho_doc:
                    broken_links += 1
                    _log(f"⚠️ Sin shopify_id pero zoho_id no existe en zoho_by_id | index={i} | zoho_id={repr(zoho_id_raw)}")
                    continue

                broken_links += 1
                product_dict = self._template_str_to_dict(self.product_payload, data_dict=zoho_doc)

                # 👇 IMPORTANTE: payload Shopify requiere wrapper {"product": {...}}
                create_jobs.append({
                    "zoho_item_id": zoho_id_raw,
                    "payload": {"product": product_dict},
                })
                continue

        if not create_jobs:
            _log("ℹ️ No hay productos por crear.")
            return []

        _log(f"🧩 create_jobs → {len(create_jobs)} (links sin shopify_id) | broken_links={broken_links}")

        # ✅ crea en Shopify (POST) usando tu función existente ya extendida
        results = self.send_workload_to_shopify_api(create_jobs, store, logger=logger)

        # ✅ inyecta shopify_id en items_per_store + upsert producto en store.products
        updated = 0
        for r in results:
            if not r.get("ok") or not r.get("created"):
                continue

            zoho_item_id_raw = r.get("zoho_item_id")
            shopify_new_id = r.get("product_id")
            created_product = r.get("product", {})

            if not zoho_item_id_raw or not shopify_new_id:
                continue

            # 1) linkeo en Zoho_Inventory.items_per_store (array items)
            client["Zoho_Inventory"]["items_per_store"].update_one(
                {"store": store, "items.item_id": zoho_item_id_raw},
                {"$set": {
                    "items.$.shopify_id": shopify_new_id,
                    "items.$.linked_at": datetime.utcnow(),
                }}
            )

            # 2) guardar el producto creado en la colección store.products
            client[store]["products"].update_one(
                {"id": shopify_new_id},
                {"$set": created_product},
                upsert=True
            )

            updated += 1
            _log(f"✅ Link actualizado: zoho_item_id={repr(zoho_item_id_raw)} → shopify_id={shopify_new_id}")

        _log(f"🎉 Creación terminada. Links actualizados: {updated}/{len(results)}")
        return results
    
    def run_inventory_sync(self, store: str, logger=None):
        def _log(msg: str):
            if callable(logger):
                logger(str(msg))
            else:
                print(str(msg))

        _log(f"📦 Sincronizando inventario para {store}...")

        # --- location_id mapping (simplified)
        location_map = {
            "managed_store_one": 108620087615,
            "managed_store_two": 80329703512,
        }
        location_id = location_map.get(store)
        if location_id is None:
            raise ValueError(
                f"No tengo location_id para store='{store}'. "
                f"Stores válidos: {list(location_map.keys())}"
            )

        # --- resolve Shopify config (based on YOUR YAML)
        if not isinstance(self.data, dict):
            raise TypeError(f"self.data debe ser dict, recibí: {type(self.data)}")

        store_conf = self.data.get(store)
        if not isinstance(store_conf, dict):
            raise KeyError(
                f"No encontré config dict para store='{store}' en self.data. "
                f"Keys disponibles: {list(self.data.keys())}"
            )

        token = store_conf.get("access_token")
        api_version = store_conf.get("api_version", "2024-10")
        store_name = store_conf.get("store_name")
        if not token or not store_name:
            raise ValueError(
                f"Config incompleta para store='{store}'. Requerido: access_token, store_name. "
                f"Recibí keys: {list(store_conf.keys())}"
            )

        base = store_name.strip()
        if not base.startswith("http"):
            base = "https://" + base
        base = base.rstrip("/")

        endpoint_set = f"{base}/admin/api/{api_version}/inventory_levels/set.json"

        headers = store_conf.get("headers")
        if not isinstance(headers, dict) or not headers:
            headers = {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": token,
            }
        else:
            headers = dict(headers)
            headers["X-Shopify-Access-Token"] = token
            headers.setdefault("Content-Type", "application/json")

        # --- Mongo
        mongo_db_url = self.data["non_sql_database"]["url"]
        client = MongoClient(mongo_db_url)

        zoho_db = client["Zoho_Inventory"]
        store_db = client[store]

        col_items_per_store = zoho_db["items_per_store"]
        col_zoho_items = zoho_db["items"]
        col_shopify_products = store_db["products"]
        col_inventory_levels = store_db["inventory_levels"]
        now_iso = datetime.now(timezone.utc).isoformat()
        # =========================
        # 1) Getting zoho item_id - shopify_id pair
        # =========================
        _log("🔎 Step: Getting zoho item_id - shopify_id pair")

        link_doc = col_items_per_store.find_one({"store": store}, {"items": 1})
        if not link_doc or not link_doc.get("items"):
            _log(f"⚠️ No encontré Zoho_Inventory.items_per_store para store='{store}' o está vacío.")
            return

        item_to_shopify = {}
        invalid_links = 0

        for it in link_doc["items"]:
            item_id = it.get("item_id")
            shopify_id = it.get("shopify_id")

            if item_id is None or shopify_id is None:
                invalid_links += 1
                continue

            item_id = str(item_id)

            # shopify_id might come like {"$numberLong": "..."}
            if isinstance(shopify_id, dict) and "$numberLong" in shopify_id:
                try:
                    shopify_id = int(shopify_id["$numberLong"])
                except Exception:
                    invalid_links += 1
                    continue
            else:
                try:
                    shopify_id = int(shopify_id)
                except Exception:
                    invalid_links += 1
                    continue

            item_to_shopify[item_id] = shopify_id

        _log(f"   ✅ pairs_ok={len(item_to_shopify)} invalid_links={invalid_links}")

        if not item_to_shopify:
            _log("⚠️ items_per_store existe pero no pude extraer item_id/shopify_id válidos.")
            return

        item_ids = list(item_to_shopify.keys())
        shopify_product_ids = list(set(item_to_shopify.values()))

        # =========================
        # 2) Getting zoho items for listed shopify items at {store}
        # =========================
        _log(f"🔎 Step: Getting zoho items for listed shopify items at {store}")

        item_to_stock = {}
        zoho_found = 0
        for doc in col_zoho_items.find(
            {"item_id": {"$in": item_ids}},
            {"item_id": 1, "actual_available_stock": 1, "available_stock": 1},
        ):
            zoho_found += 1
            iid = str(doc.get("item_id"))
            stock = doc.get("actual_available_stock", None)
            if stock is None:
                stock = doc.get("available_stock", 0)

            try:
                item_to_stock[iid] = int(stock)
            except Exception:
                item_to_stock[iid] = 0

        missing_zoho_items = [iid for iid in item_ids if iid not in item_to_stock]
        _log(f"   ✅ zoho_docs_found={zoho_found} missing_zoho_items={len(missing_zoho_items)}")
        if missing_zoho_items:
            _log(f"   ⚠️ sample missing item_ids: {missing_zoho_items[:5]}")

        # =========================
        # 3) Getting shopify products (to obtain inventory_item_id)
        # =========================
        _log(f"🔎 Step: Getting shopify products for the listed shopify items at {store}")

        pid_to_inv_item = {}
        products_found = 0
        products_missing_variant_inv = 0

        for p in col_shopify_products.find(
            {"id": {"$in": shopify_product_ids}},
            {"id": 1, "variants.inventory_item_id": 1},
        ):
            products_found += 1

            pid = p.get("id")
            try:
                pid = int(pid) if not (isinstance(pid, dict) and "$numberLong" in pid) else int(pid["$numberLong"])
            except Exception:
                continue

            variants = p.get("variants") or []
            if not variants or not isinstance(variants, list):
                products_missing_variant_inv += 1
                continue

            inv_item_id = variants[0].get("inventory_item_id")
            if inv_item_id is None:
                products_missing_variant_inv += 1
                continue

            if isinstance(inv_item_id, dict) and "$numberLong" in inv_item_id:
                try:
                    inv_item_id = int(inv_item_id["$numberLong"])
                except Exception:
                    products_missing_variant_inv += 1
                    continue
            else:
                try:
                    inv_item_id = int(inv_item_id)
                except Exception:
                    products_missing_variant_inv += 1
                    continue

            pid_to_inv_item[pid] = inv_item_id

        missing_products = [pid for pid in shopify_product_ids if pid not in pid_to_inv_item]
        _log(f"   ✅ shopify_products_found={products_found} inv_item_extracted={len(pid_to_inv_item)} missing_inv_item={len(missing_products)}")
        if missing_products:
            _log(f"   ⚠️ sample missing shopify product ids: {missing_products[:5]}")

        # =========================
        # 4) Building templates
        # =========================
        _log("🔎 Step: Building templates")

        desired = {}  # inventory_item_id -> desired_qty
        missing_inv_item_links = 0
        for item_id, pid in item_to_shopify.items():
            inv_item_id = pid_to_inv_item.get(pid)
            if not inv_item_id:
                missing_inv_item_links += 1
                continue
            qty = item_to_stock.get(item_id, 0)
            desired[inv_item_id] = int(qty)

        _log(f"   ✅ templates_built={len(desired)} missing_inv_item_links={missing_inv_item_links}")
        if desired:
            # show 3 examples
            sample = list(desired.items())[:3]
            _log(f"   🧪 sample templates (inv_item_id -> qty): {sample}")

        if not desired:
            _log("⚠️ No hay templates que construir (desired vacío).")
            return

        inv_item_ids = list(desired.keys())

        # =========================
        # 5) Getting shopify inventory_levels for the listed shopify items at {store}
        # =========================
        _log(f"🔎 Step: Getting shopify inventory_levels for the listed shopify items at {store} (Mongo cache)")

        current = {}  # inventory_item_id -> available
        levels_found = 0

        for lvl in col_inventory_levels.find(
            {"location_id": int(location_id), "inventory_item_id": {"$in": inv_item_ids}},
            {"inventory_item_id": 1, "location_id": 1, "available": 1},
        ):
            levels_found += 1
            inv_item_id = lvl.get("inventory_item_id")

            if isinstance(inv_item_id, dict) and "$numberLong" in inv_item_id:
                try:
                    inv_item_id = int(inv_item_id["$numberLong"])
                except Exception:
                    continue
            else:
                try:
                    inv_item_id = int(inv_item_id)
                except Exception:
                    continue

            try:
                current[inv_item_id] = int(lvl.get("available", 0))
            except Exception:
                current[inv_item_id] = 0

        _log(f"   ✅ inventory_levels_found={levels_found} current_indexed={len(current)}")
        if levels_found == 0:
            _log("   ⚠️ Ojo: tu cache inventory_levels está vacío para ese location_id. Eso haría que TODO parezca 'to_create'.")

        # =========================
        # 6) Comparing both data + Building inventory_level-like payloads
        # =========================
        _log("🔎 Step: Comparing both data")

        now_iso = datetime.now(timezone.utc).isoformat()

        to_create = []
        to_update = []
        no_change = []

        for inv_item_id, desired_qty in desired.items():
            cur_qty = current.get(inv_item_id)  # Shopify-reported (from Mongo cache)

            payload = {
                "inventory_item_id": int(inv_item_id),
                "location_id": int(location_id),
                "available": int(desired_qty),  # Zoho desired
            }

            if cur_qty is None:
                # Shopify inventory level not found (in your cache) for this location
                to_create.append(payload)
            else:
                # Compare Shopify vs Zoho
                if int(cur_qty) == int(desired_qty):
                    no_change.append(payload)
                else:
                    to_update.append(payload)

        _log(
            f"   ✅ compare_results: "
            f"to_create={len(to_create)} "
            f"to_update={len(to_update)} "
            f"no_change={len(no_change)}"
        )

        if to_create:
            _log(f"   🧪 sample to_create payloads: {to_create[:2]}")
        if to_update:
            _log(f"   🧪 sample to_update payloads: {to_update[:2]}")
        if no_change:
            _log(f"   🧪 sample no_change payloads: {no_change[:2]}")
        pprint(to_update)
        # =========================
        # Send to Shopify GraphQL
        # =========================
        graphql_endpoint = f"{base}/admin/api/{api_version}/graphql.json"

        mutation_set = """
        mutation InventorySet($input: InventorySetQuantitiesInput!) {
        inventorySetQuantities(input: $input) {
            inventoryAdjustmentGroup {
            reason
            changes { name delta }
            }
            userErrors { field message }
        }
        }
        """

        # We'll verify "available" after each batch
        # NOTE: quantities(names:["available"]) returns the current value at that location.  [oai_citation:1‡Shopify](https://shopify.dev/docs/api/admin-graphql/latest/queries/inventoryLevel)
        BATCH_SIZE = 50
        location_gid = f"gid://shopify/Location/{int(location_id)}"

        ok_count = 0
        mismatch_count = 0
        error_batches = 0

        for i in range(0, len(to_update), BATCH_SIZE):
            batch = to_update[i:i + BATCH_SIZE]

            # --- 1) Send mutation
            quantities = [
                {
                    "inventoryItemId": f"gid://shopify/InventoryItem/{int(d['inventory_item_id'])}",
                    "locationId": location_gid,
                    "quantity": int(d["available"]),
                }
                for d in batch
            ]

            variables = {
                "input": {
                    "name": "available",
                    "reason": "correction",
                    "ignoreCompareQuantity": True,
                    "quantities": quantities,
                }
            }

            resp = requests.post(
                graphql_endpoint,
                headers=headers,
                json={"query": mutation_set, "variables": variables},
                timeout=60
            )
            resp.raise_for_status()
            j = resp.json()

            user_errors = (
                j.get("data", {})
                .get("inventorySetQuantities", {})
                .get("userErrors", [])
            )
            if user_errors:
                error_batches += 1
                _log(f"❌ Set batch {(i//BATCH_SIZE)+1}: userErrors={user_errors}")
                # You can continue or stop; I continue so you see all errors
                continue

            _log(f"✅ Set batch {(i//BATCH_SIZE)+1}: sent {len(batch)} quantities")

            # --- 2) Verify by querying inventoryItem.inventoryLevel(locationId).  [oai_citation:2‡Shopify](https://shopify.dev/docs/api/admin-graphql/latest/queries/inventoryItem?utm_source=chatgpt.com)
            # Build a single query with aliases i0, i1, ... so we verify the whole batch in one call.
            desired_by_gid = {f"gid://shopify/InventoryItem/{int(d['inventory_item_id'])}": int(d["available"]) for d in batch}

            # We’ll allow a tiny retry in case of short propagation delay
            verified = False
            last_result = None

            for attempt in range(1, 4):
                parts = []
                for idx, inv_gid in enumerate(desired_by_gid.keys()):
                    parts.append(f'''
                    i{idx}: inventoryItem(id: "{inv_gid}") {{
                        id
                        inventoryLevel(locationId: "{location_gid}") {{
                        updatedAt
                        quantities(names: ["available"]) {{
                            name
                            quantity
                        }}
                        }}
                    }}
                    ''')

                query_verify = "query VerifyBatch {\n" + "\n".join(parts) + "\n}"

                vresp = requests.post(
                    graphql_endpoint,
                    headers=headers,
                    json={"query": query_verify},
                    timeout=60
                )
                vresp.raise_for_status()
                vj = vresp.json()
                last_result = vj

                data = vj.get("data", {}) if isinstance(vj, dict) else {}
                # If data is empty, retry
                if not data:
                    time.sleep(1 * attempt)
                    continue

                # Compare results
                mismatches = []
                null_levels = []
                matches = 0

                for idx, inv_gid in enumerate(desired_by_gid.keys()):
                    node = data.get(f"i{idx}")
                    if not node:
                        mismatches.append((inv_gid, "missing_node", desired_by_gid[inv_gid]))
                        continue

                    lvl = node.get("inventoryLevel")
                    if lvl is None:
                        # This usually means not stocked/activated at that location -> you may need inventoryActivate.  [oai_citation:3‡Shopify](https://shopify.dev/docs/api/admin-graphql/latest/objects/InventoryLevel)
                        null_levels.append(inv_gid)
                        continue

                    q_list = lvl.get("quantities") or []
                    # find "available"
                    got = None
                    for q in q_list:
                        if q.get("name") == "available":
                            got = q.get("quantity")
                            break

                    want = desired_by_gid[inv_gid]
                    if got is None:
                        mismatches.append((inv_gid, "missing_available", want))
                    elif int(got) == int(want):
                        matches += 1
                    else:
                        mismatches.append((inv_gid, int(got), want))

                if null_levels:
                    _log(f"⚠️ Verify batch {(i//BATCH_SIZE)+1}: {len(null_levels)} items returned inventoryLevel=null (likely not activated at this location).")

                if mismatches:
                    # retry a bit (sometimes values lag for a second)
                    time.sleep(1 * attempt)
                    continue

                # all good
                verified = True
                ok_count += matches
                _log(f"✅ Verify batch {(i//BATCH_SIZE)+1}: ok={matches}/{len(batch)}")
                break

            if not verified:
                # On last attempt, report mismatches (small sample)
                mismatch_count += len(batch)
                _log(f"❌ Verify batch {(i//BATCH_SIZE)+1}: mismatches remain after retries. Sample:")
                # Print at most 5 mismatches so logs are readable
                try:
                    # Recompute mismatches from last_result for printing (quick & safe)
                    data = (last_result or {}).get("data", {})
                    shown = 0
                    for idx, inv_gid in enumerate(desired_by_gid.keys()):
                        if shown >= 5:
                            break
                        node = data.get(f"i{idx}", {})
                        lvl = node.get("inventoryLevel")
                        want = desired_by_gid[inv_gid]
                        if lvl is None:
                            _log(f"   - {inv_gid}: inventoryLevel=null, want={want}")
                            shown += 1
                            continue
                        got = None
                        for q in (lvl.get("quantities") or []):
                            if q.get("name") == "available":
                                got = q.get("quantity")
                                break
                        _log(f"   - {inv_gid}: got={got} want={want}")
                        shown += 1
                except Exception:
                    pass

        _log(f"🏁 Done: verified_ok≈{ok_count}, verify_failed_batches={error_batches}, verify_failed_items≈{mismatch_count}")    
        
    def run_product_sync(self, store: str, logger=None):
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

        products_to_create = self.shopify_create_items(store, logger=logger)
        
        products_to_update = self.shopify_update_items(store, logger=logger)    
            
        if products_to_update:
            self.send_workload_to_shopify_api(products_to_update, store, logger=logger)
        else:
            print("ℹ️ No hay actualizaciones por enviar.")
            


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
        #app.run_product_sync(store)