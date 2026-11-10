import sys
import os

# Asegurar que la ruta 'src' esté disponible para las importaciones
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from database import obtener_conexion

def main():
    print("🚀 Iniciando contenedor ETL Recaudo...")
    print("🔄 Verificando la conexión a la base de datos PostgreSQL...")
    
    conn = obtener_conexion()
    if conn:
        print("✅ ¡Conexión exitosa a la base de datos desde el contenedor Docker!")
        
        # Consulta rápida de validación
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print(f"📊 Versión de Postgres: {version[0]}")
        
        cursor.close()
        conn.close()
        print("✨ Prueba de conexión finalizada con éxito.")
    else:
        print("❌ Error crítico: No se pudo establecer la conexión con la base de datos.")
        sys.exit(1)

if __name__ == "__main__":
    main()