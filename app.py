import base64
from colorthief import ColorThief
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, storage
from flask import Flask, jsonify, request
from flask_cors import CORS
from io import BytesIO
from lxml import etree
import os
from PIL import Image
import re
import requests
from threading import Lock
from ytmusicapi import YTMusic


load_dotenv()

upload_lock = Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ytmusic = YTMusic(os.getenv('YTMUSIC_BROWSER'))

cred = credentials.Certificate(os.getenv('FIREBASE_CREDENTIALS'))
firebase_admin.initialize_app(cred, {
    'storageBucket': os.getenv('FIREBASE_BUCKET')
})

BLOB_NAME       = os.getenv('BLOB_NAME', 'listening-on-ytmusic.svg')
FIREBASE_BUCKET = os.getenv('FIREBASE_BUCKET')

YouTube_Music_is_opened = None

app = Flask(__name__)
CORS(app)

THEMES = [
    {
        'name'         : 'Theme_Card_HTML',
        'svg_template' : os.path.join(BASE_DIR, 'themes', 'Theme_Card_HTML.html'),
        'svg_output'   : os.path.join(BASE_DIR, 'themes', 'Theme_Card_HTML_UPDATED.svg'),
        'blob_name'    : 'listening-on-ytmusic.svg',
        'title_class'  : 'artist',
        'artist_class' : 'song',
        'has_bars'     : True,
        'active_only'  : None,
    },
]


@app.route('/status', methods=['POST'])
def receive_status():
    global YouTube_Music_is_opened

    status = request.json.get('status')
    print(f"YouTube Music status: {status}")

    if status == "Off":
        YouTube_Music_is_opened = False
    elif status == "Open":
        YouTube_Music_is_opened = True
    else:
        print("Status desconhecido, ignorando.")
        return "Status received", 200

    print(f"YouTube_Music_is_opened = {YouTube_Music_is_opened}")

    recent_songs = ytmusic.get_history()
    if not recent_songs:
        return jsonify({'error': 'No history found'}), 404

    recent_song_vid_id    = recent_songs[0]['videoId']
    recent_song           = ytmusic.get_song(recent_song_vid_id)
    recent_song_title     = recent_songs[0]['title']
    recent_song_artist    = recent_song['videoDetails']['author']
    recent_song_thumb_url = recent_song['videoDetails']['thumbnail']['thumbnails'][-1]['url']

    print(f"Música: {recent_song_title} | Artista: {recent_song_artist}")

    dominant_color = get_dominant_color_from_thumbnail(recent_song_thumb_url)
    hex_color      = rgb_to_hex(dominant_color)
    print(f"Cor dominante (HEX): {hex_color}")

    urls   = {}
    bucket = storage.bucket(FIREBASE_BUCKET)

    for theme in THEMES:
        if theme['active_only'] is True and not YouTube_Music_is_opened:
            continue
        if theme['active_only'] is False and YouTube_Music_is_opened:
            continue

        update_svg(
            svg_file      = theme['svg_template'],
            output_file   = theme['svg_output'],
            song_title    = recent_song_title,
            artist_name   = recent_song_artist,
            thumbnail_url = recent_song_thumb_url,
            hex_color     = hex_color,
            title_class   = theme['title_class'],
            artist_class  = theme['artist_class'],
            has_bars      = theme['has_bars'],
        )

        with upload_lock:
            blob = bucket.blob(theme['blob_name'])
            try:
                blob.delete()
            except Exception:
                pass
            blob.upload_from_filename(
                theme['svg_output'],
                content_type='image/svg+xml',
            )
            blob.cache_control = "no-cache, no-store, must-revalidate"
            blob.patch()

        # Recarrega os metadados do blob do servidor
        print(f"public_url: {blob.public_url}")
        print(f"content_type no servidor: {blob.content_type}")
        print(f"cache_control no servidor: {blob.cache_control}")

        print(f"[{theme['name']}] URL pública: {blob.public_url}")

    return jsonify({'message': 'SVGs updated', 'urls': urls}), 200


