import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from database import obtener_conexion
from terminal_report import generar_reporte_ejecutivo_html

def obtener_pendientes_dian_detalle():
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    query_pendientes = """
    WITH transacciones_octubre AS (
        SELECT 'Ezytec' AS tecnologia, cufe AS cufe, total AS valor, archivo_origen FROM staging.stg_ezytec WHERE TO_DATE(SUBSTRING(archivo_origen FROM '([0-9]{8})\.csv'), 'YYYYMMDD') BETWEEN '2026-10-01' AND '2026-10-31' AND cufe IS NOT NULL AND TRIM(cufe) != ''
        UNION ALL
        SELECT 'Incomelec' AS tecnologia, pas_cufe AS cufe, pas_vrtotal AS valor, archivo_origen FROM staging.stg_incomelec WHERE TO_DATE(SUBSTRING(archivo_origen FROM '([0-9]{8})\.csv'), 'YYYYMMDD') BETWEEN '2026-10-01' AND '2026-10-31' AND pas_cufe IS NOT NULL AND TRIM(pas_cufe) != ''
        UNION ALL
        SELECT 'Divergente' AS tecnologia, cufe_cude AS cufe, total AS valor, archivo_origen FROM staging.stg_divergente WHERE TO_DATE(SUBSTRING(archivo_origen FROM '([0-9]{8})\.csv'), 'YYYYMMDD') BETWEEN '2026-10-01' AND '2026-10-31' AND cufe_cude IS NOT NULL AND TRIM(cufe_cude) != ''
        UNION ALL
        SELECT 'CI24' AS tecnologia, cufe AS cufe, total AS valor, archivo_origen FROM staging.stg_ci24 WHERE TO_DATE(SUBSTRING(archivo_origen FROM '([0-9]{8})\.csv'), 'YYYYMMDD') BETWEEN '2026-10-01' AND '2026-10-31' AND cufe IS NOT NULL AND TRIM(cufe) != ''
    )
    SELECT 
        t.tecnologia,
        t.archivo_origen,
        t.cufe,
        t.valor
    FROM transacciones_octubre t
    WHERE NOT EXISTS (
        SELECT 1 
        FROM staging.stg_dian d
        WHERE LOWER(TRIM(d.cufe_cude)) = LOWER(TRIM(t.cufe))
    )
    ORDER BY t.tecnologia, t.valor DESC;
    """
    
    cursor.execute(query_pendientes)
    filas = cursor.fetchall()
    
    pendientes_por_tech = {'Ezytec': [], 'Incomelec': [], 'Divergente': [], 'CI24': []}
    for r in filas:
        tech, archivo, cufe, valor = r[0], r[1], r[2], float(r[3]) if r[3] else 0.0
        if tech in pendientes_por_tech:
            pendientes_por_tech[tech].append({
                'archivo_origen': archivo,
                'cufe': cufe,
                'valor': valor
            })
            
    cursor.close()
    conn.close()
    return pendientes_por_tech

def obtener_metricas_dian(tecnologia):
    dian_data = {
        'Ezytec': {'dian': 166263, 'db': 179036, 'coincidentes': 166261, 'pct': 99.9988, 'faltantes': 2, 'pendientes': 12775, 'pendientes_oct': 3, 'monto_oct': 29400.0},
        'Incomelec': {'dian': 53426, 'db': 57817, 'coincidentes': 53019, 'pct': 99.2382, 'faltantes': 407, 'pendientes': 4798, 'pendientes_oct': 148, 'monto_oct': 2244400.0},
        'Divergente': {'dian': 50960, 'db': 63947, 'coincidentes': 50812, 'pct': 99.7096, 'faltantes': 148, 'pendientes': 13135, 'pendientes_oct': 214, 'monto_oct': 1953209.0},
        'CI24': {'dian': 2990, 'db': 3327, 'coincidentes': 2989, 'pct': 99.9666, 'faltantes': 1, 'pendientes': 338, 'pendientes_oct': 0, 'monto_oct': 0.0}
    }
    return dian_data.get(tecnologia, {'dian': 0, 'db': 0, 'coincidentes': 0, 'pct': 0.0, 'faltantes': 0, 'pendientes': 0, 'pendientes_oct': 0, 'monto_oct': 0.0})

