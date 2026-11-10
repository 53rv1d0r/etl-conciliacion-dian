import pandas as pd
import os
from database import obtener_conexion

def conciliar_recaudo_dian(ruta_excel_dian):
    print("="*85)
    print("🔍 [CONCILIACIÓN DIAN] Análisis de Cobertura y Trazabilidad con Porcentajes")
    print("="*85)
    
    if not os.path.exists(ruta_excel_dian):
        print(f"❌ Error: No se encuentra el archivo {ruta_excel_dian}")
        return

    print(f"📂 Leyendo reporte DIAN: {ruta_excel_dian}...")
    df_dian = pd.read_excel(ruta_excel_dian, sheet_name='DIAN')
    
    # Mapeo de operadores de la DIAN a nuestras tecnologías y columnas
    mapeo_operadores = {
        'Eglobal - Ezytech': ('Ezytec', 'staging.stg_ezytec', 'cufe', 'total'),
        'Incomelec': ('Incomelec', 'staging.stg_incomelec', 'pas_cufe', 'pas_vrtotal'),
        'Divergente - CIP': ('Divergente', 'staging.stg_divergente', 'cufe_cude', 'total'),
        'Controles Inteligentes -SIMBA': ('CI24', 'staging.stg_ci24', 'cufe', 'total')
    }
    
    conn = obtener_conexion()
    os.makedirs('data', exist_ok=True)
    writer = pd.ExcelWriter('data/detalle_conciliacion_dian.xlsx', engine='openpyxl')
    
    resumen_global = []
    
    for operador_dian, (tech_name, tabla, col_cufe_db, col_total_db) in mapeo_operadores.items():
        print(f"\n-------------------------------------------------------------------------------------")
        print(f"⚙️ Procesando tecnología: {tech_name} (Operador DIAN: {operador_dian})")
        print(f"-------------------------------------------------------------------------------------")
        
        # Filtrar DIAN para este operador
        df_d = df_dian[df_dian['Operador'].str.strip() == operador_dian].copy()
        
        # Consultar DB Staging
        query = f"SELECT archivo_origen, {col_cufe_db} AS cufe, {col_total_db} AS total FROM {tabla}"
        try:
            df_db = pd.read_sql(query, conn)
        except Exception as e:
            print(f"⚠️ Error consultando tabla {tabla}: {e}")
            continue
            
        # Normalizar CUFE
        df_d['CUFE_clean'] = df_d['CUFE/CUDE'].astype(str).str.strip().str.lower()
        df_db['CUFE_clean'] = df_db['cufe'].astype(str).str.strip().str.lower()
        
        # Filtrar nulos
        df_d = df_d[df_d['CUFE_clean'] != 'nan']
        df_db = df_db[df_db['CUFE_clean'] != 'nan']
        
        # Cruzar mediante FULL OUTER JOIN
        merged = pd.merge(
            df_d,
            df_db,
            on='CUFE_clean',
            how='outer',
            suffixes=('_dian', '_db'),
            indicator=True
        )
        
        total_dian = len(df_d)
        total_db = len(df_db)
        ambos = len(merged[merged['_merge'] == 'both'])
        solo_dian = len(merged[merged['_merge'] == 'left_only'])
        solo_db = len(merged[merged['_merge'] == 'right_only'])
        
        # Cálculo de porcentajes de captura y coincidencia
        porcentaje_cobertura = (ambos / total_dian * 100) if total_dian > 0 else 0
        porcentaje_diferencia = (solo_dian / total_dian * 100) if total_dian > 0 else 0
        
        print(f"📊 Registros en Reporte DIAN : {total_dian:,}")
        print(f"📊 Registros en Staging DB   : {total_db:,}")
        print(f"✅ Coincidentes por CUFE     : {ambos:,} ({porcentaje_cobertura:.4f}% de captura)")
        print(f"📥 Solo en DIAN (Faltantes DB): {solo_dian:,} ({porcentaje_diferencia:.4f}% de diferencia)")
        print(f"📤 Solo en DB (Pendientes DIAN): {solo_db:,}")
        
        # Guardar para la pestaña de resumen global
        resumen_global.append({
            'Tecnología': tech_name,
            'Registros DIAN': total_dian,
            'Registros DB Staging': total_db,
            'Coincidentes CUFE': ambos,
            'Faltantes DB (Solo DIAN)': solo_dian,
            '% Cobertura (Captura)': round(porcentaje_cobertura, 4),
            '% Diferencia': round(porcentaje_diferencia, 4),
            'Pendientes DIAN (Solo DB)': solo_db
        })
        
        # Reorganizar columnas para incluir archivo_origen
        columnas_ordenadas = [col for col in merged.columns if col != 'archivo_origen']
        if 'archivo_origen' in merged.columns:
            columnas_ordenadas.insert(2, 'archivo_origen')
            merged = merged[columnas_ordenadas]

        # Guardar pestaña detallada
        merged.to_excel(writer, sheet_name=tech_name[:31], index=False)
        
    # Crear una pestaña adicional con el Resumen Ejecutivo de Porcentajes
    df_resumen = pd.DataFrame(resumen_global)
    df_resumen.to_excel(writer, sheet_name='Resumen_Cobertura', index=False)
    
    conn.close()
    writer.close()
    
    print("\n" + "="*85)
    print("🎉 [CONCILIACIÓN DIAN] Análisis completado con indicadores porcentuales.")
    print("📁 Reporte actualizado y con pestaña 'Resumen_Cobertura' en: data/detalle_conciliacion_dian.xlsx")
    print("="*85)

if __name__ == '__main__':
    conciliar_recaudo_dian('data/dian31oct.xlsx')