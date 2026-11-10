import os
import pandas as pd
from database import obtener_conexion
from gdrive import listar_archivos_en_subcarpeta, descargar_archivo

def auditar_ci24_completo(folder_id_ci24):
    print("🔍 [AUDITORÍA] Iniciando conciliación adaptativa de CI24 (Drive vs Base de Datos)...")
    
    archivos_drive = listar_archivos_en_subcarpeta(folder_id_ci24)
    if not archivos_drive:
        print("❌ No se encontraron archivos en la carpeta de Drive para CI24.")
        return

    mapa_drive = {f['name']: f for f in archivos_drive}
    nombres_drive = set(mapa_drive.keys())

    conn = obtener_conexion()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT archivo_nombre, registros_cargados, archivo_hash 
        FROM staging.control_archivos 
        WHERE tecnologia = 'CI24' AND estado = 'EXITOSO'
        """
    )
    registros_db = cursor.fetchall()
    mapa_db = {row[0]: {'registros': row[1], 'hash': row[2]} for row in registros_db}
    nombres_db = set(mapa_db.keys())

    cursor.close()
    conn.close()

    archivos_faltantes_en_db = nombres_drive - nombres_db

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

        try:
            descargar_archivo(file_id, local_path)
            df = pd.read_csv(local_path)
            
            # FILTRAR FILAS DE SUMARIO O FACTURAS NULAS
            if 'Dispositivo' in df.columns:
                df = df[~df['Dispositivo'].astype(str).str.lower().str.contains('total facturado|total de documentos', na=False)]
            if 'Factura' in df.columns:
                df = df[df['Factura'].notna() & (df['Factura'].astype(str).str.strip() != '') & (df['Factura'].astype(str).str.strip() != 'nan')]

            if 'Total' in df.columns:
                df['total_clean'] = pd.to_numeric(df['Total'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0.0)
                total_bruto_drive = float(df['total_clean'].sum())
                
                # Desduplicar netamente por la llave de CI24
                # Manejar variaciones de columnas de fecha
                col_fecha = 'Fecha' if 'Fecha' in df.columns else ('Fecha y hora' if 'Fecha y hora' in df.columns else None)
                if all(col in df.columns for col in ['Prefijo', 'Factura']) and col_fecha:
                    df_neto = df.drop_duplicates(subset=['Prefijo', 'Factura', col_fecha])
                else:
                    df_neto = df
                
                total_archivo_drive = float(df_neto['total_clean'].sum())
                monto_duplicado = total_bruto_drive - total_archivo_drive
                
            gran_total_drive += total_archivo_drive
        except Exception as e:
            print(f"{nombre_archivo[:35]:<35} | {'ERROR DESC':<20} | {'$0.00':<15} | ❌ FALLO")
            detalles_auditoria.append((nombre_archivo, 0.0, 0.0, 0.0, 0.0, 0.0, 'FALLO'))
            continue
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

        cursor.execute(
            "SELECT COALESCE(SUM(total), 0.0) FROM staging.stg_ci24 WHERE archivo_origen = %s",
            (nombre_archivo,)
        )
        total_archivo_db = float(cursor.fetchone()[0])

        diferencia_archivo = abs(total_archivo_drive - total_archivo_db)
        estado_archivo_str = "OK" if diferencia_archivo < 0.01 else "DIFF"
        
        print(f"{nombre_archivo[:35]:<35} | ${total_archivo_drive:18,.2f} | ${total_archivo_db:13,.2f} | {'✅ OK' if estado_archivo_str == 'OK' else '❌ DIFF'}")

        detalles_auditoria.append((
            nombre_archivo, total_archivo_drive, total_archivo_db, diferencia_archivo, total_bruto_drive, monto_duplicado, estado_archivo_str
        ))

    cursor.execute("SELECT COALESCE(SUM(total), 0.0) FROM staging.stg_ci24")
    gran_total_db = float(cursor.fetchone()[0])

    diferencia_global = abs(gran_total_drive - gran_total_db)
    estado_global_str = "EXITOSO" if (diferencia_global < 0.01 and not archivos_faltantes_en_db) else "DISCREPANCIA"

    cursor.execute(
        """
        INSERT INTO staging.log_auditoria_global 
        (tecnologia, total_archivos_drive, total_archivos_db, archivos_faltantes, gran_total_drive, gran_total_db, diferencia_global, estado_auditoria)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        ('CI24', len(nombres_drive), len(nombres_db), len(archivos_faltantes_en_db), gran_total_drive, gran_total_db, diferencia_global, estado_global_str)
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
    print("📊 RESULTADO FINAL DE LA AUDITORÍA CI24")
    print(f"🔹 Gran Total Origen Neto (Google Drive): ${gran_total_drive:,.2f}")
    print(f"🔹 Gran Total Destino (PostgreSQL)      : ${gran_total_db:,.2f}")
    print(f"🔹 Diferencia Global                    : ${diferencia_global:,.2f}")
    print("="*85)

if __name__ == "__main__":
    FOLDER_CI24_ID = os.getenv("GDRIVE_CI24_FOLDER_ID", "1wbZBPsRML47l90fYRchizviEsGpdjDoh")
    auditar_ci24_completo(FOLDER_CI24_ID)