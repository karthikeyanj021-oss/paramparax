"""
ParamparaX SIH prototype - backend (Flask + SQLite).

Stores:
  - user signups (mobile number + state)
  - a community photo gallery (caption + image file)

Run (from this folder):
    pip install flask
    python app.py

The Flask server now serves the whole site (HTML/CSS/JS from the repo
root) plus the API and uploads on a single origin, and binds to 0.0.0.0
so anyone on the network can open http://<this-machine-ip>:5000/

Endpoints:
  POST /api/users    {"phone":"10 digit","state":"Telangana"}
  GET  /api/users
  GET  /api/gallery
  POST /api/gallery  multipart: file=<image> caption=<text>
  GET  /uploads/<filename>
"""
import os
import sqlite3
import time
from flask import Flask, request, jsonify, send_from_directory, g

import doc_kb

BASE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.normpath(os.path.join(BASE, '..'))
ASSET_DIR = os.path.join(SITE_DIR, 'assets')
DB = os.path.join(BASE, 'virasat.db')
UPLOAD_DIR = os.path.join(BASE, 'uploads')
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
MAX_BYTES = 8 * 1024 * 1024

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_BYTES

os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS gallery(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                caption TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
        ''')


@app.after_request
def cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return resp


@app.route('/api/users', methods=['GET', 'POST', 'OPTIONS'])
def users():
    if request.method == 'OPTIONS':
        return ('', 204)
    if request.method == 'GET':
        rows = get_db().execute('SELECT * FROM users ORDER BY id DESC').fetchall()
        return jsonify([dict(r) for r in rows])
    data = request.get_json(silent=True) or {}
    phone = str(data.get('phone', '') or '').strip()
    state = str(data.get('state', '') or '').strip()
    if not phone.isdigit() or len(phone) != 10 or phone[0] not in '6789':
        return jsonify({'ok': False, 'error': 'invalid_phone'}), 400
    try:
        cur = get_db().execute(
            'INSERT INTO users(phone, state, created_at) VALUES(?,?,?)',
            (phone, state, time.strftime('%Y-%m-%d %H:%M:%S')))
        get_db().commit()
        return jsonify({'ok': True, 'id': cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'error': 'duplicate_phone'}), 409
    except sqlite3.Error:
        return jsonify({'ok': False, 'error': 'db_error'}), 500


@app.route('/api/gallery', methods=['GET', 'POST', 'OPTIONS'])
def gallery():
    if request.method == 'OPTIONS':
        return ('', 204)
    if request.method == 'GET':
        rows = get_db().execute('SELECT * FROM gallery ORDER BY id DESC').fetchall()
        return jsonify([dict(r) for r in rows])
    f = request.files.get('file')
    caption = (request.form.get('caption') or '').strip()[:200]
    if not f or f.filename == '':
        return jsonify({'ok': False, 'error': 'no_file'}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({'ok': False, 'error': 'bad_type'}), 415
    name = '{}_{}'.format(int(time.time() * 1000), os.path.basename(f.filename).replace(' ', '_'))
    f.save(os.path.join(UPLOAD_DIR, name))
    try:
        cur = get_db().execute(
            'INSERT INTO gallery(filename, caption, created_at) VALUES(?,?,?)',
            (name, caption, time.strftime('%Y-%m-%d %H:%M:%S')))
        get_db().commit()
    except sqlite3.Error:
        try:
            os.remove(os.path.join(UPLOAD_DIR, name))
        except OSError:
            pass
        return jsonify({'ok': False, 'error': 'db_error'}), 500
    return jsonify({'ok': True, 'id': cur.lastrowid, 'filename': name}), 201


@app.route('/uploads/<path:name>')
def uploaded_file(name):
    return send_from_directory(UPLOAD_DIR, name)


@app.route('/api/doc/sections')
def doc_sections():
    """List the sections ingested from the project concept document."""
    return jsonify({'sections': doc_kb.doc_sections()})


@app.route('/api/doc/section/<int:sid>')
def doc_section(sid):
    """Full text of one document section by id (1..17)."""
    s = doc_kb.doc_section(sid)
    if s is None:
        return jsonify({'ok': False, 'error': 'no_such_section'}), 404
    for k in ('tokens', 'stem_set', 'heading_words', 'heading_stems'):
        s.pop(k, None)
    return jsonify({'ok': True, 'section': s})


@app.route('/api/doc/search')
def doc_search():
    """Token-overlap retrieval over the ingested document.

    Query params: q=<text>, n=<top results, default 3>
    Returns ranked sections so the chatbot can answer with source-grounded
    excerpts instead of hallucinated content.
    """
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'ok': False, 'error': 'missing_q'}), 400
    try:
        n = max(1, min(int(request.args.get('n', 3)), 5))
    except ValueError:
        n = 3
    results = doc_kb.doc_search(q, top_n=n)
    for r in results:
        for k in ('tokens', 'stem_set', 'heading_words', 'heading_stems'):
            r['section'].pop(k, None)
    return jsonify({'ok': True, 'query': q, 'results': results})


@app.route('/')
def index():
    """Serve the public ParamparaX site from the repository root."""
    return send_from_directory(SITE_DIR, 'index.html')


@app.route('/assets/<path:name>')
def site_assets(name):
    return send_from_directory(ASSET_DIR, name)


@app.route('/<path:name>')
def site_pages(name):
    full = os.path.normpath(os.path.join(SITE_DIR, name))
    if full.startswith(os.path.normpath(SITE_DIR)) and os.path.isfile(full):
        return send_from_directory(SITE_DIR, name)
    return jsonify({'ok': False, 'error': 'not_found'}), 404


init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False, threaded=True)