# TaskNest

A self-hosted dynamic task website with account registration, sign-in, sign-out, and a private dashboard. Create tasks, assign Personal/Study/Work categories, set due dates, mark tasks complete, and delete tasks. Filters and statistics update from stored data.

Public source: https://github.com/osth4545/tasknest

## Assignment requirements

| Requirement | Implementation |
| --- | --- |
| Dynamic website | Flask renders account-specific tasks and dashboard statistics |
| Database service | PostgreSQL 17 in a separate Docker Compose service |
| Authentication | Registration, scrypt password hashes, signed cookies and revocable server-side sessions |
| Public source | Publish this folder as a **public** GitHub repository using the steps below |
| Installation instructions | Docker Compose setup below |

The application contains no AWS keys, SSH keys, default accounts, or default passwords. The database port is internal to Docker. Each user's task queries are restricted to their user ID. Forms use CSRF tokens; login attempts are limited per email to 10 per 15 minutes. Sessions expire after 12 hours and are invalidated on logout. This is a coursework application; it does not include email verification or password recovery.

## Run on your Linux server / AWS EC2

Prerequisites: Git, Python 3, and Docker Engine with the Compose plugin installed and running. Use the official [Docker Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/) for Ubuntu. On other distributions use the matching official installation guide. The account running the commands must have permission to run Docker (otherwise prefix Docker commands with `sudo`).

No GitHub credentials are needed to clone this public repository.

```bash
git clone https://github.com/osth4545/tasknest.git
cd tasknest
python3 setup_env.py
docker compose up -d --build
docker compose ps
curl http://localhost/health
```

Open `http://YOUR_SERVER_PUBLIC_IP` in your browser. Register your own account; there is no preset login. In your EC2 security group, allow inbound TCP port **80** for the intended visitors. Restrict SSH port 22 to your own IP. Do not open PostgreSQL port 5432.

Compose starts PostgreSQL first, waits for database health, initializes tables, then serves the website through Waitress on container port 8000, exposed as host port 80. If port 80 is occupied, change `PORT` in `.env`, run `docker compose up -d`, and use the selected port in the URL and security group.

For an internet-facing deployment with real accounts, put an HTTPS reverse proxy in front of the app and set `COOKIE_SECURE=true` in `.env`, then recreate the web service. The default HTTP configuration is provided for the assignment demonstration; do not enter sensitive or reused passwords over HTTP.

### Verify the database and persistence

```bash
docker compose exec db psql -U tasknest -d tasknest -c 'SELECT name, email FROM users;'
docker compose exec db psql -U tasknest -d tasknest -c 'SELECT title, category, done FROM tasks;'
docker compose restart
```

Refresh the site after restarting: accounts and tasks remain in the named `postgres_data` volume. `docker compose down` stops the services while preserving the database. **Do not add `-v` unless you intend to erase the database.** Keep your generated `.env`; changing its database password alone does not change the password inside an existing PostgreSQL volume.

Logs: `docker compose logs --tail=80 web db`. Health: `curl http://localhost/health` should return `{"status":"ok"}`.

## Publish to public GitHub (required by the assignment)

Create an empty public repository named `tasknest` on [GitHub](https://github.com/new). Leave the README, license and .gitignore initialization options unchecked because these files are already supplied. In PowerShell, open this project folder and run:

```powershell
git init -b main
git add app.py templates static tests requirements.txt Dockerfile compose.yaml setup_env.py README.md LICENSE .gitignore .dockerignore .env.example
git commit -m "Build TaskNest with authentication and PostgreSQL"
git remote add origin https://github.com/YOUR_USERNAME/tasknest.git
git push -u origin main
```

The author may need to sign in to push. The server can subsequently clone the public repository without signing in. Never upload `.env`, `.pem`, or AWS credentials. Verify the repository is visible while signed out before using it on your instance.

## Local preview without Docker (SQLite)

Docker Compose is the PostgreSQL deployment. SQLite is a separate convenience mode for previewing and running tests on a machine without Docker; it is not a substitute for demonstrating the PostgreSQL service in the assignment.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
.\.venv\Scripts\python.exe -m flask --app app:create_app init-db
.\.venv\Scripts\python.exe -m flask --app app:create_app run --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Keep the same `SECRET_KEY` to preserve login cookies between restarts. Preview data is stored in `instance/tasknest.db`. If `DATABASE_URL` is set, the app uses that PostgreSQL database instead of SQLite. Do not use Flask's development server for a public deployment.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The tests use a temporary SQLite database and cover registration, hashed passwords, login failures, rate limiting, session expiration and logout revocation, task creation/completion/deletion, persistence, CSRF, validation, HTML escaping, and isolation between users. Docker/PostgreSQL verification must additionally be performed on a Docker-capable host.

## Screenshots for submission

1. Registration or login screen, showing the website identity.
2. Your logged-in dashboard with at least three tasks and one completed task.
3. `docker compose ps` showing the web and database services running and healthy.
4. PostgreSQL query output showing stored tasks (commands above).
5. The public GitHub repository page and URL.

Use screenshots from your actual running server for the deployment evidence.

## References

- [Flask sessions and application basics](https://flask.palletsprojects.com/en/stable/quickstart/)
- [Werkzeug password hashing](https://werkzeug.palletsprojects.com/en/stable/utils/)
- [Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/)
- [Official PostgreSQL Docker image](https://hub.docker.com/_/postgres)

License: MIT.
