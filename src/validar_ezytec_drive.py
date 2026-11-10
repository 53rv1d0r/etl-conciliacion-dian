import os
import io
import psycopg2
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "postgres_db"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "db_etl_recaudo"),
    "user": os.getenv("DB_USER", "cbadmin"),
    "password": os.getenv("DB_PASSWORD", "")
}

SERVICE_ACCOUNT_FILE = '/app/service_account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
FOLDER_ID = '1cF5OJNZTZBfmZME2GTXSVK_cYwskzMBl'

def get_drive_service():
    """Autentica y retorna el servicio de Google Drive con la Cuenta de Servicio"""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

def obtener_ezytec_db():
    """Obtiene las facturas de Ezytec registradas en PostgreSQL para octubre de 2026"""
    print("Conectando a PostgreSQL para extraer registros de Ezytec...")
    query = """
        SELECT prefix, number, fcreacion, total, cufe
        FROM staging.stg_ezytec
        WHERE DATE(fcreacion) BETWEEN '2026-10-01' AND '2026-10-31';
    """
    conn = psycopg2.connect(**DB_CONFIG)
    df_db = pd.read_sql(query, conn)
    conn.close()
    print(f" -> Registros de Ezytec en BD (Octubre): {len(df_db)}")
    return df_db

def listar_archivos_carpeta(service, folder_id):
    """Lista todos los archivos de la carpeta manejando paginación"""
    print("Escaneando todos los archivos de la carpeta en Google Drive...")
    files = []
    page_token = None
    while True:
        query = f"'{folder_id}' in parents and trashed = false"
        response = service.files().list(
            q=query,
            pageSize=100,
            pageToken=page_token,
            fields="nextPageToken, files(id, name, mimeType)"
        ).execute()
        files.extend(response.get('files', []))
        page_token = response.get('nextPageToken', None)
        if not page_token:
            break
    print(f" -> Total de archivos encontrados en la carpeta: {len(files)}")
    return files

def descargar_y_leer_csv(service, file_id, file_name):
    """Descarga un archivo CSV desde Google Drive a memoria"""
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        
        try:
            df = pd.read_csv(fh, dtype=str, encoding='utf-8')
        except UnicodeDecodeError:
            fh.seek(0)
            df = pd.read_csv(fh, dtype=str, encoding='latin-1')
        return df
    except Exception as e:
        print(f"Error procesando archivo {file_name}: {e}")
        return pd.DataFrame()

def main():
    print("=== INICIANDO AUDITORÍA CON MONTO Y CUFE - EZYTEC OCTUBRE 2026 ===")
    
    # 1. Extraer datos de PostgreSQL (incluyendo total)
    df_db = obtener_ezytec_db()
    
    # 2. Conectar a Google Drive y listar archivos
    drive_service = get_drive_service()
    archivos = listar_archivos_carpeta(drive_service, FOLDER_ID)
    
    if not archivos:
        print("¡La carpeta en Google Drive está vacía o no se tienen permisos!")
        return

    # 3. Escanear y procesar cada CSV
    lista_dfs_drive = []
    for archivo in archivos:
        nombre = archivo['name']
        if nombre.lower().endswith('.csv'):
            print(f" Leyendo contenido de: {nombre}...")
            df_csv = descargar_y_leer_csv(drive_service, archivo['id'], nombre)
            if not df_csv.empty and 'fcreacion' in df_csv.columns and 'total' in df_csv.columns:
                df_csv['archivo_origen'] = nombre
                lista_dfs_drive.append(df_csv)

    if not lista_dfs_drive:
        print("No se encontraron archivos CSV válidos con columnas 'fcreacion' y 'total'.")
        return

    df_drive_total = pd.concat(lista_dfs_drive, ignore_index=True)
    print(f"Total de filas leídas en Drive: {len(df_drive_total)}")

    # 4. Normalizar fechas y filtrar octubre de 2026
    df_drive_total['fcreacion_dt'] = pd.to_datetime(df_drive_total['fcreacion'], format='%d/%m/%Y', errors='coerce')
    mask_octubre = (df_drive_total['fcreacion_dt'] >= '2026-10-01') & (df_drive_total['fcreacion_dt'] <= '2026-10-31')
    df_drive_oct = df_drive_total[mask_octubre].copy()
    print(f"Registros en Drive con fecha de octubre: {len(df_drive_oct)}")

    # Asegurar tipo numérico en montos para sumar bien
    df_drive_oct['total_num'] = pd.to_numeric(df_drive_oct['total'], errors='coerce').fillna(0)
    df_db['total_num'] = pd.to_numeric(df_db['total'], errors='coerce').fillna(0)

    # 5. Normalizar nombres y preparar llaves de cruce
    df_drive_oct = df_drive_oct.rename(columns={'total_num': 'total_drive'})
    df_db = df_db.rename(columns={'total_num': 'total_db'})

    df_db['key_factura'] = df_db['prefix'].astype(str).str.strip() + '-' + df_db['number'].astype(str).str.strip()
    df_drive_oct['key_factura'] = df_drive_oct['prefix'].astype(str).str.strip() + '-' + df_drive_oct['number'].astype(str).str.strip()

    # Cruce con PostgreSQL usando Prefijo + Número y especificando sufijos limpios
    df_cruce = pd.merge(
        df_drive_oct,
        df_db[['key_factura', 'total_db', 'cufe']],
        on='key_factura',
        how='outer',
        indicator=True,
        suffixes=('_drive', '_db')
    )

    # Columna unificada para tener el monto sin importar de qué lado venga
    df_cruce['monto_final'] = df_cruce['total_drive'].fillna(df_cruce['total_db'])

    # 6. Clasificar estado y diferencias de dinero
    def clasificar_estado(row):
        if row['_merge'] == 'left_only':
            return 'FALTA_EN_DB (Dinero no contabilizado en staging)'
        elif row['_merge'] == 'right_only':
            return 'FALTA_EN_DRIVE (En DB pero ausente en CSVs de Drive)'
        else:
            monto_d = row['total_drive'] if pd.notna(row['total_drive']) else 0
            monto_b = row['total_db'] if pd.notna(row['total_db']) else 0
            if abs(monto_d - monto_b) > 1.0: # Tolerancia de 1 peso por redondeos
                return 'DIFERENCIA_MONTO'
            
            # Verificamos el CUFE viniendo de Drive o de la Base de Datos
            cufe_val = row.get('cufe_drive') if pd.notna(row.get('cufe_drive')) else row.get('cufe_db')
            has_cufe = pd.notna(cufe_val) and str(cufe_val).strip() != ''
            if not has_cufe:
                return 'PRESENTE_SIN_CUFE'
            else:
                return 'CONCILIADO_OK'

    df_cruce['estado_auditoria'] = df_cruce.apply(clasificar_estado, axis=1)

    # 7. Resumen financiero por categoría
    print("\n--- RESUMEN FINANCIERO DE LA AUDITORÍA ---")
    resumen = df_cruce.groupby('estado_auditoria').agg(
        cantidad_facturas=('key_factura', 'count'),
        monto_total=('monto_final', lambda x: x.sum(skipna=True))
    ).reset_index()
    print(resumen.to_string(index=False))

    # 8. Exportar reporte detallado
    os.makedirs('data', exist_ok=True)
    output_filename = "data/auditoria_ezytec_con_montos.csv"
    df_cruce.to_csv(output_filename, index=False, encoding='utf-8-sig')
    print(f"\nReporte detallado guardado en: {output_filename}")

if __name__ == "__main__":
    main()