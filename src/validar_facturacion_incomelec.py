import os
import pandas as pd
from database import obtener_conexion
from gdrive import listar_archivos_en_subcarpeta, descargar_archivo

def auditar_incomelec_completo(folder_id_incomelec):
    print("🔍 [AUDITORÍA] Iniciando conciliación exhaustiva de Incomelec (Drive vs Base de Datos)...")
    
    # 1. Obtener todos los archivos de Google Drive
    archivos_drive = listar_archivos_en_subcarpeta(folder_id_incomelec)
    if not archivos_drive:
        print("❌ No se encontraron archivos en la carpeta de Google Drive de Incomelec.")
        return

    mapa_drive = {f['name']: f for f in archivos_drive}
    nombres_drive = set(mapa_drive.keys())

    # 2. Consultar la base de datos para ver qué se procesó
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT archivo_nombre, registros_cargados, archivo_hash 
        FROM staging.control_archivos 
        WHERE tecnologia = 'Incomelec' AND estado = 'EXITOSO'
        """
    )
    registros_db = cursor.fetchall()
    mapa_db = {row[0]: {'registros': row[1], 'hash': row[2]} for row in registros_db}
    nombres_db = set(mapa_db.keys())

    cursor.close()
    conn.close()

    # 3. Cruzar listas para detectar anomalías
    archivos_faltantes_en_db = nombres_drive - nombres_db
    archivos_huerfanos_en_db = nombres_db - nombres_drive

    print(f"\n📊 [RESUMEN DE COBERTURA DE ARCHIVOS - INCOMELEC]")
    print(f"   - Total archivos en Google Drive: {len(nombres_drive)}")
    print(f"   - Total archivos procesados en DB: {len(nombres_db)}")
    
    if archivos_faltantes_en_db:
        print(f"   ⚠️ ¡ALERTA! Hay {len(archivos_faltantes_en_db)} archivos en Drive que NO se han procesado:")
        for f in sorted(archivos_faltantes_en_db):
            print(f"      ❌ Faltante: {f}")
    else:
        print("   ✅ Todos los archivos de Google Drive de Incomelec tienen registro exitoso en la base de datos.")

    if archivos_huerfanos_en_db:
        print(f"   ⚠️ Atención: Hay {len(archivos_huerfanos_en_db)} registros en DB que ya no están en Drive.")

    # 4. Conciliación de montos totales archivo por archivo
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

        try:
            # Descargar temporalmente para sumar en origen
            descargar_archivo(file_id, local_path)
            df = pd.read_csv(local_path)
            
            if 'Pas_VrTotal' in df.columns:
                # Convertir montos limpios
                df['Pas_VrTotal_Clean'] = df['Pas_VrTotal'].astype(str).str.replace(',', '.').astype(float)
                
                # Desduplicar localmente en base a la llave de negocio (Pas_Num, Pas_fechaini)
                if 'Pas_Num' in df.columns and 'Pas_fechaini' in df.columns:
                    df_neto = df.drop_duplicates(subset=['Pas_Num', 'Pas_fechaini'])
                else:
                    df_neto = df

                total_archivo_drive = float(df_neto['Pas_VrTotal_Clean'].sum())
            
            gran_total_drive += total_archivo_drive
        except Exception as e:
            print(f"{nombre_archivo[:35]:<35} | {'ERROR DESC':<20} | {'$0.00':<15} | ❌ FALLO")
            detalles_auditoria.append((
                nombre_archivo, 
                0.0, 
                0.0, 
                0.0, 
                'FALLO'
            ))
            continue
        finally:
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except:
                    pass

        # Consultar la suma real insertada en staging para este archivo específico
        cursor.execute(
            """
            SELECT COALESCE(SUM(pas_vrtotal), 0.0) 
            FROM staging.stg_incomelec 
            WHERE archivo_origen = %s
            """,
            (nombre_archivo,)
        )
        total_archivo_db = float(cursor.fetchone()[0])

        # Verificamos si cuadran los montos netos del archivo
        diferencia_archivo = abs(total_archivo_drive - total_archivo_db)
        estado_archivo_str = "OK" if diferencia_archivo < 0.01 else "DIFF"
        
        print(f"{nombre_archivo[:35]:<35} | ${total_archivo_drive:18,.2f} | ${total_archivo_db:13,.2f} | {'✅ OK' if estado_archivo_str == 'OK' else '❌ DIFF'}")

        detalles_auditoria.append((
            nombre_archivo, 
            total_archivo_drive, 
            total_archivo_db, 
            diferencia_archivo, 
            estado_archivo_str
        ))

    # 5. Gran Total Global en Base de Datos para Incomelec
    cursor.execute("SELECT COALESCE(SUM(pas_vrtotal), 0.0) FROM staging.stg_incomelec")
    gran_total_db = float(cursor.fetchone()[0])

    diferencia_global = abs(gran_total_drive - gran_total_db)
    estado_global_str = "EXITOSO" if (diferencia_global < 0.01 and not archivos_faltantes_en_db) else "DISCREPANCIA"

    # 6. PERSISTENCIA DE RESULTADOS EN BASE DE DATOS
    print("\n💾 [AUDITORÍA] Guardando resultados en las tablas de log de auditoría...")
    
    cursor.execute(
        """
        INSERT INTO staging.log_auditoria_global 
        (tecnologia, total_archivos_drive, total_archivos_db, archivos_faltantes, gran_total_drive, gran_total_db, diferencia_global, estado_auditoria)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (
            'Incomelec', 
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
            (auditoria_global_id, archivo_nombre, total_drive, total_db, diferencia, estado_archivo)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (auditoria_global_id, det[0], det[1], det[2], det[3], det[4])
        )

    conn.commit()
    cursor.close()
    conn.close()

    print("="*85)
    print("\n" + "="*45)
    print("📊 RESULTADO FINAL DE LA AUDITORÍA INCOMELEC")
    print("="*45)
    print(f"🔹 Gran Total Origen Neto (Google Drive): ${gran_total_drive:,.2f}")
    print(f"🔹 Gran Total Destino (PostgreSQL)      : ${gran_total_db:,.2f}")
    print(f"🔹 Diferencia Global                    : ${diferencia_global:,.2f}")
    
    if estado_global_str == "EXITOSO":
        print("✅ ¡Cerradura perfecta! El recaudo de Incomelec cuadra al centavo.")
    else:
        print("❌ ¡Atención! Se registraron discrepancias en Incomelec y quedaron guardadas en el histórico.")
    print("="*85)

if __name__ == "__main__":
    FOLDER_INCOMELEC_ID = os.getenv("GDRIVE_INCOMELEC_FOLDER_ID", "14O3njJ5nse0YS51mGj9gDEZzrv-_nip8")
    auditar_incomelec_completo(FOLDER_INCOMELEC_ID)