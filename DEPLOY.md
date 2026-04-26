# NPC PMS Portal — DirectAdmin Quick Deploy Guide

Target URL: **https://pms.npcindia.info/**

Same rhythm as your biometric deploy, but Django has two extra "execute script" clicks to migrate the DB and collect static files.

---

## Before you start — checklist

- [ ] You have the DirectAdmin login (`npcindia` @ `103.133.215.103:2222`)
- [ ] You know your SSH is **disabled** — everything is panel-driven
- [ ] You have ~45 minutes (5 min setup, 10 min upload, 5 min pip install, 5 min database, 20 min testing)

---

## The 11 steps

### 1. Create the MariaDB database

DirectAdmin → **Databases** → "Create new database"

| Field | Value |
|---|---|
| Database Name | `pms` (becomes `npcindia_pms`) |
| Username | `pms` (becomes `npcindia_pms`) |
| Password | click the dice icon |

**→ Copy the password. You will need it twice.**

### 2. Create the data folder

DirectAdmin → **File Manager** → navigate to `/home/npcindia/`

- Create folder: `pms_data`
- Inside `pms_data`, create two subfolders: `uploads` and `reports`

### 3. Create the logs folder (if it doesn't already exist)

Still in `/home/npcindia/`:
- Create folder: `logs` (skip if already present from the biometric deploy)

### 4. Create the subdomain

DirectAdmin → **Subdomain Management** → "Create Subdomain"

| Field | Value |
|---|---|
| Subdomain | `pms` |
| Root Domain | `npcindia.info` |

This creates `pms.npcindia.info` with its own document root. Do NOT enable the "Open public_html" option; Passenger will override the webroot.

### 5. Create the Python App

DirectAdmin → **Setup Python App** → "Create Application"

| Field | Value |
|---|---|
| Python version | 3.12.11 |
| Application root | `pms_app` |
| Application URL | `pms.npcindia.info` |
| Application URI | *(leave blank — subdomain, not subfolder)* |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |
| Passenger log file | `/home/npcindia/logs/passenger_pms.log` |

Click **CREATE**. DirectAdmin will create the virtualenv.

### 6. Zip your code on your PC

On Windows, run in the project folder:

```cmd
python make_deploy_zip.py
```

This creates `pms_upload.zip` (about 3–5 MB) containing:
- `pms_portal/` (Django settings/urls/wsgi)
- `core/` (the Django app — models, views, templates, static files, migrations)
- `manage.py`, `passenger_wsgi.py`, `requirements.txt`
- `local_settings.py.example`
- `run_migrate.py`, `run_collectstatic.py`, `run_createsuperuser.py`
- This `DEPLOY.md`

It **excludes**: tests, old FastAPI `app/`, Tally data, docs, `*.xlsx`, `db.sqlite3`, `__pycache__`, `.git`.

### 7. Upload and extract

- File Manager → navigate to `/home/npcindia/pms_app/`
- Upload `pms_upload.zip`
- Right-click the zip → **Extract** → "Yes to all" to overwrite
- Delete the zip when done

### 8. Edit `local_settings.py`

In `/home/npcindia/pms_app/`:

- Right-click `local_settings.py.example` → **Rename** → `local_settings.py`
- Double-click to open in the File Manager editor
- Change these 2 lines with your real values:

  ```python
  MYSQL_PASSWORD = 'PUT-YOUR-DB-PASSWORD-HERE'     # ← from step 1
  SECRET_KEY     = 'PUT-A-LONG-RANDOM-STRING-HERE-AT-LEAST-50-CHARACTERS'  # ← any 50+ random chars
  ```

  Generate a SECRET_KEY at https://www.random.org/strings/ (length 50, alphanumeric).

- Save.

### 9. Install Python packages

DirectAdmin → **Setup Python App** → **Manage** next to `pms.npcindia.info`

Scroll to "Configuration files":

1. Click the empty box "Add another file and press enter"
2. Type: `requirements.txt`
3. **Press ENTER** (not the Add button)
4. Now **▶ Run Pip Install** is clickable — click it
5. Wait 3–6 minutes. Watch for "Successfully installed Django-6.0.3 ..."

**If it fails:** open File Manager, navigate to `/home/npcindia/pms_app/requirements.log`, scroll to the bottom, share the last 30 lines with me. Do NOT guess from the pop-up error — it's truncated.

### 10. Run the 3 setup scripts (one at a time)

Still on the Manage page, scroll down to **"Execute python script"**. Paste each full path in turn, click **▶ Run Script**, wait for output, then do the next one:

**10a. Create the database tables:**
```
/home/npcindia/pms_app/run_migrate.py
```
Expected output: "Applying core.0001_initial... OK" and 15–20 more lines. Takes 20–40 seconds.

**10b. Collect static files (for WhiteNoise):**
```
/home/npcindia/pms_app/run_collectstatic.py
```
Expected: "160 static files copied to ..."

**10c. Create the first admin:**
```
/home/npcindia/pms_app/run_createsuperuser.py
```
Expected: "Admin created. Email: admin@npcindia.gov.in, Password: admin123"

### 11. Restart and test

- Click **⟳ RESTART** on the Manage page
- Open a new browser tab: **https://pms.npcindia.info/**
- Log in with `admin@npcindia.gov.in` / `admin123`
- **CHANGE THE PASSWORD IMMEDIATELY** from the profile page

First page load takes 10–20 seconds (Django warming up).

---

## If something breaks

### First, read the log

File Manager → `/home/npcindia/logs/passenger_pms.log` → copy the last 30 lines → share.

