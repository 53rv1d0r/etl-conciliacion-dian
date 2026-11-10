import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Ajustar path local
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from database import obtener_conexion
from gdrive import listar_archivos_en_subcarpeta

# Importar procesadores
from processors.ezytec_processor import procesar_ezytec
from processors.incomelec_processor import procesar_incomelec
from processors.divergente_processor import procesar_divergente
from processors.ci24_processor import procesar_ci24

# Importar auditores
from validar_facturacion_ezytec import auditar_ezytec_completo
from validar_facturacion_incomelec import auditar_incomelec_completo
from validar_facturacion_divergente import auditar_divergente_completo
from validar_facturacion_ci24 import auditar_ci24_completo

# Importar generador de reporte ejecutivo
from terminal_report import generar_reporte_ejecutivo_html

def obtener_metricas_tecnologia(tecnologia, folder_id):
    """Consulta la base de datos para construir el resumen ejecutivo y el detalle por archivo."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    # Archivos en Drive
    archivos_drive = listar_archivos_en_subcarpeta(folder_id)
    cant_drive = len(archivos_drive) if archivos_drive else 0
    
    # Archivos procesados en DB
    cursor.execute(
        "SELECT COUNT(*) FROM staging.control_archivos WHERE tecnologia = %s AND estado = 'EXITOSO'",
        (tecnologia,)
    )
    cant_db = cursor.fetchone()[0]
    
    # Última auditoría global registrada
    cursor.execute(
        """
        SELECT gran_total_drive, gran_total_db, diferencia_global, archivos_faltantes
        FROM staging.log_auditoria_global 
        WHERE tecnologia = %s 
        ORDER BY id DESC LIMIT 1
        """,
        (tecnologia,)
    )
    audit = cursor.fetchone()
    
    total_drive = float(audit[0]) if audit else 0.0
    total_db = float(audit[1]) if audit else 0.0
    diferencia = float(audit[2]) if audit else 0.0
    archivos_faltantes = audit[3] if audit else 0
    
    # Cuarentena
    cursor.execute(
        "SELECT COUNT(*) FROM staging.cuarentena_recaudo WHERE tecnologia = %s",
        (tecnologia,)
    )
    cuarentena = cursor.fetchone()[0]
    
    # ==========================================
    # CÁLCULO DEL ÍNDICE DE CALIDAD DEL DATO (%)
    # ==========================================
    # Total de registros válidos en base de datos para esta tecnología
    total_registros_validos = int(total_db) if total_db else 0
    total_procesados_global = total_registros_validos + cuarentena
    
    if total_procesados_global > 0:
        pct_calidad = round((total_registros_validos / total_procesados_global) * 100, 4)
    else:
        pct_calidad = 100.00  # Si no hay datos, asumimos 100% limpio por defecto
    
    # ==========================================
    # Consultar el detalle archivo por archivo de la última ejecución
    # ==========================================
    cursor.execute(
        """
        SELECT d.archivo_nombre, d.total_drive, d.total_db
        FROM staging.log_auditoria_detalle d
        JOIN staging.log_auditoria_global g ON d.auditoria_global_id = g.id
        WHERE g.tecnologia = %s AND g.id = (
            SELECT MAX(id) FROM staging.log_auditoria_global WHERE tecnologia = %s
        )
        ORDER BY d.archivo_nombre ASC
        """,
        (tecnologia, tecnologia)
    )
    filas_detalle = cursor.fetchall()
    
    detalles_archivos = []
    for fila in filas_detalle:
        detalles_archivos.append({
            'nombre': fila[0],
            'drive': float(fila[1]),
            'db': float(fila[2])
        })
    
    cursor.close()
    conn.close()
    
    return {
        'nombre': tecnologia,
        'archivos_drive': cant_drive,
        'archivos_db': cant_db,
        'total_drive': total_drive,
        'total_db': total_db,
        'diferencia': diferencia,
        'archivos_faltantes': archivos_faltantes,
        'registros_cuarentena': cuarentena,
        'indice_calidad_pct': pct_calidad,  # 👈 Nuevo indicador métrico del 0 al 100%
        'detalles_archivos': detalles_archivos
    }

def ejecutar_orquestador():
    print("="*85)
    print("🚀 [ORQUESTADOR ETL] Iniciando Pipeline Consolidado Multi-Proveedor")
    print(f"📅 Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*85)

    folder_ezytec = os.getenv("GDRIVE_EZYTEC_FOLDER_ID", "1cF5OJNZTZBfmZME2GTXSVK_cYwskzMBl")
    folder_incomelec = os.getenv("GDRIVE_INCOMELEC_FOLDER_ID", "14O3njJ5nse0YS51mGj9gDEZzrv-_nip8")
    folder_divergente = os.getenv("GDRIVE_DIVERGENTE_FOLDER_ID", "1oJjm2Kwd0NhiNQes7xrmviJVpbT_FTpu")
    folder_ci24 = os.getenv("GDRIVE_CI24_FOLDER_ID", "1wbZBPsRML47l90fYRchizviEsGpdjDoh")

    # ==========================================
    # 1. EZYTEC
    # ==========================================
    print("\n" + "-"*85)
    print("⚙️ [1/4] PROCESANDO: EZYTEC")
    print("-"*85)
    try:
        archivos_ezytec = listar_archivos_en_subcarpeta(folder_ezytec)
        if archivos_ezytec:
            conn = obtener_conexion()
            cursor = conn.cursor()
            cursor.execute("SELECT archivo_nombre FROM staging.control_archivos WHERE tecnologia = 'Ezytec' AND estado = 'EXITOSO'")
            procesados_db = {row[0] for row in cursor.fetchall()}
            cursor.close()
            conn.close()

            for archivo in archivos_ezytec:
                nombre = archivo.get('name')
                if nombre not in procesados_db:
                    procesar_ezytec(archivo.get('id'), nombre, archivo.get('md5Checksum', 'HASH_AUTO'))
        auditar_ezytec_completo(folder_ezytec)
    except Exception as e:
        print(f"❌ Error en Ezytec: {e}")

    # ==========================================
    # 2. INCOMELEC
    # ==========================================
    print("\n" + "-"*85)
    print("⚙️ [2/4] PROCESANDO: INCOMELEC")
    print("-"*85)
    try:
        procesar_incomelec(folder_incomelec)
        auditar_incomelec_completo(folder_incomelec)
    except Exception as e:
        print(f"❌ Error en Incomelec: {e}")

    # ==========================================
    # 3. DIVERGENTE
    # ==========================================
    print("\n" + "-"*85)
    print("⚙️ [3/4] PROCESANDO: DIVERGENTE")
    print("-"*85)
    try:
        procesar_divergente(folder_divergente)
        auditar_divergente_completo(folder_divergente)
    except Exception as e:
        print(f"❌ Error en Divergente: {e}")

    # ==========================================
    # 4. CI24
    # ==========================================
    print("\n" + "-"*85)
    print("⚙️ [4/4] PROCESANDO: CI24")
    print("-"*85)
    try:
        procesar_ci24(folder_ci24)
        auditar_ci24_completo(folder_ci24)
    except Exception as e:
        print(f"❌ Error en CI24: {e}")

    # ==========================================
    # REPORTE EJECUTIVO
    # ==========================================
    print("\n" + "="*85)
    print("📄 Generando Informe Ejecutivo Consolidado...")
    print("="*85)
    
    try:
        resumenes = [
            obtener_metricas_tecnologia('Ezytec', folder_ezytec),
            obtener_metricas_tecnologia('Incomelec', folder_incomelec),
            obtener_metricas_tecnologia('Divergente', folder_divergente),
            obtener_metricas_tecnologia('CI24', folder_ci24),
        ]
        
        generar_reporte_ejecutivo_html(resumenes, "data/reporte_ejecutivo_recaudo.html")
    except Exception as e:
        print(f"❌ Error generando el informe ejecutivo: {e}")

    print("\n" + "="*85)
    print("🎉 [ORQUESTADOR ETL] Pipeline consolidado ejecutado exitosamente de punta a punta.")
    print("="*85)

if __name__ == "__main__":
    ejecutar_orquestador()