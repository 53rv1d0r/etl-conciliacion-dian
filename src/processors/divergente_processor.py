import os
import sys
import hashlib
import pandas as pd
from datetime import datetime

# Ajustar path para importar módulos desde src/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import obtener_conexion
from gdrive import listar_archivos_en_subcarpeta, descargar_archivo

def parsear_fecha_segura(valor):
    """
    Parsea de forma segura cualquier formato de fecha y descarta basura.
    Devuelve un string en formato 'YYYY-MM-DD' o None si es inválido.
    """
    if pd.isna(valor) or not valor:
        return None
    
    s = str(valor).strip()
    if len(s) < 6 or not any(char.isdigit() for char in s):
        return None
    
    formatos = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%y', '%d/%m/%y', '%m/%d/%Y', '%Y/%m/%d']
    for fmt in formatos:
        try:
            dt = datetime.strptime(s, fmt)
            if 2020 <= dt.year <= 2030:
                return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
            
    return None

def parsear_monto_seguro(valor):
    """
    Limpia y convierte montos (total, iva, ica, ic) de manera segura.
    """
    if pd.isna(valor) or valor == '':
        return 0.0
    try:
        s = str(valor).strip().replace('$', '').replace(' ', '')
        if ',' in s and '.' in s:
            if s.rfind(',') > s.rfind('.'):
                s = s.replace('.', '').replace(',', '.')
            else:
                s = s.replace(',', '')
        elif ',' in s:
            s = s.replace(',', '.')
        return float(s)
    except (ValueError, TypeError):
        return 0.0

def calcular_hash_archivo(file_path):
    """Calcula el hash MD5 de un archivo local para control de integridad."""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

