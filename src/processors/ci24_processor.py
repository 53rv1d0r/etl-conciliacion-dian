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
    Limpia y convierte montos (total, subtotal, iva) de manera segura.
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
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

def procesar_ci24(folder_id_ci24):
    print("🚀 [ETL CI24] Iniciando procesamiento adaptativo con Parseo Robusto y Cuarentena...")
    
    archivos_drive = listar_archivos_en_subcarpeta(folder_id_ci24)
    if not archivos_drive:
        print("❌ No se encontraron archivos en la carpeta de Drive para CI24.")
        return

    conn = obtener_conexion()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT archivo_nombre 
        FROM staging.control_archivos 
        WHERE tecnologia = 'CI24' AND estado = 'EXITOSO'
        """
    )
    procesados_db = {row[0] for row in cursor.fetchall()}

    archivos_nuevos = [f for f in archivos_drive if f['name'] not in procesados_db]
    print(f"📊 Total archivos en Drive: {len(archivos_drive)} | Ya procesados en DB: {len(procesados_db)} | Pendientes: {len(archivos_nuevos)}")

    if not archivos_nuevos:
        print("✅ No hay archivos nuevos de CI24 pendientes por procesar.")
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
                dispositivo = str(row.get('Dispositivo', '')).strip()
                
                # 1. FILTRAR ENCABEZADOS Y TOTALES BASURA EN LAS PRIMERAS FILAS
                if any(kw in dispositivo.lower() for kw in ['total facturado', 'total de documentos']):
                    continue
                
                raw_factura = row.get('Factura')
                if pd.isna(raw_factura) or str(raw_factura).strip() == '' or str(raw_factura).strip() == 'nan':
                    continue

                factura = str(raw_factura).replace('.0', '').strip()
                prefijo = str(row.get('Prefijo', '')).strip()
                
                # 2. RESOLVER FECHA Y HORA DINÁMICAMENTE CON PARSEO SEGURO
                fecha_cruda = None
                hora = ''
                if 'Fecha' in row and pd.notna(row.get('Fecha')):
                    fecha_cruda = row.get('Fecha')
                    hora = str(row.get('Hora', '')).strip() if pd.notna(row.get('Hora')) else ''
                elif 'Fecha y hora' in row and pd.notna(row.get('Fecha y hora')):
                    fecha_hora_str = str(row.get('Fecha y hora')).strip()
                    partes = fecha_hora_str.split(' ')
                    fecha_cruda = partes[0]
                    hora = partes[1] if len(partes) > 1 else ''

                fecha = parsear_fecha_segura(fecha_cruda)
                total_val = parsear_monto_seguro(row.get('Total'))
                subtotal_val = parsear_monto_seguro(row.get('Subtotal'))
                iva_val = parsear_monto_seguro(row.get('IVA'))

                # 3. CUARENTENA PARA REGISTROS INVÁLIDOS
                if not factura or total_val < 0 or not fecha:
                    motivo = f"Registro defectuoso CI24: Factura inválida, Total corrupto o Fecha nula/inválida (Valor fecha: {fecha_cruda})"
                    cursor.execute(
                        """
                        INSERT INTO staging.cuarentena_recaudo 
                        (tecnologia, archivo_origen, payload_fila, motivo_rechazo)
                        VALUES (%s, %s, %s, %s)
                        """,
                        ('CI24', nombre_archivo, str(row.to_dict()), motivo)
                    )
                    registros_cuarentena += 1
                    continue

                # 4. INSERCIÓN CON CONTROL DE DUPLICADOS EN LLAVE (prefijo, factura, fecha)
                cursor.execute(
                    """
                    INSERT INTO staging.stg_ci24 
                    (
                        archivo_origen, dispositivo, prefijo, factura, fecha, 
                        hora, subtotal, iva, total, nombre_completo, 
                        documento, correo, envio_dian, cufe
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (prefijo, factura, fecha) DO NOTHING
                    RETURNING 1;
                    """,
                    (
                        nombre_archivo,
                        dispositivo,
                        prefijo,
                        factura,
                        fecha,
                        hora,
                        subtotal_val,
                        iva_val,
                        total_val,
                        str(row.get('Nombre completo', '')).strip(),
                        str(row.get('Documento', '')).strip(),
                        str(row.get('Correo', '')).strip(),
                        str(row.get('Envío DIAN', row.get('Estado DIAN', ''))).strip(),
                        str(row.get('CUFE', '')).strip()
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
                ('CI24', nombre_archivo, registros_insertados, registros_omitidos + registros_cuarentena, archivo_hash, 'EXITOSO')
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
                    ('CI24', nombre_archivo, 0, 0, 'ERROR', 'FALLIDO')
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
    print("\n🎉 [ETL CI24] Proceso finalizado exitosamente.")

if __name__ == "__main__":
    FOLDER_CI24_ID = os.getenv("GDRIVE_CI24_FOLDER_ID", "1wbZBPsRML47l90fYRchizviEsGpdjDoh")
    procesar_ci24(FOLDER_CI24_ID)