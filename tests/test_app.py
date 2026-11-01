import re
import sqlite3
import uuid
import unittest
from contextlib import closing
from pathlib import Path
from app import create_app


class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.path = str(Path(__file__).parent / f'test-{uuid.uuid4().hex}.db')
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only-' * 8,
                               'DATABASE_URL': None, 'SQLITE_PATH': self.path})
        result = self.app.test_cli_runner().invoke(args=['init-db'])
        self.assertEqual(result.exit_code, 0, str(result.exception) if result.exception else result.output)
        self.client = self.app.test_client()

    def tearDown(self):
        Path(self.path).unlink(missing_ok=True)

    def post(self, client, path, data=None):
        token = re.search(rb'name="csrf" value="([^"]+)"', client.get('/register').data)
        if not token:
            token = re.search(rb'name="csrf" value="([^"]+)"', client.get('/').data)
        return client.post(path, data={**(data or {}), 'csrf': token[1].decode()})

    def register(self, client=None, email='alex@example.com'):
        client = client or self.client
        return self.post(client, '/register', {'name': 'Alex Morgan', 'email': email, 'password': 'strong-password-123'})

    def rows(self, sql):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(sql).fetchall()

    def test_protected_dashboard(self):
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.client.get('/health').json, {'status': 'ok'})

    def test_register_and_password_hashing(self):
        self.assertEqual(self.register().status_code, 302)
        self.assertIn(b'A fresh perspective.', self.client.get('/').data)
        stored = self.rows('SELECT password_hash FROM users')[0][0]
        self.assertTrue(stored.startswith('scrypt:'))
        self.assertNotEqual(stored, 'strong-password-123')

    def test_login_logout_and_revocation(self):
        self.register()
        with self.client.session_transaction() as old_session:
            stolen = dict(old_session)
        self.post(self.client, '/logout')
        self.assertEqual(self.client.get('/').status_code, 302)
        with self.client.session_transaction() as current:
            current.update(stolen)
        self.assertEqual(self.client.get('/').status_code, 302)
        self.post(self.client, '/login', {'email': 'alex@example.com', 'password': 'wrong'})
        self.assertEqual(self.client.get('/').status_code, 302)
        self.post(self.client, '/login', {'email': 'alex@example.com', 'password': 'strong-password-123'})
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_csrf_required(self):
        self.register()
        self.assertEqual(self.client.post('/tasks', data={'title': 'Unsafe'}).status_code, 400)
        self.assertEqual(len(self.rows('SELECT * FROM tasks')), 0)

    def test_task_crud_and_persistence(self):
        self.register()
        self.post(self.client, '/tasks', {'title': 'Finish assignment', 'category': 'Study', 'due_date': '2026-11-10'})
        task_id = self.rows('SELECT id FROM tasks')[0][0]
        self.assertIn(b'Finish assignment', self.client.get('/').data)
        self.post(self.client, f'/tasks/{task_id}/toggle')
        self.assertEqual(self.rows('SELECT done FROM tasks')[0][0], 1)
        self.assertNotIn(b'Finish assignment', self.client.get('/?view=active').data)
        self.assertIn(b'Finish assignment', self.client.get('/?view=done').data)
        restarted = create_app(self.app.config).test_client()
        self.post(restarted, '/login', {'email': 'alex@example.com', 'password': 'strong-password-123'})
        self.assertIn(b'Finish assignment', restarted.get('/').data)
        self.post(self.client, f'/tasks/{task_id}/delete')
        self.assertEqual(self.rows('SELECT COUNT(*) FROM tasks')[0][0], 0)

    def test_users_cannot_access_others_tasks(self):
        self.register()
        self.post(self.client, '/tasks', {'title': 'Private task', 'category': 'Work'})
        task_id = self.rows('SELECT id FROM tasks')[0][0]
        other = self.app.test_client()
        self.register(other, 'other@example.com')
        self.assertNotIn(b'Private task', other.get('/').data)
        for action in ['toggle', 'delete']:
            self.assertEqual(self.post(other, f'/tasks/{task_id}/{action}').status_code, 404)
        self.assertEqual(self.rows('SELECT done FROM tasks')[0][0], 0)

    def test_validation_and_escaping(self):
        self.register()
        for fields in [{'title': 'x' * 161}, {'title': 'ok', 'due_date': 'invalid'}, {'title': 'ok', 'category': 'bad'}]:
            self.post(self.client, '/tasks', fields)
        self.assertEqual(len(self.rows('SELECT * FROM tasks')), 0)
        self.post(self.client, '/tasks', {'title': '<script>alert(1)</script>'})
        page = self.client.get('/').data
        self.assertNotIn(b'<script>', page)
        self.assertIn(b'&lt;script&gt;', page)

    def test_duplicate_email_and_weak_password(self):
        weak = self.post(self.client, '/register', {'name': 'Test', 'email': 'test@example.com', 'password': 'short'})
        self.assertIn(b'between 10 and 128', weak.data)
        self.register()
        other = self.app.test_client()
        self.register(other, 'ALEX@example.com')
        self.assertEqual(self.rows('SELECT COUNT(*) FROM users')[0][0], 1)

    def test_login_rate_limit(self):
        for _ in range(10):
            self.post(self.client, '/login', {'email': 'missing@example.com', 'password': 'wrong'})
        self.assertEqual(self.post(self.client, '/login', {'email': 'missing@example.com', 'password': 'wrong'}).status_code, 429)

    def test_expired_session(self):
        self.register()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE sessions SET expires=0')
            db.commit()
        self.assertEqual(self.client.get('/').status_code, 302)


if __name__ == '__main__':
    unittest.main()
