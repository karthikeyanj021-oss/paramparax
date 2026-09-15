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
  POST /api/auth/register  {"username","password","state?"}
  POST /api/auth/login     {"username","password"}
  POST /api/auth/logout    (Bearer token)
  GET  /api/auth/me        (Bearer token)
  GET/POST /api/favs       Bearer token; POST {"item"} / DELETE /api/favs/<item>
  GET/POST/DELETE /api/chat  Bearer token; POST {"role","text"}
  POST /api/users    {"phone":"10 digit","state":"Telangana"}  (legacy signup)
  GET  /api/users
  GET  /api/gallery        (public)
  POST /api/gallery        multipart: file=<image> caption=<text>  (login required)
  GET  /uploads/<filename>
"""
import os
import re
import secrets
import sqlite3
import time
from flask import Flask, request, jsonify, send_from_directory, g
from werkzeug.security import generate_password_hash, check_password_hash

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
            CREATE TABLE IF NOT EXISTS accounts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                pass_hash TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions(
                token TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS favourites(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                item TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(account_id, item)
            );
            CREATE TABLE IF NOT EXISTS chat_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
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
    acc = token_account()
    if not acc:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
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


def token_account():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    row = get_db().execute(
        'SELECT a.* FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.token=?',
        (auth[7:].strip(),)).fetchone()
    return row


def make_session(account_id):
    token = secrets.token_hex(32)
    get_db().execute('INSERT INTO sessions(token, account_id, created_at) VALUES(?,?,?)',
                     (token, account_id, time.strftime('%Y-%m-%d %H:%M:%S')))
    get_db().commit()
    return token


USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,24}$')


@app.route('/api/auth/register', methods=['POST', 'OPTIONS'])
def auth_register():
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '') or '').strip()
    password = str(data.get('password', '') or '')
    state = str(data.get('state', '') or '').strip()
    if not USERNAME_RE.match(username):
        return jsonify({'ok': False, 'error': 'bad_username'}), 400
    if len(password) < 6:
        return jsonify({'ok': False, 'error': 'short_password'}), 400
    try:
        cur = get_db().execute(
            'INSERT INTO accounts(username, pass_hash, state, created_at) VALUES(?,?,?,?)',
            (username, generate_password_hash(password), state[:100],
             time.strftime('%Y-%m-%d %H:%M:%S')))
        get_db().commit()
        token = make_session(cur.lastrowid)
        return jsonify({'ok': True, 'token': token, 'username': username}), 201
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'error': 'taken'}), 409
    except sqlite3.Error:
        return jsonify({'ok': False, 'error': 'db_error'}), 500


@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def auth_login():
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '') or '').strip()
    password = str(data.get('password', '') or '')
    acc = get_db().execute('SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
    if not acc or not check_password_hash(acc['pass_hash'], password):
        return jsonify({'ok': False, 'error': 'bad_credentials'}), 401
    token = make_session(acc['id'])
    return jsonify({'ok': True, 'token': token, 'username': acc['username'], 'state': acc['state']})


@app.route('/api/auth/logout', methods=['POST', 'OPTIONS'])
def auth_logout():
    if request.method == 'OPTIONS':
        return ('', 204)
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        get_db().execute('DELETE FROM sessions WHERE token=?', (auth[7:].strip(),))
        get_db().commit()
    return jsonify({'ok': True})


@app.route('/api/auth/me', methods=['GET', 'OPTIONS'])
def auth_me():
    if request.method == 'OPTIONS':
        return ('', 204)
    acc = token_account()
    if not acc:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    return jsonify({'ok': True, 'username': acc['username'], 'state': acc['state']})


@app.route('/api/favs', methods=['GET', 'POST', 'OPTIONS'])
def favs():
    if request.method == 'OPTIONS':
        return ('', 204)
    acc = token_account()
    if not acc:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    if request.method == 'GET':
        rows = get_db().execute('SELECT item FROM favourites WHERE account_id=?', (acc['id'],)).fetchall()
        return jsonify({'ok': True, 'favs': [r['item'] for r in rows]})
    data = request.get_json(silent=True) or {}
    item = str(data.get('item', '') or '').strip()
    if not item:
        return jsonify({'ok': False, 'error': 'missing_item'}), 400
    try:
        get_db().execute('INSERT OR IGNORE INTO favourites(account_id, item, created_at) VALUES(?,?,?)',
                         (acc['id'], item, time.strftime('%Y-%m-%d %H:%M:%S')))
        get_db().commit()
        return jsonify({'ok': True})
    except sqlite3.Error:
        return jsonify({'ok': False, 'error': 'db_error'}), 500


@app.route('/api/favs/<path:item>', methods=['DELETE', 'OPTIONS'])
def fav_delete(item):
    if request.method == 'OPTIONS':
        return ('', 204)
    acc = token_account()
    if not acc:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    get_db().execute('DELETE FROM favourites WHERE account_id=? AND item=?', (acc['id'], item))
    get_db().commit()
    return jsonify({'ok': True})


@app.route('/api/chat', methods=['GET', 'POST', 'DELETE', 'OPTIONS'])
def chat_log():
    if request.method == 'OPTIONS':
        return ('', 204)
    acc = token_account()
    if not acc:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    if request.method == 'GET':
        rows = get_db().execute(
            'SELECT role, text FROM chat_log WHERE account_id=? ORDER BY id ASC', (acc['id'],)).fetchall()
        return jsonify({'ok': True, 'messages': [dict(r) for r in rows]})
    if request.method == 'DELETE':
        get_db().execute('DELETE FROM chat_log WHERE account_id=?', (acc['id'],))
        get_db().commit()
        return jsonify({'ok': True})
    data = request.get_json(silent=True) or {}
    role = str(data.get('role', ''))
    text = str(data.get('text', '') or '').strip()
    if role not in ('user', 'bot') or not text:
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    if len(text) > 20000:
        text = text[:20000]
    get_db().execute('INSERT INTO chat_log(account_id, role, text, created_at) VALUES(?,?,?,?)',
                     (acc['id'], role, text, time.strftime('%Y-%m-%d %H:%M:%S')))
    get_db().commit()
    return jsonify({'ok': True})


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