Also check `/home/npcindia/logs/pms_django.log` (created by Django's file logger).

### Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| **502 Bad Gateway** | Passenger can't start Python. Almost always a typo in `local_settings.py` or a missing package. | Read passenger_pms.log (last 30 lines). Usually shows `ModuleNotFoundError` or `OperationalError`. |
| **500 Internal Server Error** | App started but crashed on a request. | Read pms_django.log. Usually a DB issue. |
| **"Unknown database 'npcindia_pms'"** | DB name mismatch in local_settings.py. | Check spelling — prefix is `npcindia_` not `npcindia-`. |
| **"Access denied for user 'npcindia_pms'@'localhost'"** | Wrong DB password. | Re-check MYSQL_PASSWORD in local_settings.py. Copy/paste from the database page. |
| **CSS missing / logo broken** | run_collectstatic.py not run, or WhiteNoise middleware misordered. | Run step 10b again, then restart. |
| **"DisallowedHost at /"** | ALLOWED_HOSTS doesn't include `pms.npcindia.info`. | Check local_settings.py — should match exactly. |
| **Admin login works but rest of site shows 500** | Data tables are empty — no offices/roles seeded. | Log in as admin → Django admin at `/admin/` → add at least one Office. |

### How to push a code change later

1. Edit files on your PC
2. Re-run `python make_deploy_zip.py`
3. Upload `pms_upload.zip` to `/home/npcindia/pms_app/`, right-click → Extract (overwrite yes)
4. If you changed `requirements.txt`: Run Pip Install again
5. If you changed a model OR added an app: Run `run_migrate.py` again
6. **Always run `run_collectstatic.py`** — manifest must be regenerated even if no asset files changed (CompressedManifestStaticFilesStorage needs it)
7. Click **⟳ RESTART**

**You do NOT need to re-run `run_createsuperuser.py`** — it's idempotent and will skip if admin already exists.

### Pre-deploy checklist (per release)

Before clicking deploy, confirm what changed since the last release and which steps are needed:

| Change | Action |
|---|---|
| `requirements.txt` modified (new package) | **Run Pip Install (step 4)** |
| New `core/migrations/000X_*.py` files | **Run `run_migrate.py` (step 5)** |
| New `INSTALLED_APPS` entry | **Run `run_migrate.py` (step 5)** — third-party apps add their own tables |
| `core/static/` or `core/templates/` changed | Run `run_collectstatic.py` (step 6) — always safe |
| Only `.py` view / model code changed | Restart only |

---

## Daily backup (set up after first successful deploy)

The portal ships three management commands that handle DB backup, file backup,
and old-backup cleanup. Wire them up via DirectAdmin cron — one entry each.

First, create the backup directory in File Manager:
- `/home/npcindia/pms_data/backups/`

DirectAdmin → **Cron Jobs** → add THREE jobs:

**1. DB backup (daily 02:00)**

| Field | Value |
|---|---|
| Minute | `0` |
| Hour | `2` |
| Day / Month / Weekday | `*` |
| Command | `cd /home/npcindia/pms_app && /home/npcindia/virtualenv/pms_app/3.12/bin/python manage.py backup_db >> /home/npcindia/logs/backup.log 2>&1` |

**2. File backup (daily 02:30)**

| Field | Value |
|---|---|
| Minute | `30` |
| Hour | `2` |
| Day / Month / Weekday | `*` |
| Command | `cd /home/npcindia/pms_app && /home/npcindia/virtualenv/pms_app/3.12/bin/python manage.py backup_files >> /home/npcindia/logs/backup.log 2>&1` |

**3. Cleanup old backups (daily 03:00)**

| Field | Value |
|---|---|
| Minute | `0` |
| Hour | `3` |
| Day / Month / Weekday | `*` |
| Command | `cd /home/npcindia/pms_app && /home/npcindia/virtualenv/pms_app/3.12/bin/python manage.py cleanup_backups >> /home/npcindia/logs/backup.log 2>&1` |

Default retention is 30 days. To change, set `BACKUP_RETENTION_DAYS` in
`local_settings.py` (e.g. `BACKUP_RETENTION_DAYS = 90` for statutory cases).

**Each command writes integrity-checked, gzipped output to
`/home/npcindia/pms_data/backups/`.** Naming:
- `db_YYYY-MM-DD_HHMMSS.sql.gz` — full mysqldump
- `files_YYYY-MM-DD_HHMMSS.tar.gz` — uploads tarball

Tail `/home/npcindia/logs/backup.log` weekly to catch silent failures.

### Manual backup before risky changes

DirectAdmin → Setup Python App → Manage → "Execute python script". Paste:

```
/home/npcindia/pms_app/manage.py backup_db
```

(Same for `backup_files`. Output goes to the standard backup directory.)

---

## What's NOT deployed (Phase 2)

| Feature | Why deferred | Plan |
|---|---|---|
| **Tally Prime sync** | Needs LAN/VPN into office network. Shared hosting can't reach Tally server. | Phase 2 — deploy on-prem or on a VPS with VPN. |
| **Background jobs** | Shared hosting has no persistent workers (no Celery). | If needed, use DirectAdmin Cron to run Django management commands on a schedule. |
| **Redis cache** | Not available on shared hosting. | Using Django's default database cache (fine for ~50 concurrent users). |

---

## Reference — what changed from Render/Railway

| Old | New (DirectAdmin) |
|---|---|
| `gunicorn pms_portal.wsgi:application` | Passenger reads `passenger_wsgi.py` |
| PostgreSQL via `DATABASE_URL` | MariaDB via `local_settings.py` |
| `psycopg2-binary` | `pymysql` (pure Python, no compilation) |
| Auto-deploy on `git push` | Manual zip → upload → extract → restart |
| `DATABASE_URL` env var | `MYSQL_DB`, `MYSQL_USER`, etc. in `local_settings.py` |
| `render.yaml` / `Procfile` | `passenger_wsgi.py` |
