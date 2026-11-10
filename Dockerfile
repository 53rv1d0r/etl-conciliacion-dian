# Usamos una imagen oficial y ligera de Python
FROM python:3.11-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Instalar dependencias del sistema esenciales para compilación si se requiere
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar las dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente y la estructura del proyecto
COPY src/ ./src/
COPY main.py .

# Comando por defecto al ejecutar el contenedor
CMD ["python", "main.py"]