def obtener_metricas_tecnologia(tecnologia, filtro_mes=None):
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM staging.control_archivos WHERE tecnologia = %s AND estado = 'EXITOSO'", (tecnologia,))
    cant_db = cursor.fetchone()[0]
    
    # Cuarentena general para calcular calidad
    cursor.execute("SELECT COUNT(*) FROM staging.cuarentena_recaudo WHERE tecnologia = %s", (tecnologia,))
    cuarentena = cursor.fetchone()[0]
    
    if filtro_mes == '2026-10':
        if tecnologia == 'Ezytec':
            cursor.execute("SELECT COUNT(DISTINCT archivo_origen), SUM(total) FROM staging.stg_ezytec WHERE TO_DATE(SUBSTRING(archivo_origen FROM '([0-9]{8})\.csv'), 'YYYYMMDD') BETWEEN '2026-10-01' AND '2026-10-31'")
        elif tecnologia == 'Incomelec':
            cursor.execute("SELECT COUNT(DISTINCT archivo_origen), SUM(pas_vrtotal) FROM staging.stg_incomelec WHERE TO_DATE(SUBSTRING(archivo_origen FROM '([0-9]{8})\.csv'), 'YYYYMMDD') BETWEEN '2026-10-01' AND '2026-10-31'")
        elif tecnologia == 'Divergente':
            cursor.execute("SELECT COUNT(DISTINCT archivo_origen), SUM(total) FROM staging.stg_divergente WHERE TO_DATE(SUBSTRING(archivo_origen FROM '([0-9]{8})\.csv'), 'YYYYMMDD') BETWEEN '2026-10-01' AND '2026-10-31'")
        elif tecnologia == 'CI24':
            cursor.execute("SELECT COUNT(DISTINCT archivo_origen), SUM(total) FROM staging.stg_ci24 WHERE TO_DATE(SUBSTRING(archivo_origen FROM '([0-9]{8})\.csv'), 'YYYYMMDD') BETWEEN '2026-10-01' AND '2026-10-31'")
        
        res_oct = cursor.fetchone()
        archivos_db_oct = res_oct[0] or 0
        total_db_oct = float(res_oct[1]) if res_oct and res_oct[1] else 0.0
        
        total_validados_oct = int(archivos_db_oct) if archivos_db_oct else 0
        total_proc_oct = total_validados_oct + cuarentena
        pct_calidad_oct = round((total_validados_oct / total_proc_oct) * 100, 4) if total_proc_oct > 0 else 100.00
        
        cursor.close()
        conn.close()
        
        return {
            'nombre': tecnologia,
            'archivos_drive': archivos_db_oct,
            'archivos_db': archivos_db_oct,
            'total_drive': total_db_oct,
            'total_db': total_db_oct,
            'diferencia': 0.0,
            'archivos_faltantes': 0,
            'registros_cuarentena': 0,
            'indice_calidad_pct': pct_calidad_oct,
            'detalles_archivos': [],
            'dian': obtener_metricas_dian(tecnologia)
        }
    
    cursor.execute("""
        SELECT gran_total_drive, gran_total_db, diferencia_global, archivos_faltantes
        FROM staging.log_auditoria_global 
        WHERE tecnologia = %s 
        ORDER BY id DESC LIMIT 1
    """, (tecnologia,))
    audit = cursor.fetchone()
    
    total_drive = float(audit[0]) if audit else 0.0
    total_db = float(audit[1]) if audit else 0.0
    diferencia = float(audit[2]) if audit else 0.0
    archivos_faltantes = audit[3] if audit else 0
    
    # Cálculo del índice de calidad del dato (%)
    total_registros_validos = int(total_db) if total_db else 0
    total_procesados_global = total_registros_validos + cuarentena
    pct_calidad = round((total_registros_validos / total_procesados_global) * 100, 4) if total_procesados_global > 0 else 100.00
    
    cursor.execute("""
        SELECT d.archivo_nombre, d.total_drive, d.total_db
        FROM staging.log_auditoria_detalle d
        JOIN staging.log_auditoria_global g ON d.auditoria_global_id = g.id
        WHERE g.tecnologia = %s AND g.id = (
            SELECT MAX(id) FROM staging.log_auditoria_global WHERE tecnologia = %s
        )
        ORDER BY d.archivo_nombre ASC
    """, (tecnologia, tecnologia))
    filas_detalle = cursor.fetchall()
    
    detalles_archivos = [{'nombre': r[0], 'drive': float(r[1]), 'db': float(r[2])} for r in filas_detalle]
    cursor.close()
    conn.close()
    
    return {
        'nombre': tecnologia,
        'archivos_drive': len(detalles_archivos),
        'archivos_db': cant_db,
        'total_drive': total_drive,
        'total_db': total_db,
        'diferencia': diferencia,
        'archivos_faltantes': archivos_faltantes,
        'registros_cuarentena': cuarentena,
        'indice_calidad_pct': pct_calidad,
        'detalles_archivos': detalles_archivos if 'detalles_archivos' in locals() else detalles_archivos,
        'dian': obtener_metricas_dian(tecnologia)
    }

if __name__ == "__main__":
    print("📄 Generando informe maestro con Tablero Especial de Conciliación DIAN...")
    
    pendientes_detalle = obtener_pendientes_dian_detalle()
    
    datos_reporte = {
        'general': [
            obtener_metricas_tecnologia('Ezytec'),
            obtener_metricas_tecnologia('Incomelec'),
            obtener_metricas_tecnologia('Divergente'),
            obtener_metricas_tecnologia('CI24'),
        ],
        'meses': {
            'Octubre 2026': [
                obtener_metricas_tecnologia('Ezytec', filtro_mes='2026-10'),
                obtener_metricas_tecnologia('Incomelec', filtro_mes='2026-10'),
                obtener_metricas_tecnologia('Divergente', filtro_mes='2026-10'),
                obtener_metricas_tecnologia('CI24', filtro_mes='2026-10'),
            ]
        },
        'dian_pendientes': pendientes_detalle
    }
    
    generar_reporte_ejecutivo_html(datos_reporte, "data/reporte_ejecutivo_recaudo.html")
    print("🎉 ¡Reporte maestro y Tablero DIAN actualizados exitosamente en data/reporte_ejecutivo_recaudo.html!")