import os
import sys
import hashlib
import pandas as pd
from datetime import datetime

# Ajustar el path para permitir importar módulos desde la carpeta padre (src/)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import obtener_conexion
from gdrive import listar_archivos_en_subcarpeta, descargar_archivo

def parsear_fecha_segura(valor):
    """
    Parsea de forma segura cualquier formato de fecha y descarta basura (ej. '887', '197').
    Devuelve un string en formato 'YYYY-MM-DD' o None si es inválido.
    """
    if pd.isna(valor) or not valor:
        return None
    
    s = str(valor).strip()
    if len(s) < 6 or not any(char.isdigit() for char in s):
        return None
    
    formatos = ['%d/%m/%Y', '%m/%d/%y', '%Y-%m-%d', '%d/%m/%y', '%m/%d/%Y', '%Y/%m/%d']
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
    Limpia y convierte montos numéricos de manera segura, manejando símbolos, 
    espacios y separadores de miles/decimales.
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

def procesar_incomelec(folder_id_incomelec):
    print("🚀 [ETL INCOMELEC] Iniciando procesamiento de archivos desde Google Drive con Cuarentena y Parseo Robusto...")
    
    # 1. Obtener archivos de Drive
    archivos_drive = listar_archivos_en_subcarpeta(folder_id_incomelec)
    if not archivos_drive:
        print("❌ No se encontraron archivos en la carpeta de Drive para Incomelec.")
        return

    conn = obtener_conexion()
    cursor = conn.cursor()

    # 2. Consultar archivos ya procesados exitosamente en control_archivos
    cursor.execute(
        """
        SELECT archivo_nombre 
        FROM staging.control_archivos 
        WHERE tecnologia = 'Incomelec' AND estado = 'EXITOSO'
        """
    )
    procesados_db = {row[0] for row in cursor.fetchall()}

    archivos_nuevos = [f for f in archivos_drive if f['name'] not in procesados_db]
    print(f"📊 Total archivos en Drive: {len(archivos_drive)} | Ya procesados en DB: {len(procesados_db)} | Pendientes: {len(archivos_nuevos)}")

    if not archivos_nuevos:
        print("✅ No hay archivos nuevos de Incomelec pendientes por procesar.")
        cursor.close()
        conn.close()
        return

    # 3. Iterar y procesar cada archivo pendiente
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
            registros_duplicados = 0
            registros_cuarentena = 0

            # Validar e insertar fila por fila
            for _, row in df.iterrows():
                pas_num = str(row.get('Pas_Num', '')).strip()
                
                # Fechas robustas estandarizadas (neutraliza basura como '887')
                pas_fechaini = parsear_fecha_segura(row.get('Pas_fechaini'))
                pas_fechafin = parsear_fecha_segura(row.get('Pas_Fechafin'))
                fecha_entrada = parsear_fecha_segura(row.get('FechaEntrada'))

                # Montos e impuestos (IVA) con parseo seguro
                vrtotal_val = parsear_monto_seguro(row.get('Pas_VrTotal'))
                vrunit_val = parsear_monto_seguro(row.get('Pas_Vrunit'))
                vrajuste_val = parsear_monto_seguro(row.get('Pas_VrAjuste'))
                vriva_val = parsear_monto_seguro(row.get('Pas_VrIva'))

                # Validación de regla de negocio / integridad
                if not pas_num or pas_num == 'nan' or vrtotal_val < 0 or not pas_fechaini:
                    motivo = f"Registro defectuoso: Pas_Num inválido, VrTotal corrupto o Fecha inicial nula/inválida (Valor: {row.get('Pas_fechaini')})"
                    cursor.execute(
                        """
                        INSERT INTO staging.cuarentena_recaudo 
                        (tecnologia, archivo_origen, payload_fila, motivo_rechazo)
                        VALUES (%s, %s, %s, %s)
                        """,
                        ('Incomelec', nombre_archivo, clave_negocio, str(row.to_dict()), motivo)
                    )
                    registros_cuarentena += 1
                    continue

                # Inserción normal con control de conflicto (Duplicados)
                cursor.execute(
                    """
                    INSERT INTO staging.stg_incomelec 
                    (
                        archivo_origen, pas_num, id_horus, cajero, tipo_operacion, ticket, 
                        factura_contingencia, factura_interna_horus, fecha_entrada, pas_cia, 
                        pas_id, pas_fechaini, pas_fechafin, pas_cantidad, pas_vrunit, 
                        pas_nit, div, pas_email, pas_observa, pas_placa, pas_nombre, 
                        pas_clasenit, pas_razon_social, pas_codigo_dane, pas_actividad_eco, 
                        pas_referencia, pas_idpos, pas_form_pago, pas_cufe, 
                        pas_vrajuste, pas_vriva, pas_vrtotal
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (pas_num, pas_fechaini) DO NOTHING
                    RETURNING 1;
                    """,
                    (
                        nombre_archivo,
                        pas_num,
                        str(row.get('IdHorus', '')).strip(),
                        str(row.get('Cajero', '')).strip(),
                        str(row.get('Tipo_Operacion', '')).strip(),
                        str(row.get('Ticket', '')).strip(),
                        str(row.get('Factura_Contingencia')).strip() if pd.notna(row.get('Factura_Contingencia')) else None,
                        str(row.get('Factura_Interna_Horus')).strip() if pd.notna(row.get('Factura_Interna_Horus')) else None,
                        fecha_entrada,
                        str(row.get('Pas_Cia', '')).strip(),
                        str(row.get('Pas_Id', '')).strip(),
                        pas_fechaini,
                        pas_fechafin,
                        str(row.get('Pas_Cantidad', '')).strip(),
                        vrunit_val,
                        str(row.get('Pas_Nit', '')).strip(),
                        str(row.get('Div')).strip() if pd.notna(row.get('Div')) else None,
                        str(row.get('Pas_Email')).strip() if pd.notna(row.get('Pas_Email')) else None,
                        str(row.get('Pas_Observa')).strip() if pd.notna(row.get('Pas_Observa')) else None,
                        str(row.get('Pas_Placa')).strip() if pd.notna(row.get('Pas_Placa')) else None,
                        str(row.get('Pas_Nombre', '')).strip(),
                        str(row.get('Pas_Clasenit', '')).strip(),
                        str(row.get('Pas_RazonSocial', '')).strip(),
                        str(row.get('Pas_CodigoDane')).strip() if pd.notna(row.get('Pas_CodigoDane')) else None,
                        str(row.get('Pas_ActividadEco')).strip() if pd.notna(row.get('Pas_ActividadEco')) else None,
                        str(row.get('Pas_Referencia')).strip() if pd.notna(row.get('Pas_Referencia')) else None,
                        str(row.get('Pas_Idpos', '')).strip(),
                        str(row.get('Pas_FormPago', '')).strip(),
                        str(row.get('Pas_Cufe', '')).strip(),
                        vrajuste_val,
                        vriva_val,
                        vrtotal_val
                    )
                )
                if cursor.fetchone():
                    registros_insertados += 1
                else:
                    registros_duplicados += 1

            # Registrar en el control de archivos
            cursor.execute(
                """
                INSERT INTO staging.control_archivos 
                (tecnologia, archivo_nombre, registros_cargados, registros_omitidos, archivo_hash, estado)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (archivo_hash) DO NOTHING;
                """,
                ('Incomelec', nombre_archivo, registros_insertados, registros_duplicados + registros_cuarentena, archivo_hash, 'EXITOSO')
            )
            
            conn.commit()
            print(f"✅ [EXITO] {nombre_archivo}: {registros_insertados} insertados | {registros_duplicados} duplicados | {registros_cuarentena} en cuarentena.")

        except Exception as e:
            conn.rollback()
            print(f"❌ [ERROR] Falló el procesamiento global del archivo {nombre_archivo}: {e}")
            try:
                cursor.execute(
                    """
                    INSERT INTO staging.control_archivos 
                    (tecnologia, archivo_nombre, registros_cargados, registros_omitidos, archivo_hash, estado)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    ('Incomelec', nombre_archivo, 0, 0, 'ERROR', 'FALLIDO')
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
    print("\n🎉 [ETL INCOMELEC] Proceso con Cuarentena y Parseo Robusto finalizado exitosamente.")

if __name__ == "__main__":
    FOLDER_INCOMELEC_ID = os.getenv("GDRIVE_INCOMELEC_FOLDER_ID", "14O3njJ5nse0YS51mGj9gDEZzrv-_nip8")
    procesar_incomelec(FOLDER_INCOMELEC_ID)