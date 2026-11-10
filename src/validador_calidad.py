import os
import csv
import re
from datetime import datetime
from database import obtener_conexion

# Diccionario de reglas y esquemas esperados por tecnología
REGLAS_TECNOLOGIA = {
    'Ezytec': {'campo_total': 'total', 'campo_cufe': 'cufe'},
    'Incomelec': {'campo_total': 'pas_vrtotal', 'campo_cufe': 'pas_cufe'},
    'Divergente': {'campo_total': 'total', 'campo_cufe': 'cufe_cude'},
    'CI24': {'campo_total': 'total', 'campo_cufe': 'cufe'}
}

def validar_integridad_archivo(ruta_archivo, tecnologia):
    """
    Inspecciona un archivo CSV antes de procesarlo en Staging.
    Retorna una tupla: (registros_limpios, registros_en_cuarentena)
    """
    registros_limpios = []
    cuarentena = []
    
    if not os.path.exists(ruta_archivo):
        print(f"⚠️ Archivo no encontrado para validación: {ruta_archivo}")
        return registros_limpios, cuarentena

    nombre_archivo = os.path.basename(ruta_archivo)
    config = REGLAS_TECNOLOGIA.get(tecnologia, {})
    campo_total = config.get('campo_total', 'total')
    campo_cufe = config.get('campo_cufe', 'cufe')

    with open(ruta_archivo, mode='r', encoding='utf-8', errors='ignore') as f:
        lector = csv.DictReader(f)
        
        if not lector.fieldnames:
            cuarentena.append({
                'tecnologia': tecnologia,
                'archivo': nombre_archivo,
                'fila': 0,
                'campo': 'estructura_general',
                'clave_negocio': 'N/A',
                'error': 'El archivo CSV está vacío o carece de cabeceras válidas.',
                'data_cruda': ''
            })
            return registros_limpios, cuarentena

        fila_idx = 1  # Cabecera
        for fila in lector:
            fila_idx += 1
            error_detectado = None
            campo_afectado = None
            
            # Extraer clave de negocio (CUFE o identificador si existe en la fila)
            clave_neg = fila.get(campo_cufe, fila.get('id', fila.get('factura', 'N/A'))).strip()
            if not clave_neg:
                clave_neg = 'SIN_CLAVE'
            
            # 1. Validar fecha en el nombre del archivo
            match_fecha = re.search(r'([0-9]{8})\.csv', nombre_archivo)
            if match_fecha:
                try:
                    datetime.strptime(match_fecha.group(1), '%Y%m%d')
                except ValueError:
                    error_detectado = f"Fecha en nombre de archivo inválida: {match_fecha.group(1)}"
                    campo_afectado = "archivo_origen"
            
            # 2. Validar estructura de columnas clave
            if not error_detectado and (campo_total not in fila or campo_cufe not in fila):
                error_detectado = f"Estructura incompleta: Faltan columnas clave ('{campo_total}' o '{campo_cufe}'). Posible columna corrida."
                campo_afectado = "columnas_esquema"

            # 3. Validar sanitización numérica del monto total
            if not error_detectado:
                valor_str = fila.get(campo_total, '').strip()
                if valor_str:
                    try:
                        val_num = float(valor_str.replace(',', '.'))
                        if val_num < 0:
                            error_detectado = f"Valor monetario negativo en '{campo_total}': {valor_str}"
                            campo_afectado = campo_total
                    except ValueError:
                        error_detectado = f"Columna '{campo_total}' contiene texto no numérico: '{valor_str}'"
                        campo_afectado = campo_total
                else:
                    error_detectado = f"El campo obligatorio '{campo_total}' está vacío."
                    campo_afectado = campo_total

            # 4. Validar integridad del CUFE / CUDE
            if not error_detectado:
                cufe_val = fila.get(campo_cufe, '').strip()
                if not cufe_val or len(cufe_val) < 15:
                    error_detectado = f"CUFE inválido o demasiado corto en campo '{campo_cufe}': '{cufe_val}'"
                    campo_afectado = campo_cufe

            # Clasificar registro
            if error_detectado:
                cuarentena.append({
                    'tecnologia': tecnologia,
                    'archivo': nombre_archivo,
                    'fila': fila_idx,
                    'campo': campo_afectado or 'desconocido',
                    'clave_negocio': clave_neg,
                    'error': error_detectado,
                    'data_cruda': str(dict(fila))
                })
            else:
                registros_limpios.append(fila)

    return registros_limpios, cuarentena

def registrar_cuarentena_db(lote_errores):
    """Inserta los registros anómalos mapeando exactamente las columnas de cuarentena_recaudo."""
    if not lote_errores:
        return
    
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    for err in lote_errores:
        cursor.execute("""
            INSERT INTO staging.cuarentena_recaudo 
            (archivo_origen, tecnologia, clave_negocio, campo_discrepancia, motivo_rechazo, payload_fila, estado)
            VALUES (%s, %s, %s, %s, %s, %s, 'PENDIENTE');
        """, (
            err['archivo'],
            err['tecnologia'],
            err['clave_negocio'],
            err['campo'],
            err['error'],
            err['data_cruda']
        ))
        
    conn.commit()
    cursor.close()
    conn.close()
    print(f"🚨 Se registraron {len(lote_errores)} anomalías en la tabla de cuarentena.")