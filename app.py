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

app = Flask(__name__)
app.secret_key = 'your secret key'

def crossfade(clip1, clip2, fade_duration):
    clip1 = fadeout(clip1, fade_duration)
    clip2 = fadein(clip2, fade_duration)
    return CompositeVideoClip([clip1, clip2.set_start(clip1.duration - fade_duration)])

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.execute('CREATE TABLE IF NOT EXISTS users (name TEXT, username TEXT, email TEXT, password TEXT, images TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS images (image_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, image BLOB, metadata TEXT, mimetype TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS audio (data BLOB, metadata TEXT)')
    conn.row_factory = sqlite3.Row
    return conn

@app.before_request
def upload_audio_files():
    if not getattr(g, 'audio_files_uploaded', None):
        conn = get_db_connection()
        audio_folder = 'audio'
        for filename in os.listdir(audio_folder):
            if filename.endswith('.mp3') or filename.endswith('.wav'):
                with open(os.path.join(audio_folder, filename), 'rb') as f:
                    audio_data = f.read()
                audio = conn.execute('SELECT * FROM audio WHERE metadata = ?', (filename,)).fetchone()
                if audio is None:
                    conn.execute('INSERT INTO audio (data, metadata) VALUES (?, ?)', (audio_data, filename))
                    print('Audio uploaded: ' + filename)
                else:
                    print('Audio already loaded: ' + filename)
        conn.commit()
        conn.close()
        g.audio_files_uploaded = True

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'username' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        images = request.files.getlist('images')
        conn = get_db_connection()
        for image in images:
            conn.execute('INSERT INTO images (username, image, metadata, mimetype) VALUES (?, ?, ?, ?)',
                         (session['username'], image.read(), image.filename, image.content_type))
            conn.commit()
            image_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            user_images = conn.execute('SELECT images FROM users WHERE username = ?', (session['username'],)).fetchone()[0]
            if user_images:
                user_images += ',' + str(image_id)
            else:
                user_images = str(image_id)
            conn.execute('UPDATE users SET images = ? WHERE username = ?', (user_images, session['username']))
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
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user is None:
            conn.execute('INSERT INTO users (name, username, email, password, images) VALUES (?, ?, ?, ?, ?)',
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
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user is None:
            error = 'User does not have an account.'
        else:
            if check_password_hash(user['password'], password):
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
    user_images = conn.execute('SELECT images FROM users WHERE username = ?', (session['username'],)).fetchone()[0]
    image_ids = user_images.split(',')
    images_and_mimetypes = []
    for image_id in image_ids:
        row = conn.execute('SELECT image, mimetype FROM images WHERE image_id = ?', (image_id,)).fetchone()
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
    slideshow_path = None
    if request.method == 'POST':
        image_ids = request.form.getlist('image_ids')
        transition_values = request.form.get('transitions')
        audio_file_name = request.form.get('audio')

        images = []
        print(image_ids)
        print(audio_file_name)
        for image_id in image_ids:
            row = conn.execute('SELECT image FROM images WHERE image_id = ?', (image_id,)).fetchone()
            if row is not None:
                image = Image.open(io.BytesIO(row[0]))
                image = image.resize((640, 480))  # Resize the image to 640x480
                image = np.array(image)  # Convert the image to a Numpy array
                images.append(image)

        audio_row = conn.execute('SELECT data FROM audio WHERE metadata = ?', (audio_file_name,)).fetchone()
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

    user_images = conn.execute('SELECT images FROM users WHERE username = ?', (session['username'],)).fetchone()[0]
    image_ids = user_images.split(',')
    images = []
    mimetypes = []
    for image_id in image_ids:
        row = conn.execute('SELECT image, mimetype FROM images WHERE image_id = ?', (image_id,)).fetchone()
        if row is not None:
            image = base64.b64encode(row[0]).decode('ascii')
            images.append(image)
            mimetypes.append(row[1])
    audios = [row['metadata'] for row in conn.execute('SELECT metadata FROM audio').fetchall()]
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