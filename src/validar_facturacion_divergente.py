import os
import pandas as pd
from database import obtener_conexion
from gdrive import listar_archivos_en_subcarpeta, descargar_archivo

def auditar_divergente_completo(folder_id_divergente):
    print("🔍 [AUDITORÍA] Iniciando conciliación exhaustiva de Divergente (Drive vs Base de Datos)...")
    
    archivos_drive = listar_archivos_en_subcarpeta(folder_id_divergente)
    if not archivos_drive:
        print("❌ No se encontraron archivos en la carpeta de Drive para Divergente.")
        return

    mapa_drive = {f['name']: f for f in archivos_drive}
    nombres_drive = set(mapa_drive.keys())

    conn = obtener_conexion()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT archivo_nombre, registros_cargados, archivo_hash 
        FROM staging.control_archivos 
        WHERE tecnologia = 'Divergente' AND estado = 'EXITOSO'
        """
    )
    registros_db = cursor.fetchall()
    mapa_db = {row[0]: {'registros': row[1], 'hash': row[2]} for row in registros_db}
    nombres_db = set(mapa_db.keys())

    cursor.close()
    conn.close()

    archivos_faltantes_en_db = nombres_drive - nombres_db
    archivos_huerfanos_en_db = nombres_db - nombres_drive

    print(f"\n📊 [RESUMEN DE COBERTURA DE ARCHIVOS - DIVERGENTE]")
    print(f"   - Total archivos en Google Drive: {len(nombres_drive)}")
    print(f"   - Total archivos procesados en DB: {len(nombres_db)}")
    
    if archivos_faltantes_en_db:
        print(f"   ⚠️ ¡ALERTA! Hay {len(archivos_faltantes_en_db)} archivos en Drive que NO se han procesado:")
        for f in sorted(archivos_faltantes_en_db):
            print(f"      ❌ Faltante: {f}")
    else:
        print("   ✅ Todos los archivos de Google Drive de Divergente tienen registro exitoso en la base de datos.")

    print("\n" + "="*85)
    print(f"{'ARCHIVO':<35} | {'TOTAL DRIVE (NETO)':<20} | {'TOTAL DB':<15} | {'ESTADO':<8}")
    print("="*85)

    gran_total_drive = 0.0
    detalles_auditoria = []

    conn = obtener_conexion()
    cursor = conn.cursor()

    for nombre_archivo in sorted(nombres_drive):
        file_id = mapa_drive[nombre_archivo]['id']
        local_path = f"/tmp/{nombre_archivo}"
        total_archivo_drive = 0.0
        total_bruto_drive = 0.0
        monto_duplicado = 0.0

        try:
            descargar_archivo(file_id, local_path)
            df = pd.read_csv(local_path)
            if 'Total' in df.columns:
                df['total_clean'] = pd.to_numeric(df['Total'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0.0)
                total_bruto_drive = float(df['total_clean'].sum())
                
                # Desduplicar netamente por la llave de Divergente
                if all(col in df.columns for col in ['Prefijo', 'Folio', 'Fecha Emisión']):
                    df_neto = df.drop_duplicates(subset=['Prefijo', 'Folio', 'Fecha Emisión'])
                else:
                    df_neto = df
                
                total_archivo_drive = float(df_neto['total_clean'].sum())
                monto_duplicado = total_bruto_drive - total_archivo_drive
                
            gran_total_drive += total_archivo_drive
        except Exception as e:
            print(f"{nombre_archivo[:35]:<35} | {'ERROR DESC':<20} | {'$0.00':<15} | ❌ FALLO")
            detalles_auditoria.append((
                nombre_archivo, 0.0, 0.0, 0.0, 0.0, 0.0, 'FALLO'
            ))
            continue
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

        cursor.execute(
            """
            SELECT COALESCE(SUM(total), 0.0) 
            FROM staging.stg_divergente 
            WHERE archivo_origen = %s
            """,
            (nombre_archivo,)
        )
        total_archivo_db = float(cursor.fetchone()[0])

        diferencia_archivo = abs(total_archivo_drive - total_archivo_db)
        estado_archivo_str = "OK" if diferencia_archivo < 0.01 else "DIFF"
        
        print(f"{nombre_archivo[:35]:<35} | ${total_archivo_drive:18,.2f} | ${total_archivo_db:13,.2f} | {'✅ OK' if estado_archivo_str == 'OK' else '❌ DIFF'}")

        detalles_auditoria.append((
            nombre_archivo, 
            total_archivo_drive, 
            total_archivo_db, 
            diferencia_archivo, 
            total_bruto_drive,
            monto_duplicado,
            estado_archivo_str
        ))

    cursor.execute("SELECT COALESCE(SUM(total), 0.0) FROM staging.stg_divergente")
    gran_total_db = float(cursor.fetchone()[0])

    diferencia_global = abs(gran_total_drive - gran_total_db)
    estado_global_str = "EXITOSO" if (diferencia_global < 0.01 and not archivos_faltantes_en_db) else "DISCREPANCIA"

    print("\n💾 [AUDITORÍA] Guardando resultados en las tablas de log de auditoría...")
    
    cursor.execute(
        """
        INSERT INTO staging.log_auditoria_global 
        (tecnologia, total_archivos_drive, total_archivos_db, archivos_faltantes, gran_total_drive, gran_total_db, diferencia_global, estado_auditoria)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (
            'Divergente', 
            len(nombres_drive), 
            len(nombres_db), 
            len(archivos_faltantes_en_db), 
            gran_total_drive, 
            gran_total_db, 
            diferencia_global, 
            estado_global_str
        )
    )
    auditoria_global_id = cursor.fetchone()[0]

    for det in detalles_auditoria:
        cursor.execute(
            """
            INSERT INTO staging.log_auditoria_detalle 
            (auditoria_global_id, archivo_nombre, total_drive, total_db, diferencia, total_drive_bruto, monto_duplicado, estado_archivo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (auditoria_global_id, det[0], det[1], det[2], det[3], det[4], det[5], det[6])
        )

    conn.commit()
    cursor.close()
    conn.close()

    print("="*85)
    print("\n" + "="*45)
    print("📊 RESULTADO FINAL DE LA AUDITORÍA DIVERGENTE")
    print("="*45)
    print(f"🔹 Gran Total Origen Neto (Google Drive): ${gran_total_drive:,.2f}")
    print(f"🔹 Gran Total Destino (PostgreSQL)      : ${gran_total_db:,.2f}")
    print(f"🔹 Diferencia Global                    : ${diferencia_global:,.2f}")
    
    if estado_global_str == "EXITOSO":
        print("✅ ¡Cerradura perfecta! El recaudo de Divergente cuadra al centavo.")
    else:
        print("❌ ¡Atención! Se registraron discrepancias en Divergente y quedaron guardadas en el histórico.")
    print("="*85)

if __name__ == "__main__":
    FOLDER_DIVERGENTE_ID = os.getenv("GDRIVE_DIVERGENTE_FOLDER_ID", "1oJjm2Kwd0NhiNQes7xrmviJVpbT_FTpu")
    auditar_divergente_completo(FOLDER_DIVERGENTE_ID)