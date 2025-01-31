import requests
import yt_dlp
from io import BytesIO
import librosa
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from pydub import AudioSegment
from flask import Flask, request, render_template, jsonify
import threading
from pathlib import Path
import os

# Configuración
UMBRAL_SIMILITUD = 0.97  # Umbral de similitud ajustado (más alto)
FRAGMENT_DURATION = 1000  # Duración máxima del fragmento a descargar (5 minutos)
SEGMENT_DURATION = 1000  # Duración de cada segmento a analizar (30 segundos)

# Lista para almacenar coincidencias
coincidencias = []
no_coincidencias = []
procesando = False

app = Flask(__name__)

def buscar_videos_youtube(query, max_resultados=1):
    API_KEY = os.environ.get("API_KEY")  # Obtener la API Key desde la variable de entorno
    if not API_KEY:
        raise ValueError("API_KEY no está configurada en las variables de entorno.")
    
    search_url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'maxResults': max_resultados,
        'key': API_KEY
    }
    response = requests.get(search_url, params=params, timeout=10)
    response.raise_for_status()
    resultados = response.json()
    videos = [{"videoId": item["id"]["videoId"], "title": item["snippet"]["title"]} for item in resultados.get("items", [])]
    return videos

def descargar_audio_youtube(video_url, output_path):
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "cookiefile": "cookies.txt"  # Añadir la ruta al archivo de cookies
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            audio_file = output_path % {'id': info['id'], 'ext': 'mp3'}
            if Path(audio_file).exists():
                print(f"✅ Audio descargado: {audio_file}")
                return audio_file
            else:
                print(f"❌ No se encontró el archivo de audio descargado: {audio_file}")
                return None
    except Exception as e:
        print(f"❌ Error al descargar el audio de {video_url}: {e}")
        return None

def obtener_fragmento_grande(video_url, max_duration=FRAGMENT_DURATION):
    audio_path = descargar_audio_youtube(video_url, str(Path("audio_temp") / "%(id)s.%(ext)s"))
    if audio_path:
        return open(audio_path, "rb")
    else:
        return None

def convertir_a_wav(audio_stream):
    audio = AudioSegment.from_file(audio_stream)
    wav_stream = BytesIO()
    audio.export(wav_stream, format="wav")
    wav_stream.seek(0)
    return wav_stream

def dividir_audio_en_segmentos(audio_stream, segment_duration=SEGMENT_DURATION):
    wav_stream = convertir_a_wav(audio_stream)
    y, sr = librosa.load(wav_stream, sr=None)
    segment_length = segment_duration * sr
    return [y[i:i + segment_length] for i in range(0, len(y), segment_length)]

def extraer_caracteristicas(audio_stream):
    wav_stream = convertir_a_wav(audio_stream)
    y, sr = librosa.load(wav_stream, sr=None, duration=SEGMENT_DURATION)
    y = librosa.effects.trim(y)[0]
    features = np.hstack([
        np.mean(librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40), axis=1),
        np.mean(librosa.feature.chroma_stft(y=y, sr=sr), axis=1),
        np.mean(librosa.feature.melspectrogram(y=y, sr=sr), axis=1),
        np.mean(librosa.feature.spectral_contrast(y=y, sr=sr), axis=1),
        np.mean(librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr), axis=1),
        librosa.beat.beat_track(y=y, sr=sr)[0]
    ])
    print(f"Características extraídas: {features}")
    return features

def comparar_caracteristicas(caracteristicas_referencia, caracteristicas_video):
    similitud = cosine_similarity([caracteristicas_referencia], [caracteristicas_video])[0][0]
    print(f"Similitud calculada: {similitud}")
    return similitud

def eliminar_archivo_temporal(filepath):
    try:
        Path(filepath).unlink()
        print(f"🗑️ Archivo temporal eliminado: {filepath}")
    except Exception as e:
        print(f"❌ Error al eliminar el archivo temporal: {filepath}, {e}")

def detectar_uso_no_autorizado(query, referencia_url, max_resultados):
    global coincidencias, no_coincidencias, procesando
    coincidencias = []
    no_coincidencias = []
    procesando = True

    print("\n🔎 Buscando videos en YouTube...")
    videos = buscar_videos_youtube(query, max_resultados)
    if not videos:
        print("❌ No se encontraron videos para la búsqueda.")
        procesando = False
        return

    referencia_stream = obtener_fragmento_grande(referencia_url)
    if not referencia_stream:
        print("❌ No se pudo obtener el fragmento grande del audio de referencia.")
        procesando = False
        return

    caracteristicas_referencia = extraer_caracteristicas(referencia_stream)
    if caracteristicas_referencia is None or not np.any(caracteristicas_referencia):
        print("❌ No se pudieron extraer las características de la canción de referencia.")
        procesando = False
        return

    for video in videos:
        video_url = f"https://www.youtube.com/watch?v={video['videoId']}"
        print(f"\n✅ Procesando video: {video['title']}")

        fragmento_grande = obtener_fragmento_grande(video_url)
        if not fragmento_grande:
            print("❌ No se pudo obtener el fragmento grande del audio. Saltando este video.")
            continue

        caracteristicas_video = extraer_caracteristicas(fragmento_grande)
        if caracteristicas_video is None or not np.any(caracteristicas_video):
            print("❌ No se pudieron extraer las características del video. Saltando este video.")
            continue

        similitud = comparar_caracteristicas(caracteristicas_referencia, caracteristicas_video)
        if similitud > UMBRAL_SIMILITUD:
            print(f"✅ ¡Coincidencia confirmada en el video!")
            coincidencias.append({"Título": video["title"], "Enlace": f"https://www.youtube.com/watch?v={video['videoId']}"})
        else:
            print("❌ No se encontró ninguna coincidencia clara en este video.")
            no_coincidencias.append({"Título": video["title"], "Enlace": f"https://www.youtube.com/watch?v={video['videoId']}"})

        # Cerrar y eliminar el archivo temporal después de procesar
        fragmento_grande.close()
        eliminar_archivo_temporal(fragmento_grande.name)

    procesando = False

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        query = request.form['query']
        max_resultados = int(request.form['max_resultados'])
        referencia_url = request.form['referencia_url']
        threading.Thread(target=detectar_uso_no_autorizado, args=(query, referencia_url, max_resultados)).start()
        return jsonify({"status": "Procesando..."})
    return render_template('index.html')

@app.route('/status')
def status():
    return jsonify({"procesando": procesando, "coincidencias": coincidencias, "no_coincidencias": no_coincidencias})

if __name__ == '__main__':
    Path("uploads").mkdir(parents=True, exist_ok=True)
    Path("audio_temp").mkdir(parents=True, exist_ok=True)
    app.run(debug=True)
