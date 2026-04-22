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
from ytmusicapi import YTMusic

# ─────────────────────────────────────────────
# Configuração
# ─────────────────────────────────────────────

load_dotenv()

ytmusic = YTMusic(os.getenv('YTMUSIC_BROWSER'))

cred = credentials.Certificate(os.getenv('FIREBASE_CREDENTIALS'))
firebase_admin.initialize_app(cred, {
    'storageBucket': os.getenv('FIREBASE_BUCKET')
})

BLOB_NAME      = os.getenv('BLOB_NAME', 'listening-on-ytmusic.svg')
FIREBASE_BUCKET = os.getenv('FIREBASE_BUCKET')

YouTube_Music_is_opened = None

app = Flask(__name__)
CORS(app)


# ─────────────────────────────────────────────
# Configuração dos temas
# Cada tema tem:
#   svg_template : arquivo SVG base (não modificado)
#   svg_output   : arquivo SVG gerado
#   blob_name    : nome do arquivo no Firebase Storage
#   title_class  : classe CSS do elemento de título
#   artist_class : classe CSS do elemento de artista
#   has_bars     : se o tema usa barras animadas via overwrite_bar_background
# ─────────────────────────────────────────────

THEMES = [
    {
        'name'         : 'Classic',
        'svg_template' : 'themes/YouTube_Music_UI.svg',
        'svg_output'   : 'themes/Classic_UPDATED.svg',
        'blob_name'    : BLOB_NAME,
        'title_class'  : 'artist',
        'artist_class' : 'song',
        'has_bars'     : True,
        'active_only'  : True,   # só exibido quando o YT Music está aberto
    },
    {
        'name'         : 'Recently Played',
        'svg_template' : 'themes/recentlyPlayed.svg',
        'svg_output'   : 'themes/RecentlyPlayed_UPDATED.svg',
        'blob_name'    : BLOB_NAME,
        'title_class'  : 'artist',
        'artist_class' : 'song',
        'has_bars'     : False,
        'active_only'  : False,  # só exibido quando o YT Music está fechado
    },
    {
        'name'         : 'Theme2',
        'svg_template' : 'themes/Theme2.svg',
        'svg_output'   : 'themes/Theme2_UPDATED.svg',
        'blob_name'    : 'listening-theme2.svg',
        'title_class'  : 'artist',
        'artist_class' : 'song',
        'has_bars'     : True,
        'active_only'  : None,   # exibido sempre
    },
    {
        'name'         : 'Theme3_Card',
        'svg_template' : 'themes/Theme3_Card.svg',
        'svg_output'   : 'themes/Theme3_Card_UPDATED.svg',
        'blob_name'    : 'listening-theme3-card.svg',
        'title_class'  : 'artist',
        'artist_class' : 'song',
        'has_bars'     : True,
        'active_only'  : None,   # exibido sempre
    },
]


# ─────────────────────────────────────────────
# Rota principal
# ─────────────────────────────────────────────

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

    # Busca histórico uma única vez
    recent_songs = ytmusic.get_history()
    if not recent_songs:
        return jsonify({'error': 'No history found'}), 404

    recent_song_vid_id     = recent_songs[0]['videoId']
    recent_song            = ytmusic.get_song(recent_song_vid_id)
    recent_song_title      = recent_songs[0]['title']
    recent_song_artist     = recent_song['videoDetails']['author']
    recent_song_thumb_url  = recent_song['videoDetails']['thumbnail']['thumbnails'][-1]['url']

    print(f"Música: {recent_song_title} | Artista: {recent_song_artist}")

    dominant_color = get_dominant_color_from_thumbnail(recent_song_thumb_url)
    hex_color      = rgb_to_hex(dominant_color)
    print(f"Cor dominante (HEX): {hex_color}")

    urls = {}
    bucket = storage.bucket(FIREBASE_BUCKET)

    for theme in THEMES:
        # Filtra temas pelo estado do YT Music
        if theme['active_only'] is True and not YouTube_Music_is_opened:
            continue
        if theme['active_only'] is False and YouTube_Music_is_opened:
            continue

        update_svg(
            svg_file     = theme['svg_template'],
            output_file  = theme['svg_output'],
            song_title   = recent_song_title,
            artist_name  = recent_song_artist,
            thumbnail_url= recent_song_thumb_url,
            hex_color    = hex_color,
            title_class  = theme['title_class'],
            artist_class = theme['artist_class'],
            has_bars     = theme['has_bars'],
        )

        blob = bucket.blob(theme['blob_name'])
        blob.upload_from_filename(theme['svg_output'])
        blob.make_public()
        urls[theme['name']] = blob.public_url
        print(f"[{theme['name']}] URL pública: {blob.public_url}")

    return jsonify({'message': 'SVGs updated', 'urls': urls}), 200


# ─────────────────────────────────────────────
# Função genérica de atualização de SVG
# ─────────────────────────────────────────────

def update_svg(svg_file, output_file, song_title, artist_name,
               thumbnail_url, hex_color, title_class, artist_class, has_bars):

    ns = {
        'svg'  : 'http://www.w3.org/2000/svg',
        'xlink': 'http://www.w3.org/1999/xlink',
        'xhtml': 'http://www.w3.org/1999/xhtml',
    }

    tree = etree.parse(svg_file)
    root = tree.getroot()

    base64_thumbnail = download_and_resize_image_base64(thumbnail_url)

    # Título da música
    for el in root.findall(f".//xhtml:div[@class='{title_class}']", namespaces=ns):
        el.text = song_title
    print(f"Título atualizado: {song_title}")

    # Nome do artista
    for el in root.findall(f".//xhtml:div[@class='{artist_class}']", namespaces=ns):
        el.text = artist_name
    print(f"Artista atualizado: {artist_name}")

    # Thumbnail
    for el in root.findall(".//xhtml:a[@target='_BLANK']//xhtml:img", namespaces=ns):
        el.attrib['src'] = base64_thumbnail
    print("Thumbnail atualizada")

    # Status "Now playing" / "Recently played"
    label = "Now playing on" if YouTube_Music_is_opened else "Recently played on"
    for el in root.findall(".//xhtml:div[@class='playing']", namespaces=ns):
        el.text = label
    print(f"Status atualizado: {label}")

    tree.write(output_file, pretty_print=True)

    # Cor das barras (temas que usam overwrite)
    if has_bars:
        overwrite_bar_color(output_file, output_file, hex_color)


# ─────────────────────────────────────────────
# Utilitários
# ─────────────────────────────────────────────

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
    """Substitui a cor de fundo das barras animadas no bloco CSS interno."""
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