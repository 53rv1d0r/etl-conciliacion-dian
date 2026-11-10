import time
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
import io
from googleapiclient.http import MediaIoBaseDownload

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def obtener_servicio_drive():
    """
    Crea y retorna un cliente autorizado para interactuar con la API de Google Drive.
    """
    creds_file = os.getenv("GDRIVE_SERVICE_ACCOUNT_FILE", "service_account.json")
    try:
        creds = service_account.Credentials.from_service_account_file(
            creds_file, scopes=SCOPES
        )
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"❌ Error al autenticar con Google Drive: {e}")
        return None

def listar_carpetas_tecnologia(folder_id):
    """
    Busca específicamente las carpetas de tecnología dentro de la carpeta principal.
    """
    service = obtener_servicio_drive()
    if not service:
        return []

    try:
        query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(
            q=query,
            pageSize=10,
            fields="files(id, name)"
        ).execute()
        return results.get('files', [])
    except Exception as e:
        print(f"❌ Error al listar carpetas de tecnología: {e}")
        return []

def listar_archivos_en_subcarpeta(folder_id):
    """
    Lista todos los archivos dentro de una subcarpeta de Google Drive,
    manejando paginación completa (nextPageToken) para superar el límite de 100 archivos.
    """
    service = obtener_servicio_drive()
    if not service:
        print("❌ Error: No se pudo obtener el servicio de Google Drive para listar archivos.")
        return []

    query = f"'{folder_id}' in parents and trashed = false"
    archivos = []
    page_token = None

    try:
        while True:
            response = service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name, md5Checksum)',
                pageSize=1000,  # Máximo por página permitido por Google
                pageToken=page_token
            ).execute()
            
            archivos.extend(response.get('files', []))
            
            # Obtener token para la siguiente página, si existe
            page_token = response.get('nextPageToken', None)
            if not page_token:
                break
                
        print(f"📁 [Google Drive] Total archivos encontrados en carpeta {folder_id}: {len(archivos)}")
        return archivos

    except Exception as e:
        print(f"❌ [Error Google Drive] No se pudieron listar los archivos de la carpeta {folder_id}: {e}")
        return []

def descargar_archivo(file_id, ruta_destino, max_intentos=3, espera_inicial=2):
    """
    Descarga un archivo de Google Drive usando su file_id a una ruta local,
    incorporando reintentos automáticos ante intermitencias de red.
    """
    service = obtener_servicio_drive()
    if not service:
        print("❌ Error: No se pudo obtener el servicio de Google Drive para la descarga.")
        raise Exception("No se pudo obtener el servicio de Google Drive")

    intentos_realizados = 0
    espera = espera_inicial

    while intentos_realizados < max_intentos:
        try:
            intentos_realizados += 1
            request = service.files().get_media(fileId=file_id)
            fh = io.FileIO(ruta_destino, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                
            print(f"📥 Archivo descargado exitosamente en: {ruta_destino}")
            return True

        except Exception as e:
            # Limpiamos el archivo parcial si la descarga quedó a medias
            if os.path.exists(ruta_destino):
                try:
                    os.remove(ruta_destino)
                except:
                    pass

            if intentos_realizados == max_intentos:
                print(f"❌ Error al descargar el archivo {file_id} tras {max_intentos} intentos: {e}")
                raise e
            
            print(f"⚠️ [GDRIVE] Intermitencia de red (Intento {intentos_realizados}/{max_intentos}) para ID {file_id}. Reintentando en {espera}s... [Error: {e}]")
            time.sleep(espera)
            espera *= 2  # Incremento exponencial del tiempo de espera (2s, 4s, 8s...)