def safe_sub(class_name, new_text, content):
    def replacer(m):
        return m.group(1) + new_text
    return re.sub(
        r'(class="' + class_name + r'"[^>]*>)[^<]*',
        replacer,
        content
    )   

# Em update_svg, remova a condição especial para .html:
def update_svg(svg_file, output_file, song_title, artist_name,
               thumbnail_url, hex_color, title_class, artist_class, has_bars):

    # Agora trata direto como SVG (não precisa mais do if .html)
    with open(svg_file, 'r', encoding='utf-8') as f:
        content = f.read()

    base64_thumbnail = download_and_resize_image_base64(thumbnail_url)

    content = safe_sub(title_class, song_title, content)
    content = safe_sub(artist_class, artist_name, content)

    parts = content.split('class="thumb"', 1)
    if len(parts) == 2:
        after_thumb = re.sub(r'src="[^"]*"', f'src="{base64_thumbnail}"', parts[1], count=1)
        content = parts[0] + 'class="thumb"' + after_thumb

    label = "Now playing on" if YouTube_Music_is_opened else "Recently played on"
    content = safe_sub('playing', label, content)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)

    if has_bars:
        overwrite_bar_color(output_file, output_file, hex_color)


def update_html(svg_file, output_file, song_title, artist_name,
                thumbnail_url, hex_color, title_class, artist_class, has_bars):

    with open(svg_file, 'r', encoding='utf-8') as f:
        content = f.read()

    base64_thumbnail = download_and_resize_image_base64(thumbnail_url)

    # Título
    content = re.sub(
        r'(class="' + title_class + r'"[^>]*>)[^<]*',
        lambda m: m.group(1) + song_title,
        content
    )

    # Artista
    content = re.sub(
        r'(class="' + artist_class + r'"[^>]*>)[^<]*',
        lambda m: m.group(1) + artist_name,
        content
    )

    # Thumbnail — divide em 2 partes pelo marcador "class="thumb""
    # e substitui o src apenas dentro da tag da thumbnail
    parts = content.split('class="thumb"', 1)
    if len(parts) == 2:
        before_thumb = parts[0]
        after_thumb  = parts[1]
        # dentro de after_thumb, substitui o próximo src="..."
        after_thumb = re.sub(
            r'src="[^"]*"',
            f'src="{base64_thumbnail}"',
            after_thumb,
            count=1
        )
        content = before_thumb + 'class="thumb"' + after_thumb
    print("Thumbnail atualizada")

    # Status label
    label = "Now playing on" if YouTube_Music_is_opened else "Recently played on"
    content = re.sub(
        r'(class="playing"[^>]*>)[^<]*',
        lambda m: m.group(1) + label,
        content
    )

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)

    if has_bars:
        overwrite_bar_color(output_file, output_file, hex_color)


def download_and_resize_image_base64(image_url, size=(300, 300)):
    response = requests.get(image_url, timeout=10)
    img = Image.open(BytesIO(response.content)).resize(size, Image.LANCZOS)
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode("utf-8")


def get_dominant_color_from_thumbnail(thumbnail_url):
    response = requests.get(thumbnail_url, timeout=10)
    return ColorThief(BytesIO(response.content)).get_color(quality=1)


def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(rgb[0], rgb[1], rgb[2])


def overwrite_bar_color(svg_file, output_file, new_color):
    try:
        with open(svg_file, 'r', encoding='utf-8') as f:
            content = f.read()

        style_block = f""".bar {{
    background: {new_color};
    bottom: 1px;
    height: 3px;
    position: absolute;
    width: 3px;
    animation: sound 0ms -800ms linear infinite alternate;
}}"""

        updated = re.sub(r'\.bar\s*\{[^}]*\}', style_block, content)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(updated)

        print(f"Cor das barras atualizada para {new_color}")

    except Exception as e:
        print(f"Erro ao atualizar cor das barras: {e}")


if __name__ == '__main__':
    app.run(port=5000)