def procesar_divergente(folder_id_divergente):
    print("🚀 [ETL DIVERGENTE] Iniciando procesamiento de archivos desde Google Drive con Parseo Robusto...")
    
    archivos_drive = listar_archivos_en_subcarpeta(folder_id_divergente)
    if not archivos_drive:
        print("❌ No se encontraron archivos en la carpeta de Drive para Divergente.")
        return

    conn = obtener_conexion()
    cursor = conn.cursor()

    # Consultar archivos ya procesados con éxito
    cursor.execute(
        """
        SELECT archivo_nombre 
        FROM staging.control_archivos 
        WHERE tecnologia = 'Divergente' AND estado = 'EXITOSO'
        """
    )
    procesados_db = {row[0] for row in cursor.fetchall()}

    archivos_nuevos = [f for f in archivos_drive if f['name'] not in procesados_db]
    print(f"📊 Total archivos en Drive: {len(archivos_drive)} | Ya procesados en DB: {len(procesados_db)} | Pendientes: {len(archivos_nuevos)}")

    if not archivos_nuevos:
        print("✅ No hay archivos nuevos de Divergente pendientes por procesar.")
        cursor.close()
        conn.close()
        return

    for file_info in archivos_nuevos:
        nombre_archivo = file_info['name']
        file_id = file_info['id']
        local_path = f"/tmp/{nombre_archivo}"

        print(f"\n📥 [PROCESANDO] Descargando {nombre_archivo}...")

        try:
            descargar_archivo(file_id, local_path)
            df = pd.read_csv(local_path)
            archivo_hash = calcular_hash_archivo(local_path)
            registros_insertados = 0
            registros_omitidos = 0
            registros_cuarentena = 0

            for _, row in df.iterrows():
                prefijo = str(row.get('Prefijo', '')).strip()
                folio = str(row.get('Folio', '')).strip()
                
                # Fechas robustas y estandarizadas
                fecha_emision = parsear_fecha_segura(row.get('Fecha Emisión'))
                fecha_recepcion = parsear_fecha_segura(row.get('Fecha Recepción'))
                
                total_val = parsear_monto_seguro(row.get('Total'))
                iva_val = parsear_monto_seguro(row.get('IVA'))
                ica_val = parsear_monto_seguro(row.get('ICA'))
                ic_val = parsear_monto_seguro(row.get('IC'))

                if not folio or folio == 'nan' or total_val < 0 or not fecha_emision:
                    # Enviar a Cuarentena por registro defectuoso
                    motivo = f"Registro defectuoso en Divergente: Folio inválido, Total corrupto o Fecha de emisión nula/inválida (Valor: {row.get('Fecha Emisión')})"
                    cursor.execute(
                        """
                        INSERT INTO staging.cuarentena_recaudo 
                        (tecnologia, archivo_origen, payload_fila, motivo_rechazo)
                        VALUES (%s, %s, %s, %s)
                        """,
                        ('Divergente', nombre_archivo, str(row.to_dict()), motivo)
                    )
                    registros_cuarentena += 1
                    continue

                # Inserción con control de duplicados en llave (prefijo, folio, fecha_emision)
                cursor.execute(
                    """
                    INSERT INTO staging.stg_divergente 
                    (
                        archivo_origen, tipo_documento, cufe_cude, folio, prefijo, 
                        fecha_emision, fecha_recepcion, nit_emisor, nombre_emisor, 
                        nit_receptor, nombre_receptor, iva, ica, ic, total, 
                        estado, grupo, ceco, parqueadero, operador
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (prefijo, folio, fecha_emision) DO NOTHING
                    RETURNING 1;
                    """,
                    (
                        nombre_archivo,
                        str(row.get('Tipo de documento', '')).strip(),
                        str(row.get('CUFE/CUDE', '')).strip(),
                        folio,
                        prefijo,
                        fecha_emision,
                        fecha_recepcion,
                        str(row.get('NIT Emisor')).strip() if pd.notna(row.get('NIT Emisor')) else None,
                        str(row.get('Nombre Emisor', '')).strip(),
                        str(row.get('NIT Receptor', '')).strip(),
                        str(row.get('Nombre Receptor', '')).strip(),
                        iva_val,
                        ica_val,
                        ic_val,
                        total_val,
                        str(row.get('Estado', '')).strip(),
                        str(row.get('Grupo')).strip() if pd.notna(row.get('Grupo')) else None,
                        str(row.get('CeCo')).strip() if pd.notna(row.get('CeCo')) else None,
                        str(row.get('Parqueadero', '')).strip(),
                        str(row.get('Operador', '')).strip()
                    )
                )
                if cursor.fetchone():
                    registros_insertados += 1
                else:
                    registros_omitidos += 1

            cursor.execute(
                """
                INSERT INTO staging.control_archivos 
                (tecnologia, archivo_nombre, registros_cargados, registros_omitidos, archivo_hash, estado)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (archivo_hash) DO NOTHING;
                """,
                ('Divergente', nombre_archivo, registros_insertados, registros_omitidos + registros_cuarentena, archivo_hash, 'EXITOSO')
            )
            
            conn.commit()
            print(f"✅ [EXITO] {nombre_archivo}: {registros_insertados} insertados | {registros_omitidos} duplicados | {registros_cuarentena} en cuarentena.")

        except Exception as e:
            conn.rollback()
            print(f"❌ [ERROR] Falló el procesamiento global de {nombre_archivo}: {e}")
            try:
                cursor.execute(
                    """
                    INSERT INTO staging.control_archivos 
                    (tecnologia, archivo_nombre, registros_cargados, registros_omitidos, archivo_hash, estado)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    ('Divergente', nombre_archivo, 0, 0, 'ERROR', 'FALLIDO')
                )
                conn.commit()
            except:
                pass

        finally:
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except:
                    pass

    cursor.close()
    conn.close()
    print("\n🎉 [ETL DIVERGENTE] Proceso finalizado exitosamente.")

if __name__ == "__main__":
    FOLDER_DIVERGENTE_ID = os.getenv("GDRIVE_DIVERGENTE_FOLDER_ID", "1oJjm2Kwd0NhiNQes7xrmviJVpbT_FTpu")
    procesar_divergente(FOLDER_DIVERGENTE_ID)