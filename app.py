"""TaskNest: self-hosted task manager with PostgreSQL and account authentication."""
import hashlib
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL,
 category TEXT NOT NULL, due_date TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
 email TEXT PRIMARY KEY, attempts INTEGER NOT NULL, window_start BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_user_idx ON tasks(user_id);
"""


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        DATABASE_URL=os.environ.get('DATABASE_URL'),
        SQLITE_PATH=os.environ.get('SQLITE_PATH', 'instance/tasknest.db'),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', 'false').lower() == 'true',
        MAX_CONTENT_LENGTH=16384,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32:
        raise RuntimeError('Set SECRET_KEY to a random value of at least 32 characters. See README.md.')

    def db():
        if 'db' not in g:
            if app.config['DATABASE_URL']:
                import psycopg
                from psycopg.rows import dict_row
                g.db = psycopg.connect(app.config['DATABASE_URL'], row_factory=dict_row)
            else:
                Path(app.config['SQLITE_PATH']).parent.mkdir(parents=True, exist_ok=True)
                g.db = sqlite3.connect(app.config['SQLITE_PATH'])
                g.db.row_factory = sqlite3.Row
                g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    def query(sql, args=()):
        return db().execute(sql.replace('?', '%s') if app.config['DATABASE_URL'] else sql, args)

    @app.teardown_appcontext
    def close_db(error=None):
        connection = g.pop('db', None)
        if connection is not None:
            connection.close()

    @app.cli.command('init-db')
    def init_db():
        for statement in SCHEMA.split(';'):
            if statement.strip():
                query(statement)
        db().commit()
        print('Database initialized.')

    def csrf_token():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        return session['csrf']

    @app.context_processor
    def context():
        return {'csrf_token': csrf_token, 'today': date.today().isoformat()}

    @app.before_request
    def authenticate():
        g.user = None
        if request.method == 'POST':
            supplied = request.form.get('csrf', '')
            if not supplied or not secrets.compare_digest(supplied, session.get('csrf', '')):
                abort(400, description='This form expired. Refresh the page and try again.')
        token = session.get('auth_token')
        if token:
            g.user = query('SELECT users.* FROM users JOIN sessions ON users.id=sessions.user_id WHERE token_hash=? AND expires>?',
                           (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped

    def sign_in(user_id):
        session.clear()
        token = secrets.token_urlsafe(32)
        query('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
        query('INSERT INTO sessions(token_hash,user_id,expires) VALUES(?,?,?)',
              (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time()) + 43200))
        db().commit()
        session['auth_token'] = token

    @app.get('/health')
    def health():
        try:
            query('SELECT 1 FROM users LIMIT 1')
            return {'status': 'ok'}
        except Exception:
            return {'status': 'unavailable'}, 503

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if g.user:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            if not 1 <= len(name) <= 60 or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                flash('Enter your name and a valid email address.', 'error')
            elif not 10 <= len(password) <= 128:
                flash('Use a password between 10 and 128 characters.', 'error')
            else:
                user_id = str(uuid.uuid4())
                inserted = query('INSERT INTO users(id,name,email,password_hash) VALUES(?,?,?,?) ON CONFLICT(email) DO NOTHING',
                                 (user_id, name, email, generate_password_hash(password))).rowcount
                db().commit()
                if inserted:
                    sign_in(user_id)
                    flash('Your workspace is ready. Add your first task.', 'success')
                    return redirect(url_for('dashboard'))
                flash('Unable to create this account. Try signing in instead.', 'error')
        return render_template('auth.html', mode='register')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if g.user:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            email = request.form.get('email', '').strip().lower()[:254]
            password = request.form.get('password', '')
            now = int(time.time())
            attempt = query('SELECT * FROM login_attempts WHERE email=?', (email,)).fetchone()
            if attempt and attempt['window_start'] > now - 900 and attempt['attempts'] >= 10:
                flash('Too many attempts. Try again in 15 minutes.', 'error')
                return render_template('auth.html', mode='login'), 429
            user = query('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            # Always check a hash so unknown accounts do not bypass the costly password check.
            valid = check_password_hash(user['password_hash'] if user else dummy_hash, password[:128])
            if user and valid and len(password) <= 128:
                query('DELETE FROM login_attempts WHERE email=?', (email,))
                sign_in(user['id'])
                return redirect(url_for('dashboard'))
            count = attempt['attempts'] + 1 if attempt and attempt['window_start'] > now - 900 else 1
            start = attempt['window_start'] if count > 1 else now
            query('INSERT INTO login_attempts(email,attempts,window_start) VALUES(?,?,?) ON CONFLICT(email) DO UPDATE SET attempts=excluded.attempts, window_start=excluded.window_start', (email, count, start))
            query('DELETE FROM login_attempts WHERE window_start<?', (now - 900,))
            db().commit()
            flash('Email or password is incorrect.', 'error')
        return render_template('auth.html', mode='login')

    @app.post('/logout')
    @login_required
    def logout():
        query('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(session['auth_token'].encode()).hexdigest(),))
        db().commit()
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @login_required
    def dashboard():
        tasks = query('SELECT * FROM tasks WHERE user_id=? ORDER BY done, CASE WHEN due_date=\'\' THEN 1 ELSE 0 END, due_date, created_at DESC', (g.user['id'],)).fetchall()
        view = request.args.get('view', 'all')
        if view not in ('all', 'active', 'done'):
            view = 'all'
        filtered = [t for t in tasks if view == 'all' or bool(t['done']) == (view == 'done')]
        stats = {'all': len(tasks), 'done': sum(t['done'] for t in tasks),
                 'due': sum(not t['done'] and t['due_date'] == date.today().isoformat() for t in tasks)}
        stats['active'] = stats['all'] - stats['done']
        return render_template('dashboard.html', tasks=filtered, stats=stats, view=view)

    @app.post('/tasks')
    @login_required
    def add_task():
        title = request.form.get('title', '').strip()
        category = request.form.get('category', 'Personal')
        due = request.form.get('due_date', '')
        try:
            if due:
                date.fromisoformat(due)
            if not 1 <= len(title) <= 160 or category not in ('Personal', 'Study', 'Work'):
                raise ValueError()
        except ValueError:
            flash('Enter a task up to 160 characters, a valid category and a valid date.', 'error')
            return redirect(url_for('dashboard'))
        query('INSERT INTO tasks(id,user_id,title,category,due_date,created_at) VALUES(?,?,?,?,?,?)',
              (str(uuid.uuid4()), g.user['id'], title, category, due, datetime.now(timezone.utc).isoformat()))
        db().commit()
        flash('Task added.', 'success')
        return redirect(url_for('dashboard'))

    @app.post('/tasks/<task_id>/<action>')
    @login_required
    def change_task(task_id, action):
        if action not in ('toggle', 'delete'):
            abort(404)
        task = query('SELECT id FROM tasks WHERE id=? AND user_id=?', (task_id, g.user['id'])).fetchone()
        if task is None:
            abort(404)
        if action == 'toggle':
            query('UPDATE tasks SET done=1-done WHERE id=? AND user_id=?', (task_id, g.user['id']))
        else:
            query('DELETE FROM tasks WHERE id=? AND user_id=?', (task_id, g.user['id']))
        db().commit()
        return redirect(url_for('dashboard'))

    dummy_hash = generate_password_hash(secrets.token_hex(32))
    return app
