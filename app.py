import os
from flask import Flask, render_template, request, redirect, url_for, session, g
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import base64
from moviepy.editor import ImageSequenceClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, ImageClip
from moviepy.video.fx.all import fadein, fadeout
from PIL import Image, UnidentifiedImageError
import numpy as np
import io
import tempfile
from time import time
import psycopg2

app = Flask(__name__)
app.secret_key = 'your secret key'

def crossfade(clip1, clip2, fade_duration):
    clip1 = fadeout(clip1, fade_duration)
    clip2 = fadein(clip2, fade_duration)
    return CompositeVideoClip([clip1, clip2.set_start(clip1.duration - fade_duration)])

# def get_db_connection():
#     conn = sqlite3.connect('database.db')
#     conn.execute('CREATE TABLE IF NOT EXISTS users (name TEXT, username TEXT, email TEXT, password TEXT, images TEXT)')
#     conn.execute('CREATE TABLE IF NOT EXISTS images (image_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, image BLOB, metadata TEXT, mimetype TEXT)')
#     conn.execute('CREATE TABLE IF NOT EXISTS audio (data BLOB, metadata TEXT)')
#     conn.row_factory = sqlite3.Row
#     return conn

def get_db_connection():
    conn = psycopg2.connect("postgresql://manitroy:hZoVrgVUlm5JV81h3rtraQ@issproject-4067.7s5.aws-ap-south-1.cockroachlabs.cloud:26257/img2vdo?sslmode=verify-full")
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS users (name TEXT, username TEXT, email TEXT, password TEXT, images TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS images (image_id SERIAL PRIMARY KEY, username TEXT, image BYTEA, metadata TEXT, mimetype TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS audio (data BYTEA, metadata TEXT)')
    conn.commit()
    return conn

def upload_audio_files():
    conn = get_db_connection()
    cur=conn.cursor()
    audio_folder = 'audio'
    for filename in os.listdir(audio_folder):
        if filename.endswith('.mp3') or filename.endswith('.wav'):
            with open(os.path.join(audio_folder, filename), 'rb') as f:
                audio_data = f.read()
            cur.execute('SELECT * FROM audio WHERE metadata = %s', (filename,))
            audio = cur.fetchone()
            if audio is None:
                cur.execute('INSERT INTO audio (data, metadata) VALUES (%s, %s)', (audio_data, filename))
                print('Audio uploaded: ' + filename)
    conn.commit()
    conn.close()

upload_audio_files()

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'username' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        images = request.files.getlist('images')
        conn = get_db_connection()
        cur=conn.cursor()
        for image in images:
            cur.execute('INSERT INTO images (username, image, metadata, mimetype) VALUES (%s, %s, %s, %s) RETURNING image_id',
            (session['username'], image.read(), image.filename, image.content_type))
            conn.commit()
            image_id = cur.fetchone()[0]
            cur.execute('SELECT images FROM users WHERE username = %s', (session['username'],))
            user_images = cur.fetchone()[0]
            if user_images:
                user_images += ',' + str(image_id)
            else:
                user_images = str(image_id)
            cur.execute('UPDATE users SET images = %s WHERE username = %s', (user_images, session['username']))
            conn.commit()
        conn.close()
        return redirect(url_for('home'))

    return render_template('upload.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        conn = get_db_connection()
        cur=conn.cursor()
        cur.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cur.fetchone()
        if user is None:
            cur.execute('INSERT INTO users (name, username, email, password, images) VALUES (%s, %s, %s, %s, %s)',
            (name, username, email, password, ''))
            conn.commit()
            conn.close()
            return redirect(url_for('home'))
        else:
            error = 'User already exists.'
    return render_template('signup.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cur=conn.cursor()
        cur.execute('SELECT password FROM users WHERE username = %s', (username,))
        user = cur.fetchone()
        conn.close()

        if user is None:
            error = 'User does not have an account.'
        else:
            if check_password_hash(user[0], password):
                session['username'] = username
                session['password'] = password
                return redirect(url_for('home'))
            else:
                error = 'Wrong password.'
    return render_template('login.html', error=error)

@app.route('/home')
def home():
    if 'username' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur=conn.cursor()
    cur.execute('SELECT images FROM users WHERE username = %s', (session['username'],))
    user_images = cur.fetchone()[0]
    image_ids = user_images.split(',')
    images_and_mimetypes = []
    for image_id in image_ids:
        if image_id:  # Skip the query if image_id is an empty string
            cur.execute('SELECT image, mimetype FROM images WHERE image_id = %s', (image_id,))
            row = cur.fetchone()
            if row is not None:
                image = base64.b64encode(row[0]).decode('ascii')
                images_and_mimetypes.append((image, row[1]))
    conn.close()

    return render_template('home.html', username=session['username'], images_and_mimetypes=images_and_mimetypes)

@app.route('/create', methods=['GET', 'POST'])
def create():
    if 'username' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur=conn.cursor()
    slideshow_path = None
    if request.method == 'POST':
        image_ids = request.form.getlist('image_ids')
        transition_values = request.form.get('transitions')
        audio_file_name = request.form.get('audio')

        images = []
        print(image_ids)
        print(audio_file_name)
        for image_id in image_ids:
            cur.execute('SELECT image FROM images WHERE image_id = %s', (image_id,))
            row = cur.fetchone()
            if row is not None:
                image = Image.open(io.BytesIO(row[0]))
                image = image.resize((640, 480))  # Resize the image to 640x480
                image = np.array(image)  # Convert the image to a Numpy array
                images.append(image)

        cur.execute('SELECT data FROM audio WHERE metadata = %s', (audio_file_name,))
        audio_row = cur.fetchone()
        if audio_row is not None:
            audio_blob = audio_row[0]
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
                temp_audio.write(audio_blob)
                temp_audio.flush()
                audio = AudioFileClip(temp_audio.name)
        else:
            return "Audio file not found", 400
        
        if images:
            clips = []
            for i, image in enumerate(images):
                clip = ImageClip(image, duration=2)
                if i > 0 and transition_values == 'cross_fade':
                    clips[i-1] = crossfade(clips[i-1], clip, 1)  # 1 second crossfade
                else:
                    if transition_values == 'fade_in':
                        clip = fadein(clip, 1)  # 1 second fade-in
                    elif transition_values == 'fade_out':
                        clip = fadeout(clip, 1)  # 1 second fade-out
                clips.append(clip)

            slideshow = concatenate_videoclips(clips, method="compose")
            slideshow.fps = 24  

            audio = AudioFileClip(os.path.join('audio', audio_file_name))
            if audio.duration > slideshow.duration:
                audio = audio.subclip(0, slideshow.duration)  
            slideshow = slideshow.set_audio(audio)

            slideshow.write_videofile(os.path.join('static', 'slideshow.mp4'), fps=24) 

            slideshow_path = os.path.join('static', 'slideshow.mp4')
        else:
            return "No images found", 400

    cur.execute('SELECT images FROM users WHERE username = %s', (session['username'],))
    user_images = cur.fetchone()[0]
    image_ids = user_images.split(',')
    images = []
    mimetypes = []
    for image_id in image_ids:
        cur.execute('SELECT image, mimetype FROM images WHERE image_id = %s', (image_id,))
        row = cur.fetchone()
        if row is not None:
            image = base64.b64encode(row[0]).decode('ascii')
            images.append(image)
            mimetypes.append(row[1])
    cur.execute('SELECT metadata FROM audio')
    rows = cur.fetchall()
    audios = [row[0] for row in rows]
    conn.close()

    return render_template('create.html', username=session['username'], images=images, image_ids=image_ids, audios=audios, mimetypes=mimetypes, slideshow_path=slideshow_path, time=time)

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    session.pop('password', None)
    return redirect(url_for('login'))

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)