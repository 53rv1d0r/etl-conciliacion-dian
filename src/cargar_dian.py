import os
import pandas as pd
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()
from database import obtener_conexion

def cargar_excel_dian():
    archivo_excel = "data/dian31oct.xlsx"  # Asegúrate de que esté en tu carpeta data/
    
    print(f"📂 Leyendo archivo Excel: {archivo_excel}...")
    df = pd.read_excel(archivo_excel, sheet_name="DIAN")
    print(f"📊 Total de registros leídos en el Excel: {len(df):,}")
    
    # Estandarizar nombres de columnas para PostgreSQL
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(' ', '_')
        .str.replace('/', '_')
        .str.replace('á', 'a')
        .str.replace('é', 'e')
        .str.replace('í', 'i')
        .str.replace('ó', 'o')
        .str.replace('ú', 'u')
    )
    
    # Limpiar formato de CUFE
    if 'cufe_cude' in df.columns:
        df['cufe_cude'] = df['cufe_cude'].astype(str).str.strip().str.lower()

    # Sanitizar valores nulos y de tipo object
    df = df.astype(object)
    df = df.where(pd.notnull(df), None)

    print("🔌 Conectando a la Base de Datos PostgreSQL...")
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    # Recrear la tabla staging.stg_dian limpia
    print("🛠️ Recreando tabla staging.stg_dian...")
    cursor.execute("DROP TABLE IF EXISTS staging.stg_dian;")
    
    cols_defs = [f'"{col}" TEXT' for col in df.columns]
    cursor.execute(f"CREATE TABLE staging.stg_dian ({', '.join(cols_defs)});")
    conn.commit()
    
    print("📥 Insertando registros en staging.stg_dian por lotes...")
    
    # Construcción robusta de tuplas limpiando NaT, nan y vacíos
    values = []
    for row in df.itertuples(index=False):
        cleaned_row = tuple(
            None if x is None or pd.isna(x) or str(x).strip().lower() in ['nan', 'nat', 'none', 'natype'] else x 
            for x in row
        )
        values.append(cleaned_row)
    
    insert_query = f"""
        INSERT INTO staging.stg_dian ({', '.join([f'"{c}"' for c in df.columns])})
        VALUES %s
    """
    
    execute_values(cursor, insert_query, values, page_size=5000)
    conn.commit()
    
    cursor.close()
    conn.close()
    print("🎉 ¡Archivo de la DIAN cargado exitosamente en staging.stg_dian!")

if __name__ == "__main__":
    cargar_excel_dian()