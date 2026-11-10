import os
import io
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ==========================================
# CONFIGURACIÓN
# ==========================================
SERVICE_ACCOUNT_FILE = '/app/service_account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
FOLDER_ID = '14O3njJ5nse0YS51mGj9gDEZzrv-_nip8'  # Carpeta Drive Incomelec
DIAN_MASTER_PATH = 'data/dian31oct.xlsx'

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

def cargar_maestro_dian():
    print("Cargando archivo maestro DIAN (`dian31oct.xlsx`)...")
    df_dian = pd.read_excel(DIAN_MASTER_PATH, sheet_name='DIAN')
    
    # Filtrar solo Incomelec y octubre de 2026
    df_dian['Fecha Emisión'] = pd.to_datetime(df_dian['Fecha Emisión'], errors='coerce')
    mask = (df_dian['Operador'] == 'Incomelec') & \
           (df_dian['Fecha Emisión'] >= '2026-10-01') & \
           (df_dian['Fecha Emisión'] <= '2026-10-31')
    
    df_filtered = df_dian[mask].copy()
    
    # Normalizar llaves de cruce
    df_filtered['prefijo_clean'] = df_filtered['Prefijo'].astype(str).str.strip().str.upper()
    df_filtered['folio_clean'] = df_filtered['Folio'].astype(str).str.strip().str.split('.').str[0]
    df_filtered['key_factura'] = df_filtered['prefijo_clean'] + '-' + df_filtered['folio_clean']
    df_filtered['total_dian'] = pd.to_numeric(df_filtered['Total'], errors='coerce').fillna(0)
    
    print(f" -> Registros DIAN para Incomelec (Octubre): {len(df_filtered)}")
    print(f" -> Monto acumulado DIAN Incomelec: ${df_filtered['total_dian'].sum():,.2f} COP")
    return df_filtered

