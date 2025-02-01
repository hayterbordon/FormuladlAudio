# Usar una imagen base oficial de Python
FROM python:3.9-slim

# Instalar ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Establecer el directorio de trabajo en el contenedor
WORKDIR /app

# Copiar los archivos de requisitos
COPY requirements.txt requirements.txt

# Instalar las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto de los archivos de la aplicación
COPY . .

# Crear los directorios necesarios
RUN mkdir -p uploads audio_temp

# Establecer las variables de entorno
ENV PORT 8080

# Exponer el puerto en el que la aplicación se ejecutará
EXPOSE 8080

# Comando para ejecutar la aplicación
CMD exec gunicorn --bind :$PORT --workers 2 --timeout 120 main:app
