import os
from dotenv import load_dotenv
import psycopg2

# Cargar las variables de entorno desde el archivo .env ubicado en la raíz
load_dotenv()

def obtener_conexion():
    """
    Establece y retorna una conexión activa a la base de datos PostgreSQL.
    """
    try:
        conexion = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            port=os.getenv("DB_PORT")
        )
        return conexion
    except Exception as e:
        print(f"❌ Error al conectar a la base de datos: {e}")
        return None

if __name__ == "__main__":
    print("🔄 Probando conexión a la base de datos PostgreSQL...")
    conn = obtener_conexion()
    if conn:
        print("✅ ¡Conexión exitosa a la base de datos `db_etl_recaudo`!")
        
        # Prueba rápida consultando la versión de Postgres
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print(f"📊 Versión de Postgres: {version[0]}")
        
        cursor.close()
        conn.close()
    else:
        print("❌ No se pudo establecer la conexión. Revisa tus credenciales en el archivo .env.")

def verificar_archivo_procesado(conn, archivo_hash):
    """
    Verifica si un archivo ya fue procesado exitosamente basado en su hash MD5.
    Retorna True si ya existe en la tabla de control con estado EXITOSO.
    """
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT 1 FROM staging.control_archivos 
                WHERE archivo_hash = %s AND estado = 'EXITOSO'
            """
            cursor.execute(query, (archivo_hash,))
            return cursor.fetchone() is not None
    except Exception as e:
        print(f"❌ Error al consultar la tabla de control: {e}")
        if conn:
            conn.rollback()  # Resetea la transacción abortada para permitir consultas futuras
        return False