def listar_y_descargar_drive(service, folder_id):
    print("Escaneando archivos CSV en Google Drive (Carpeta Incomelec)...")
    files = []
    page_token = None
    while True:
        query = f"'{folder_id}' in parents and trashed = false"
        response = service.files().list(
            q=query, pageSize=100, pageToken=page_token,
            fields="nextPageToken, files(id, name)"
        ).execute()
        files.extend(response.get('files', []))
        page_token = response.get('nextPageToken', None)
        if not page_token:
            break
            
    print(f" -> Total archivos encontrados en Drive: {len(files)}")
    
    lista_dfs = []
    for archivo in files:
        nombre = archivo['name']
        if nombre.lower().endswith('.csv'):
            try:
                request = service.files().get_media(fileId=archivo['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                fh.seek(0)
                
                try:
                    df = pd.read_csv(fh, dtype=str, encoding='utf-8')
                except UnicodeDecodeError:
                    fh.seek(0)
                    df = pd.read_csv(fh, dtype=str, encoding='latin-1')
                    
                # Incomelec maneja campos como 'Pas_Num', 'Pas_VrTotal', 'Pas_fechaini' o 'FechaEntrada'
                if not df.empty:
                    df['archivo_origen'] = nombre
                    lista_dfs.append(df)
            except Exception as e:
                print(f"Error descargando {nombre}: {e}")
                
    if not lista_dfs:
        return pd.DataFrame()
        
    df_total = pd.concat(lista_dfs, ignore_index=True)
    return df_total

def main():
    print("=== INICIANDO CONCILIACIÓN PURA DRIVE vs DIAN (INCOMELEC) ===")
    
    # 1. Cargar Maestro DIAN
    df_dian = cargar_maestro_dian()
    
    # 2. Conectar y descargar CSVs de Drive
    drive_service = get_drive_service()
    df_drive = listar_y_descargar_drive(drive_service, FOLDER_ID)
    
    if df_drive.empty:
        print("No se pudieron procesar los archivos de Drive.")
        return
        
    print(f"Total filas brutas en Drive: {len(df_drive)}")
    
    # 3. Normalizar columnas específicas de Incomelec
    # Intentar obtener la fecha de emisión/creación
    col_fecha = 'Pas_fechaini' if 'Pas_fechaini' in df_drive.columns else ('FechaEntrada' if 'FechaEntrada' in df_drive.columns else 'fcreacion')
    col_total = 'Pas_VrTotal' if 'Pas_VrTotal' in df_drive.columns else 'total'
    col_cufe = 'Pas_Cufe' if 'Pas_Cufe' in df_drive.columns else 'cufe'
    
    df_drive['fecha_dt'] = pd.to_datetime(df_drive[col_fecha], format='%d/%m/%Y', errors='coerce')
    mask_oct = (df_drive['fecha_dt'] >= '2026-10-01') & (df_drive['fecha_dt'] <= '2026-10-31')
    df_drive_oct = df_drive[mask_oct].copy()
    print(f"Registros en Drive con fecha de octubre: {len(df_drive_oct)}")
    
    # Normalizar llaves de cruce en Incomelec (Pas_Num ej: 'CBA-22791' o Factura_Interna_Horus)
    if 'Pas_Num' in df_drive_oct.columns:
        df_drive_oct['key_factura'] = df_drive_oct['Pas_Num'].astype(str).str.strip().str.upper()
    else:
        df_drive_oct['key_factura'] = df_drive_oct['prefix'].astype(str).str.strip().str.upper() + '-' + df_drive_oct['number'].astype(str).str.strip()
        
    # Limpiar montos (Incomelec suele usar comas para decimales)
    df_drive_oct['total_drive'] = pd.to_numeric(
        df_drive_oct[col_total].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
        errors='coerce'
    ).fillna(0)
    
    # 4. Cruce Directo contra DIAN
    df_cruce = pd.merge(
        df_drive_oct,
        df_dian[['key_factura', 'total_dian', 'CUFE/CUDE', 'Fecha Emisión']],
        on='key_factura',
        how='outer',
        indicator=True,
        suffixes=('_drive', '_dian')
    )
    
    # 5. Clasificación forense de estados
    def clasificar(row):
        if row['_merge'] == 'left_only':
            return 'FALTA_EN_DIAN (En Drive, ausente en reporte DIAN)'
        elif row['_merge'] == 'right_only':
            return 'FALTA_EN_DRIVE (En reporte DIAN, ausente en CSVs Drive)'
        else:
            monto_d = row['total_drive']
            monto_di = row['total_dian']
            if abs(monto_d - monto_di) > 1.0:
                return 'DIFERENCIA_MONTO'
            
            cufe_d = str(row.get(col_cufe, '')).strip()
            cufe_di = str(row.get('CUFE/CUDE', '')).strip()
            if not cufe_d:
                return 'PRESENTE_SIN_CUFE_DRIVE'
            elif cufe_d.lower() != cufe_di.lower() and cufe_di != '':
                return 'DIFERENCIA_CUFE'
            else:
                return 'CONCILIADO_OK'
                
    df_cruce['estado_conciliacion'] = df_cruce.apply(clasificar, axis=1)
    df_cruce['monto_final'] = df_cruce['total_drive'].fillna(df_cruce['total_dian'])
    
    # 6. Resumen Financiero
    print("\n--- RESUMEN FINANCIERO DE CONCILIACIÓN INCOMELEC vs DIAN ---")
    resumen = df_cruce.groupby('estado_conciliacion').agg(
        cantidad_facturas=('key_factura', 'count'),
        monto_total=('monto_final', lambda x: x.sum(skipna=True))
    ).reset_index()
    print(resumen.to_string(index=False))
    
    # 7. Exportar reporte
    os.makedirs('data', exist_ok=True)
    out_file = "data/conciliacion_incomelec_vs_dian_crudo.csv"
    df_cruce.to_csv(out_file, index=False, encoding='utf-8-sig')
    print(f"\nReporte detallado guardado con éxito en: {out_file}")

if __name__ == '__main__':
    main()