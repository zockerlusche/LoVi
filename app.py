from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, send_file
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os, sqlite3, hashlib, secrets, re
import json
import psutil, time

# ─── TRANSLATIONS ─────────────────────────────────────────────
TRANSLATIONS_DIR = "/app/translations"

def load_translation(lang="de"):
    path = os.path.join(TRANSLATIONS_DIR, f"{lang}.json")
    if not os.path.exists(path):
        path = os.path.join(TRANSLATIONS_DIR, "en.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_user_lang():
    if current_user.is_authenticated:
        conn = get_db()
        row = conn.execute("SELECT language FROM users WHERE id = ?",
                           (current_user.id,)).fetchone()
        conn.close()
        return row["language"] if row and row["language"] else "en"
    return "de"

def get_login_lang():
    lang = request.accept_languages.best_match(["de", "en"])
    return lang or "en"

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# ─── DATENBANK ───────────────────────────────────────────────
DB_PATH  = "/data/lovi.db"
LOG_DIR  = "/logs"

GITHUB_USER = "zockerlusche"
GITHUB_REPO = "lovi-profiles"
GITHUB_BASE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_rotating_log(filename):
    """Erkennt rotierende Log-Dateien wie radarr.debug.0.txt oder app.log.1"""
    basename = os.path.basename(filename)
    # Muster: endet auf .N.ext oder .ext.N
    if re.search(r'\.\d+\.(log|txt)$', basename):
        return True
    if re.search(r'\.(log|txt)\.\d+$', basename):
        return True
    return False

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        username       TEXT UNIQUE NOT NULL,
        password       TEXT NOT NULL,
        is_admin       INTEGER DEFAULT 0,
        must_change_pw INTEGER DEFAULT 0,
        language       TEXT DEFAULT 'en'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS profiles (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT UNIQUE NOT NULL,
        description TEXT,
        author      TEXT DEFAULT 'local',
        version     TEXT DEFAULT '1.0',
        source      TEXT DEFAULT 'local',
        level_error TEXT DEFAULT '[Error],[Fatal],ERROR,CRITICAL',
        level_warn  TEXT DEFAULT '[Warn],WARN,WARNING',
        level_info  TEXT DEFAULT '[Info],INFO',
        level_debug TEXT DEFAULT '[Debug],DEBUG,TRACE',
        log_path_hint TEXT DEFAULT '',
        help_setup  TEXT DEFAULT '',
        help_mount  TEXT DEFAULT '',
        created_at  TEXT DEFAULT (datetime('now'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS log_assignments (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        filename   TEXT UNIQUE NOT NULL,
        profile_id INTEGER DEFAULT 1,
        label      TEXT DEFAULT '',
        FOREIGN KEY (profile_id) REFERENCES profiles(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS log_stats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        filename    TEXT NOT NULL,
        sampled_at  TEXT DEFAULT (datetime('now')),
        error_count INTEGER DEFAULT 0,
        warn_count  INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS notification_settings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        enabled         INTEGER DEFAULT 0,
        smtp_host       TEXT DEFAULT '',
        smtp_port       INTEGER DEFAULT 587,
        smtp_user       TEXT DEFAULT '',
        smtp_pass       TEXT DEFAULT '',
        smtp_from       TEXT DEFAULT '',
        smtp_to         TEXT DEFAULT '',
        threshold_count INTEGER DEFAULT 5,
        threshold_mins  INTEGER DEFAULT 10,
        cooldown_mins   INTEGER DEFAULT 30
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS notification_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        filename   TEXT NOT NULL,
        sent_at    TEXT DEFAULT (datetime('now')),
        error_count INTEGER DEFAULT 0
    )''')

    # NEU: Tabelle für ausgeblendete Log-Dateien
    c.execute('''CREATE TABLE IF NOT EXISTS log_hidden (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT UNIQUE NOT NULL
    )''')

    conn.commit()

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        pw_hash = hash_password("admin")
        c.execute("INSERT INTO users (username, password, is_admin, must_change_pw) VALUES (?, ?, 1, 1)",
                  ("admin", pw_hash))

    c.execute("DELETE FROM profiles WHERE source='builtin'")

    builtin_profiles = [
        ("Standard",
         "General format – detects INFO/WARN/ERROR",
         "LoVi", "1.1", "builtin",
         "ERROR,CRITICAL,FATAL", "WARN,WARNING", "INFO", "DEBUG,TRACE",
         "/logs/myapp/app.log",
         "Compatible with: Most Python, Node.js, Java apps\nVersion hint: Universal – works with almost any structured log.\n\nStep 1 – Find your log path:\nMost apps write to /config/logs/ inside the container.\nCheck your app docs or run: docker exec CONTAINERNAME find /config -name '*.log'\n\nStep 2 – Add volume to the APP's docker-compose.yml:\n  volumes:\n    - /opt/docker/APPNAME/config:/config        # already exists\n    - /opt/docker/APPNAME/config/logs:/logs/APPNAME  # ADD THIS\n\nStep 3 – Add the same path to LOVI's docker-compose.yml:\n  services:\n    lovi:\n      volumes:\n        - /opt/logs:/logs                              # already exists\n        - /opt/docker/APPNAME/config/logs:/logs/APPNAME  # ADD THIS\n\nStep 4 – Recreate BOTH containers (not just restart!):\n  cd /opt/docker/YOURSTACK && docker-compose up -d APPNAME\n  cd /opt/docker/logviewer && docker-compose up -d lovi\n\nStep 5 – Assign in LoVi:\n  Settings -> Assign -> select log file -> Profile: Standard\n\n⚠ A recreate causes ~5s downtime. App config and data are NOT affected.",
         "-v /opt/docker/APPNAME/config/logs:/logs/APPNAME"),
    ]

    for p in builtin_profiles:
        c.execute('''INSERT INTO profiles
            (name, description, author, version, source,
             level_error, level_warn, level_info, level_debug,
             log_path_hint, help_setup, help_mount)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', p)

    conn.commit()
    conn.close()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ─── FLASK-LOGIN ─────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = ""
login_manager.login_message_category = "info"

class User(UserMixin):
    def __init__(self, id, username, is_admin, must_change_pw):
        self.id             = id
        self.username       = username
        self.is_admin       = is_admin
        self.must_change_pw = must_change_pw

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        return User(row["id"], row["username"], row["is_admin"], row["must_change_pw"])
    return None

# ─── LOG FUNKTIONEN ──────────────────────────────────────────

def get_hidden_files():
    conn = get_db()
    return {row["filename"] for row in conn.execute("SELECT filename FROM log_hidden").fetchall()}

def get_log_files(include_hidden=False, include_rotating=False):
    """
    Gibt alle Log-Dateien zurück.
    include_hidden=False  → ausgeblendete Dateien weglassen
    include_rotating=False → rotierende Logs (z.B. radarr.debug.0.txt) weglassen
    """
    files = []
    if os.path.exists(LOG_DIR):
        for root, dirs, filenames in os.walk(LOG_DIR):
            for f in filenames:
                if f.endswith(".log") or f.endswith(".txt"):
                    rel_path = os.path.relpath(os.path.join(root, f), LOG_DIR)
                    files.append(rel_path)

    if not include_rotating:
        files = [f for f in files if not is_rotating_log(f)]

    if not include_hidden:
        conn = get_db()
        hidden = {row["filename"] for row in conn.execute("SELECT filename FROM log_hidden").fetchall()}
        conn.close()
        files = [f for f in files if f not in hidden]

    return sorted(files)

def send_alert_mail(settings, filename, error_count):
    """Sendet eine Alert-Mail via SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[LoVi Alert] {error_count} ERRORs in {filename}"
    msg["From"]    = settings["smtp_from"]
    msg["To"]      = settings["smtp_to"]
    body = f"""LoVi detected {error_count} ERROR entries in the last {settings["threshold_mins"]} minutes.

Log file: {filename}

-- LoVi Log Viewer"""
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP(settings["smtp_host"], settings["smtp_port"]) as server:
        server.starttls()
        server.login(settings["smtp_user"], settings["smtp_pass"])
        server.sendmail(settings["smtp_from"], settings["smtp_to"], msg.as_string())

def check_notifications():
    """Prüft nur assigned Log-Dateien auf ERROR-Rate und sendet Alerts."""
    import datetime
    conn = get_db()
    row = conn.execute("SELECT * FROM notification_settings WHERE id=1").fetchone()
    if not row or not row["enabled"]:
        conn.close()
        return
    settings = dict(row)
    threshold_count = settings["threshold_count"]
    threshold_mins  = settings["threshold_mins"]
    cooldown_mins   = settings["cooldown_mins"]
    assigned = {r["filename"] for r in conn.execute("SELECT filename FROM log_assignments").fetchall()}
    files = [f for f in get_log_files() if f in assigned]
    for filename in files:
        # Cooldown prüfen
        last = conn.execute(
            "SELECT sent_at FROM notification_log WHERE filename=? ORDER BY sent_at DESC LIMIT 1",
            (filename,)
        ).fetchone()
        if last:
            last_dt = datetime.datetime.fromisoformat(last["sent_at"])
            diff = (datetime.datetime.utcnow() - last_dt).total_seconds() / 60
            if diff < cooldown_mins:
                continue
        # Error-Rate prüfen
        lines = read_log_file(filename, lines=500)
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=threshold_mins)
        error_count = 0
        for line in lines:
            if line["level"] == "error":
                error_count += 1
        if error_count >= threshold_count:
            try:
                send_alert_mail(settings, filename, error_count)
                conn.execute(
                    "INSERT INTO notification_log (filename, error_count) VALUES (?,?)",
                    (filename, error_count)
                )
                conn.commit()
            except Exception as e:
                app.logger.error(f"Mail error: {e}")
    conn.close()

def auto_assign_by_hint(conn):
    """Weist Log-Dateien automatisch einem Profil zu wenn log_path_hint passt."""
    profiles = conn.execute(
        "SELECT id, name, log_path_hint FROM profiles WHERE log_path_hint != ''"
    ).fetchall()
    if not profiles:
        return
    log_files = get_log_files(include_hidden=True, include_rotating=False)
    for filename in log_files:
        # Bereits assigned?
        existing = conn.execute(
            "SELECT profile_id FROM log_assignments WHERE filename = ?", (filename,)
        ).fetchone()
        if existing:
            continue
        # Gegen alle Profile testen
        for profile in profiles:
            hint = profile["log_path_hint"].strip()
            if not hint:
                continue
            # Matche am Ende des Pfades (basename oder Teilpfad)
            hint_parts = hint.replace("\\", "/").split("/")
            file_parts = filename.replace("\\", "/").split("/")
            # Prüfe ob hint-Dateiname mit file-Dateiname übereinstimmt
            hint_name = hint_parts[-1]
            file_name = file_parts[-1]
            # Auch Verzeichnis prüfen wenn vorhanden
            hint_dir = hint_parts[-2] if len(hint_parts) >= 2 else ""
            file_dir = file_parts[-2] if len(file_parts) >= 2 else ""
            if hint_name == file_name and (not hint_dir or hint_dir in file_dir):
                conn.execute("""INSERT INTO log_assignments (filename, profile_id, label)
                    VALUES (?, ?, ?)
                    ON CONFLICT(filename) DO NOTHING""",
                    (filename, profile["id"], profile["name"]))
                break

def sample_log_stats():
    """Stündlich ERRORs/WARNs pro Log-Datei samplen und in DB speichern."""
    conn = get_db()
    files = get_log_files()
    for filename in files:
        lines = read_log_file(filename, lines=500)
        error_count = sum(1 for l in lines if l["level"] == "error")
        warn_count  = sum(1 for l in lines if l["level"] == "warn")
        conn.execute(
            "INSERT INTO log_stats (filename, error_count, warn_count) VALUES (?,?,?)",
            (filename, error_count, warn_count)
        )
        # Nur letzte 96 Einträge pro Datei behalten (96 x 15min = 24h)
        conn.execute("""DELETE FROM log_stats WHERE filename=? AND id NOT IN (
            SELECT id FROM log_stats WHERE filename=? ORDER BY id DESC LIMIT 96
        )""", (filename, filename))
    conn.commit()
    conn.close()

def notification_worker():
    """Background Thread – Notifications alle 5 Min, Stats stündlich."""
    import time as time_mod
    last_sample = 0
    while True:
        try:
            check_notifications()
            now = time_mod.time()
            if now - last_sample >= 900:
                sample_log_stats()
                last_sample = now
        except Exception as e:
            app.logger.error(f"Notification worker error: {e}")
        time_mod.sleep(300)

def parse_log_level(line):
    u = line.upper()
    if "ERROR" in u or "CRITICAL" in u: return "error"
    elif "WARN" in u or "WARNING" in u:  return "warn"
    elif "INFO" in u:                    return "info"
    elif "DEBUG" in u:                   return "debug"
    return "default"

def read_log_file(filename, search=None, lines=200):
    filepath = os.path.join(LOG_DIR, filename)
    result = []
    if not os.path.exists(filepath):
        return result
    with open(filepath, "r", errors="replace") as f:
        all_lines = f.readlines()
    for line in all_lines[-lines:]:
        line = line.rstrip()
        if not line:
            continue
        if search and search.lower() not in line.lower():
            continue
        result.append({"text": line, "level": parse_log_level(line)})
    return result

# ─── ROUTEN: AUTH ────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        pw_hash  = hash_password(password)
        conn = get_db()
        row  = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?",
                            (username, pw_hash)).fetchone()
        conn.close()
        if row:
            user = User(row["id"], row["username"], row["is_admin"], row["must_change_pw"])
            login_user(user)
            if row["must_change_pw"]:
                flash("Bitte Passwort ändern!", "warn")
                return redirect(url_for("change_password"))
            return redirect(url_for("index"))
        flash("Falscher Benutzername oder Passwort!", "error")
    return render_template("login.html",
                       t=load_translation(get_login_lang()),
                       current_lang=get_login_lang())

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        new_pw = request.form.get("new_password", "")
        if len(new_pw) < 6:
            flash("Passwort muss mindestens 6 Zeichen haben!", "error")
        else:
            conn = get_db()
            conn.execute("UPDATE users SET password = ?, must_change_pw = 0 WHERE id = ?",
                         (hash_password(new_pw), current_user.id))
            conn.commit()
            conn.close()
            flash("Passwort geändert!", "info")
            return redirect(url_for("index"))
    return render_template("change_password.html", t=load_translation(get_user_lang()))

# ─── ROUTEN: USERVERWALTUNG ──────────────────────────────────
@app.route("/users")
@login_required
def users():
    conn = get_db()
    user_list = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return render_template("users.html",
                           users=user_list,
                           t=load_translation(get_user_lang()),
                           current_lang=get_user_lang())

@app.route("/users/add", methods=["POST"])
@login_required
def add_user():
    if not current_user.is_admin:
        return redirect(url_for("index"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    is_admin = 1 if request.form.get("is_admin") else 0
    if username and len(password) >= 6:
        try:
            conn = get_db()
            conn.execute("INSERT INTO users (username, password, is_admin, must_change_pw) VALUES (?,?,?,1)",
                         (username, hash_password(password), is_admin))
            conn.commit()
            conn.close()
            flash(f"User '{username}' angelegt!", "info")
        except sqlite3.IntegrityError:
            flash("Benutzername existiert bereits!", "error")
    else:
        flash("Benutzername und Passwort (min. 6 Zeichen) erforderlich!", "error")
    return redirect(url_for("users"))

@app.route("/users/delete/<int:user_id>", methods=["POST"])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return redirect(url_for("index"))
    if user_id == current_user.id:
        flash("Du kannst dich nicht selbst löschen!", "error")
        return redirect(url_for("users"))
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash("User gelöscht!", "info")
    return redirect(url_for("users"))

# ─── ROUTEN: SETTINGS & PROFILE ─────────────────────────────
@app.route("/settings")
@login_required
def settings():
    if not current_user.is_admin:
        return redirect(url_for("index"))
    conn = get_db()
    profiles = conn.execute("SELECT * FROM profiles ORDER BY source, name").fetchall()
    assignments = conn.execute("""
        SELECT la.*, p.name as profile_name
        FROM log_assignments la
        LEFT JOIN profiles p ON la.profile_id = p.id
    """).fetchall()
    hidden_set = {row["filename"] for row in conn.execute("SELECT filename FROM log_hidden").fetchall()}
    conn.close()

    # Alle Dateien inkl. rotating und hidden für die Verwaltung
    all_files = get_log_files(include_hidden=True, include_rotating=True)
    # Normale Dateien für Assign-Dropdown (ohne hidden, ohne rotating)
    log_files = get_log_files()

    # Dateien mit Metadaten anreichern
    files_meta = []
    for f in all_files:
        files_meta.append({
            "filename": f,
            "hidden":   f in hidden_set,
            "rotating": is_rotating_log(f),
        })

    return render_template("settings.html",
                       profiles=profiles,
                       assignments=assignments,
                       log_files=log_files,
                       files_meta=files_meta,
                       github_user=GITHUB_USER,
                       github_repo=GITHUB_REPO,
                       t=load_translation(get_user_lang()),
                       current_lang=get_user_lang())

@app.route("/settings/logfiles/hide", methods=["POST"])
@login_required
def hide_logfile():
    if not current_user.is_admin:
        return redirect(url_for("index"))
    filename = request.form.get("filename", "")
    action   = request.form.get("action", "hide")  # hide | show
    if not filename or ".." in filename:
        flash("Ungültiger Dateiname!", "error")
        return redirect(url_for("settings"))
    conn = get_db()
    if action == "hide":
        conn.execute("INSERT OR IGNORE INTO log_hidden (filename) VALUES (?)", (filename,))
        flash(f"'{filename}' hidden.", "info")
    else:
        conn.execute("DELETE FROM log_hidden WHERE filename = ?", (filename,))
        flash(f"'{filename}' visible again.", "info")
    conn.commit()
    conn.close()
    return redirect(url_for("settings") + "#logfiles")

@app.route("/settings/logfiles/hide-rotating", methods=["POST"])
@login_required
def hide_rotating():
    """Versteckt alle rotierenden Logs auf einmal."""
    if not current_user.is_admin:
        return redirect(url_for("index"))
    all_files = get_log_files(include_hidden=True, include_rotating=True)
    rotating  = [f for f in all_files if is_rotating_log(f)]
    conn = get_db()
    for f in rotating:
        conn.execute("INSERT OR IGNORE INTO log_hidden (filename) VALUES (?)", (f,))
    conn.commit()
    conn.close()
    flash(f"{len(rotating)} rotating log(s) hidden.", "info")
    return redirect(url_for("settings") + "#logfiles")

@app.route("/settings/logfiles/show-all", methods=["POST"])
@login_required
def settings_logfiles_show_all():
    if not current_user.is_admin:
        return redirect(url_for("settings"))
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM log_hidden").fetchone()[0]
    conn.execute("DELETE FROM log_hidden")
    conn.commit()
    flash(f"{count} file(s) made visible again.", "info")
    return redirect(url_for("settings") + "#logfiles")

@app.route("/settings/profile/add", methods=["POST"])
@login_required
def add_profile():
    if not current_user.is_admin:
        return redirect(url_for("index"))
    name          = request.form.get("name", "").strip()
    description   = request.form.get("description", "")
    level_error   = request.form.get("level_error", "ERROR,CRITICAL")
    level_warn    = request.form.get("level_warn",  "WARN,WARNING")
    level_info    = request.form.get("level_info",  "INFO")
    level_debug   = request.form.get("level_debug", "DEBUG")
    log_path_hint = request.form.get("log_path_hint", "")
    help_setup    = request.form.get("help_setup", "")
    help_mount    = request.form.get("help_mount", "")
    if not name:
        flash("Name ist erforderlich!", "error")
        return redirect(url_for("settings"))
    try:
        conn = get_db()
        conn.execute("""INSERT INTO profiles
            (name, description, author, version, source,
             level_error, level_warn, level_info, level_debug,
             log_path_hint, help_setup, help_mount)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, description, current_user.username, "1.0", "local",
             level_error, level_warn, level_info, level_debug,
             log_path_hint, help_setup, help_mount))
        conn.commit()
        conn.close()
        flash(f"Profil '{name}' angelegt!", "info")
    except Exception as e:
        flash(f"Fehler: {str(e)}", "error")
    return redirect(url_for("settings"))

@app.route("/settings/profile/delete/<int:profile_id>", methods=["POST"])
@login_required
def delete_profile(profile_id):
    if not current_user.is_admin:
        return redirect(url_for("index"))
    conn = get_db()
    row = conn.execute("SELECT source FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if row and row["source"] == "builtin":
        flash("Eingebaute Profile können nicht gelöscht werden!", "error")
        conn.close()
        return redirect(url_for("settings"))
    conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    conn.commit()
    conn.close()
    flash("Profil gelöscht!", "info")
    return redirect(url_for("settings"))

@app.route("/settings/assign", methods=["POST"])
@login_required
def assign_profile():
    if not current_user.is_admin:
        return redirect(url_for("index"))
    filename   = request.form.get("filename", "")
    profile_id = request.form.get("profile_id", 1)
    label      = request.form.get("label", "")
    if not filename:
        flash("Dateiname fehlt!", "error")
        return redirect(url_for("settings"))
    conn = get_db()
    conn.execute("""INSERT INTO log_assignments (filename, profile_id, label)
        VALUES (?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
        profile_id = excluded.profile_id,
        label = excluded.label""",
        (filename, profile_id, label))
    conn.commit()
    conn.close()
    flash(f"Profil für '{filename}' gespeichert!", "info")
    return redirect(url_for("settings"))

@app.route("/settings/language", methods=["POST"])
@login_required
def change_language():
    lang = request.form.get("language", "de")
    if lang not in ["de", "en"]:
        lang = "de"
    conn = get_db()
    conn.execute("UPDATE users SET language = ? WHERE id = ?",
                 (lang, current_user.id))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for("index"))

@app.route("/api/profiles")
@login_required
def api_profiles():
    conn = get_db()
    rows = conn.execute("SELECT * FROM profiles ORDER BY name").fetchall()
    conn.close()
    return jsonify({"profiles": [dict(r) for r in rows]})

@app.route("/api/profile/detect", methods=["POST"])
@login_required
def detect_profile():
    sample = request.json.get("sample", "")
    if not sample:
        return jsonify({"error": "Keine Beispielzeile"}), 400
    conn = get_db()
    profiles = conn.execute("SELECT * FROM profiles").fetchall()
    conn.close()
    sample_upper = sample.upper()
    best_match = None
    best_score = 0
    for p in profiles:
        score = 0
        for keyword in (p["level_error"] + "," + p["level_warn"] + "," +
                        p["level_info"] + "," + p["level_debug"]).split(","):
            kw = keyword.strip()
            if kw and kw.upper() in sample_upper:
                score += 1
        if score > best_score:
            best_score = score
            best_match = dict(p)
    if best_match and best_score > 0:
        return jsonify({"match": best_match, "score": best_score})
    return jsonify({"match": None, "score": 0})

@app.route("/api/github/profiles")
@login_required
def github_profiles():
    import urllib.request, json as jsonlib
    url = f"{GITHUB_BASE}/index.json"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = jsonlib.loads(r.read().decode())
        return jsonify({"profiles": data.get("profiles", []), "error": None})
    except Exception as e:
        return jsonify({"profiles": [], "error": str(e)})

@app.route("/api/github/install", methods=["POST"])
@login_required
def github_install():
    import urllib.request, json as jsonlib
    if not current_user.is_admin:
        return jsonify({"error": "Kein Admin"}), 403
    profile_url = request.json.get("url", "")
    if not profile_url or GITHUB_USER not in profile_url:
        return jsonify({"error": "Ungültige URL"}), 400
    try:
        with urllib.request.urlopen(profile_url, timeout=5) as r:
            p = jsonlib.loads(r.read().decode())
        conn = get_db()
        conn.execute("""INSERT INTO profiles
            (name, description, author, version, source,
             level_error, level_warn, level_info, level_debug,
             log_path_hint, help_setup, help_mount)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
            description=excluded.description, version=excluded.version,
            level_error=excluded.level_error, level_warn=excluded.level_warn,
            level_info=excluded.level_info,   level_debug=excluded.level_debug,
            log_path_hint=excluded.log_path_hint,
            help_setup=excluded.help_setup,   help_mount=excluded.help_mount""",
            (p["name"], p.get("description",""), p.get("author","community"),
             p.get("version","1.0"), "github",
             p.get("level_error","ERROR"), p.get("level_warn","WARN"),
             p.get("level_info","INFO"),   p.get("level_debug","DEBUG"),
             p.get("log_path_hint",""),    p.get("help_setup",""),
             p.get("help_mount","")))
        auto_assign_by_hint(conn)
        conn.commit()
        conn.close()
        return jsonify({"success": True, "name": p["name"], "help_mount": p.get("help_mount",""), "help_setup": p.get("help_setup","")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/system")
@login_required
def api_system():
    cpu = psutil.cpu_percent(interval=0.5)

    ram = psutil.virtual_memory()
    ram_pct   = ram.percent
    ram_used  = round(ram.used  / (1024**3), 1)
    ram_total = round(ram.total / (1024**3), 1)

    uptime_sec = int(time.time() - psutil.boot_time())
    days    = uptime_sec // 86400
    hours   = (uptime_sec % 86400) // 3600
    minutes = (uptime_sec % 3600) // 60
    uptime_str = f"{days}d {hours}h" if days > 0 else (f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m")

    # Disks: pro einzigartigem Device nur EINMAL zählen
    # (Docker sieht LVM-Volumes mehrfach gemountet – wir deduplizieren)
    IGNORE_FS = {"tmpfs", "devtmpfs", "overlay", "squashfs", "vfat", "efivarfs", ""}
    seen_devices = {}  # device → (used, total)

    for part in psutil.disk_partitions(all=False):
        if part.fstype in IGNORE_FS:
            continue
        if part.device in seen_devices:
            continue  # gleiche physische Disk – überspringen
        try:
            usage = psutil.disk_usage(part.mountpoint)
            seen_devices[part.device] = {
                "pct":      usage.percent,
                "used_gb":  round(usage.used  / (1024**3), 1),
                "total_gb": round(usage.total / (1024**3), 1),
            }
        except (PermissionError, OSError):
            continue

    disks = list(seen_devices.values())

    return jsonify({
        "cpu":       cpu,
        "ram_pct":   ram_pct,
        "ram_used":  ram_used,
        "ram_total": ram_total,
        "uptime":    uptime_str,
        "disks":     disks
    })

# ─── ROUTEN: MAIN ────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    conn = get_db()
    auto_assign_by_hint(conn)
    conn.commit()
    conn.close()
    files = get_log_files()
    return render_template("index.html",
                       log_files=files,
                       t=load_translation(get_user_lang()),
                       current_lang=get_user_lang())

@app.route("/api/logs")
@login_required
def api_logs():
    filename = request.args.get("file", "")
    search   = request.args.get("search", "")
    lines    = int(request.args.get("lines", 200))
    if not filename:
        return jsonify({"error": "Keine Datei angegeben"}), 400
    if ".." in filename:
        return jsonify({"error": "Ungültiger Dateiname"}), 400
    data = read_log_file(filename, search=search, lines=lines)
    return jsonify({"lines": data, "file": filename})

@app.route("/api/summary")
@login_required
def api_summary():
    conn = get_db()
    assigned = {row["filename"] for row in conn.execute("SELECT filename FROM log_assignments").fetchall()}
    files  = get_log_files()
    files  = [f for f in files if f in assigned]
    result = []
    for filename in files:
        lines = read_log_file(filename, lines=50)
        last3 = lines[-3:] if len(lines) >= 3 else lines
        last10 = lines[-10:]
        health = "ok"
        for line in last10:
            if line["level"] == "error":
                health = "error"; break
            elif line["level"] == "warn":
                health = "warn"
        filepath = os.path.join(LOG_DIR, filename)
        try:
            size = os.path.getsize(filepath)
            size_str = f"{size/1024/1024:.1f} MB" if size > 1024*1024 else f"{size/1024:.1f} KB"
        except:
            size_str = "?"
        # 24h Stats laden
        stats_rows = conn.execute(
            "SELECT error_count, warn_count FROM log_stats WHERE filename=? ORDER BY id DESC LIMIT 96",
            (filename,)
        ).fetchall()
        stats = [{"e": r["error_count"], "w": r["warn_count"]} for r in reversed(stats_rows)]
        result.append({"file": filename, "lines": last3,
                        "health": health, "size": size_str, "total": len(lines),
                        "stats": stats})
    conn.close()
    return jsonify({"files": result})

# Dieser Block muss in app.py eingefügt werden
# NACH dem bestehenden /api/summary Route

@app.route("/api/files/meta")
@login_required
def api_files_meta():
    """Alle Dateien mit hidden/rotating/assigned Status für den Explorer"""
    all_files  = get_log_files(include_hidden=True, include_rotating=True)
    hidden_set = get_hidden_files()
    conn = get_db()
    assigned_set = {row["filename"] for row in conn.execute("SELECT filename FROM log_assignments").fetchall()}
    conn.close()
    result = []
    for f in sorted(all_files):
        result.append({
            "filename": f,
            "hidden":   f in hidden_set,
            "rotating": is_rotating_log(f),
            "assigned": f in assigned_set
        })
    return jsonify({"files": result})


@app.route("/api/files/assign-toggle", methods=["POST"])
@login_required
def api_files_assign_toggle():
    filename = request.json.get("filename", "")
    if not filename or ".." in filename:
        return jsonify({"error": "Ungueltig"}), 400
    conn = get_db()
    existing = conn.execute("SELECT id FROM log_assignments WHERE filename = ?", (filename,)).fetchone()
    if existing:
        conn.execute("DELETE FROM log_assignments WHERE filename = ?", (filename,))
        assigned = False
    else:
        profile = conn.execute("SELECT id, name FROM profiles WHERE name = 'Standard' LIMIT 1").fetchone()
        profile_id = profile["id"] if profile else 1
        profile_name = profile["name"] if profile else "Standard"
        conn.execute("""INSERT INTO log_assignments (filename, profile_id, label)
            VALUES (?, ?, ?) ON CONFLICT(filename) DO UPDATE SET profile_id=excluded.profile_id""",
            (filename, profile_id, profile_name))
        assigned = True
    conn.commit()
    conn.close()
    return jsonify({"success": True, "assigned": assigned})

@app.route("/api/files/toggle", methods=["POST"])
@login_required
def api_files_toggle():
    """Hide/Show einer einzelnen Datei per AJAX (kein Reload nötig)"""
    data     = request.get_json()
    filename = (data or {}).get("filename", "").strip()
    action   = (data or {}).get("action", "hide")

    if not filename or ".." in filename:
        return jsonify({"success": False, "error": "invalid filename"})

    db = get_db()
    if action == "hide":
        db.execute("INSERT OR IGNORE INTO log_hidden (filename) VALUES (?)", (filename,))
    else:
        db.execute("DELETE FROM log_hidden WHERE filename = ?", (filename,))
    db.commit()
    return jsonify({"success": True, "filename": filename, "hidden": action == "hide"})

# ── In app.py einfügen: NACH api_files_toggle Route ──

@app.route("/api/files/delete", methods=["POST"])
@login_required
def api_files_delete():
    """Löscht eine Log-Datei physisch vom Dateisystem"""
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Admin required"})

    data     = request.get_json()
    filename = (data or {}).get("filename", "").strip()

    # Sicherheit: kein Path-Traversal
    if not filename or ".." in filename or filename.startswith("/"):
        return jsonify({"success": False, "error": "Invalid filename"})

    log_dir  = app.config.get("LOG_DIR", "/logs")
    filepath = os.path.join(log_dir, filename)

    # Sicherstellen dass die Datei wirklich im LOG_DIR liegt
    if not os.path.abspath(filepath).startswith(os.path.abspath(log_dir)):
        return jsonify({"success": False, "error": "Path not allowed"})

    if not os.path.isfile(filepath):
        return jsonify({"success": False, "error": "File not found"})

    try:
        os.remove(filepath)
        # Auch aus hidden-Tabelle entfernen
        db = get_db()
        db.execute("DELETE FROM log_hidden WHERE filename = ?", (filename,))
        db.commit()
        return jsonify({"success": True, "filename": filename})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/search")
@login_required
def api_search():
    q = request.args.get("q", "").strip()
    if len(q) < 4:
        return jsonify({"error": "min4", "results": []})
    files   = get_log_files()
    results = []
    for filename in files:
        lines   = read_log_file(filename, lines=1000)
        matches = [l for l in lines if q.lower() in l["text"].lower()]
        if matches:
            results.append({"file": filename, "count": len(matches), "lines": matches})
    return jsonify({"q": q, "results": results})

@app.route("/api/files")
@login_required
def api_files():
    return jsonify({"files": get_log_files()})

# ─── START ───────────────────────────────────────────────────
@app.route("/api/backup/export")
@login_required
def api_backup_export():
    if not current_user.is_admin:
        return jsonify({"error": "Kein Admin"}), 403
    import zipfile, io, datetime
    db_path = "/data/lovi.db"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, "lovi.db")
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"lovi-backup-{timestamp}.zip"
    )

@app.route("/api/backup/import", methods=["POST"])
@login_required
def api_backup_import():
    if not current_user.is_admin:
        return jsonify({"error": "Kein Admin"}), 403
    import zipfile, io, shutil
    f = request.files.get("backup")
    if not f:
        return jsonify({"error": "Keine Datei"}), 400
    try:
        zip_buffer = io.BytesIO(f.read())
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            if "lovi.db" not in zf.namelist():
                return jsonify({"error": "Ungültiges Backup – lovi.db nicht gefunden"}), 400
            # Backup der aktuellen DB
            shutil.copy("/data/lovi.db", "/data/lovi.db.bak")
            # Neue DB einspielen
            with zf.open("lovi.db") as src:
                with open("/data/lovi.db", "wb") as dst:
                    dst.write(src.read())
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/notifications/settings", methods=["GET"])
@login_required
def api_notifications_get():
    conn = get_db()
    row = conn.execute("SELECT * FROM notification_settings WHERE id=1").fetchone()
    conn.close()
    if row:
        d = dict(row)
        d.pop("smtp_pass", None)
        return jsonify(d)
    return jsonify({})

@app.route("/api/notifications/settings", methods=["POST"])
@login_required
def api_notifications_save():
    if not current_user.is_admin:
        return jsonify({"error": "Kein Admin"}), 403
    d = request.json
    conn = get_db()
    conn.execute("""INSERT INTO notification_settings
        (id, enabled, smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from, smtp_to,
         threshold_count, threshold_mins, cooldown_mins)
        VALUES (1,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
        enabled=excluded.enabled, smtp_host=excluded.smtp_host,
        smtp_port=excluded.smtp_port, smtp_user=excluded.smtp_user,
        smtp_pass=CASE WHEN excluded.smtp_pass='' THEN smtp_pass ELSE excluded.smtp_pass END,
        smtp_from=excluded.smtp_from, smtp_to=excluded.smtp_to,
        threshold_count=excluded.threshold_count, threshold_mins=excluded.threshold_mins,
        cooldown_mins=excluded.cooldown_mins""",
        (1 if d.get("enabled") else 0,
         d.get("smtp_host",""), int(d.get("smtp_port",587)),
         d.get("smtp_user",""), d.get("smtp_pass",""),
         d.get("smtp_from",""), d.get("smtp_to",""),
         int(d.get("threshold_count",5)), int(d.get("threshold_mins",10)),
         int(d.get("cooldown_mins",30))))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/notifications/test", methods=["POST"])
@login_required
def api_notifications_test():
    if not current_user.is_admin:
        return jsonify({"error": "Kein Admin"}), 403
    conn = get_db()
    row = conn.execute("SELECT * FROM notification_settings WHERE id=1").fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "No settings saved"}), 400
    try:
        send_alert_mail(dict(row), "test.log", 99)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

import threading
_notif_thread = threading.Thread(target=notification_worker, daemon=True)
_notif_thread.start()

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
