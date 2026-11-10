import os
import pandas as pd
from database import obtener_conexion
from gdrive import descargar_archivo
from datetime import datetime

def parsear_fecha_segura(valor):
    """
    Parsea de forma segura cualquier formato de fecha y descarta basura (ej. '887', '197').
    Devuelve un string en formato 'YYYY-MM-DD' o None si es inválido.
    """
    if pd.isna(valor) or not valor:
        return None
    
    s = str(valor).strip()
    # Descartar valores cortos o que no contengan dígitos o letras de fecha válidas
    if len(s) < 6 or not any(char.isdigit() for char in s):
        return None
    
    formatos = ['%d/%m/%Y', '%m/%d/%y', '%Y-%m-%d', '%d/%m/%y', '%m/%d/%Y', '%Y/%m/%d']
    for fmt in formatos:
        try:
            dt = datetime.strptime(s, fmt)
            # Validar rango lógico para evitar años erróneos
            if 2020 <= dt.year <= 2030:
                return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
            
    return None

def parsear_monto_seguro(valor):
    """
    Limpia y convierte montos (subtotal, impuestos/iva, total) de manera segura.
    """
    if pd.isna(valor) or valor == '':
        return 0.0
    try:
        s = str(valor).strip().replace('$', '').replace(' ', '')
        # Manejo básico de separadores de miles y decimales
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

def procesar_ezytec(file_id, file_name, file_hash):
    """
    Procesa un archivo de Ezytec con validaciones estrictas de fechas, 
    montos, impuestos (IVA), prefijo, folio (number) y CUFE.
    """
    local_path = f"/tmp/{file_name}"
    registros_cargados = 0
    registros_omitidos = 0
    registros_cuarentena = 0
    
    try:
        print(f"📥 [Ezytec] Descargando temporalmente: {file_name}")
        descargar_archivo(file_id, local_path)
        
        df = pd.read_csv(local_path)
        
        conn = obtener_conexion()
        cursor = conn.cursor()
        
        for _, row in df.iterrows():
            # Factura: Prefijo y Folio (number)
            prefix = str(row.get('prefix')).strip() if pd.notna(row.get('prefix')) else ''
            number = str(row.get('number')).strip() if pd.notna(row.get('number')) else ''
            
            # Fechas robustas (evita textos basura como '887' o '197')
            fcreacion = parsear_fecha_segura(row.get('fcreacion'))
            fdocumento = parsear_fecha_segura(row.get('fdocumento'))
            
            # Si la fecha principal del documento es vital y viene corrupta, podemos omitirla o registrarla
            if not fdocumento and not fcreacion:
                # Opcional: mandar a cuarentena o ignorar si carece de fecha válida
                continue

            cliente = str(row.get('cliente')).strip() if pd.notna(row.get('cliente')) else None
            idcliente = str(row.get('idcliente')).strip() if pd.notna(row.get('idcliente')) else None
            
            # Valores monetarios e IVA (impuestos) blindados
            subtotal = parsear_monto_seguro(row.get('subtotal'))
            impuestos = parsear_monto_seguro(row.get('impuestos')) # IVA / Impuestos
            total_nuevo = parsear_monto_seguro(row.get('total'))
            
            # Identificadores fiscales (CUFE)
            cufe = str(row.get('cufe')).strip() if pd.notna(row.get('cufe')) else None
            tascode = str(row.get('tascode')).strip() if pd.notna(row.get('tascode')) else None
            doctype = str(row.get('doctype')).strip() if pd.notna(row.get('doctype')) else None
            
            # Verificar si la llave de negocio ya existe (Idempotencia)
            # Clave de negocio para cuarentena o logs
            clave_negocio = f"{prefix}-{number}-{fcreacion}"

            # Verificar si la llave de negocio ya existe (Idempotencia)
            cursor.execute(
                """
                SELECT total FROM staging.stg_ezytec 
                WHERE prefix = %s AND number = %s AND fcreacion = %s
                """,
                (prefix, number, fcreacion)  # <-- Usamos la fecha parseada 'YYYY-MM-DD'
            )
            resultado = cursor.fetchone()
            
            if not resultado:
                # Insertar nuevo registro con fechas parseadas
                cursor.execute(
                    """
                    INSERT INTO staging.stg_ezytec 
                    (archivo_origen, prefix, number, fcreacion, fdocumento, cliente, idcliente, subtotal, impuestos, total, cufe, tascode, doctype)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        file_name, prefix, number, fcreacion, 
                        fdocumento, cliente, idcliente,
                        subtotal, impuestos, total_nuevo,
                        cufe, tascode, doctype
                    )
                )
                registros_cargados += 1
            else:
                total_anterior = resultado[0]
                if total_anterior != total_nuevo:
                    # Discrepancia de valor -> Cuarentena (con clave_negocio incluida)
                    cursor.execute(
                        """
                        INSERT INTO staging.cuarentena_recaudo 
                        (archivo_origen, tecnologia, clave_negocio, campo_discrepancia, valor_anterior, valor_nuevo, motivo_rechazo)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (file_name, 'Ezytec', clave_negocio, 'total', total_anterior, total_nuevo, 'Discrepancia de monto en llave existente')
                    )
                    registros_cuarentena += 1
                else:
                    registros_omitidos += 1
        
        # Registrar control de archivos
        cursor.execute(
            """
            INSERT INTO staging.control_archivos 
            (archivo_nombre, archivo_hash, tecnologia, registros_cargados, registros_omitidos, estado)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (archivo_hash) DO NOTHING;
            """,
            (file_name, file_hash, 'Ezytec', registros_cargados, registros_omitidos, 'EXITOSO')
        )
        
        conn.commit()
        cursor.close()
        conn.close()
        print(f"✅ [Ezytec] Archivo {file_name} procesado. Insertados: {registros_cargados} | Omitidos: {registros_omitidos} | Cuarentena: {registros_cuarentena}")

    except Exception as e:
        print(f"❌ [Ezytec] Error procesando {file_name}: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        return False 
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)
            print(f"🧹 [Ezytec] Archivo temporal {file_name} eliminado.")
    
    return True