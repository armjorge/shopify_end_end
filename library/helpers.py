

class HELPERS:
    @staticmethod
    def dict_to_excel(data: list[dict], excel_path: str):
        """
        Convierte una lista de diccionarios en un archivo Excel.
        """
        import pandas as pd
        import os
        # --- 1) Crear DataFrame a partir de la lista de diccionarios ---
        # normalize aplana los subdiccionarios y listas
        df_dict = pd.json_normalize(data)

        # --- 2) Reemplazar saltos de línea o listas con texto plano ---
        df_dict = df_dict.applymap(
            lambda x: str(x).replace("\n", " ").replace("\r", " ") if isinstance(x, (list, dict, str)) else x
        )

        # --- 3) Construir ruta y guardar ---
        df_dict.to_excel(excel_path, index=False)
        short_path = os.path.join(*excel_path.split(os.sep)[-4:])
        print(f"\t\n✅ Archivo Excel generado en: {short_path}")