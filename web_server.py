#!/usr/bin/env python3
"""
web_server.py — Веб-интерфейс управления Bell Scheduler
Запуск: python3 web_server.py
Доступ: http://<IP-адрес Pi>:5000
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from functools import wraps

from flask import (Flask, render_template_string, request, jsonify,
                   session, redirect, url_for, send_from_directory)
from werkzeug.utils import secure_filename

# ═══════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════
BASE_DIR       = Path("/home/pi/bell_scheduler")
SOUNDS_DIR     = BASE_DIR / "sounds"
SCHEDULE_FILE  = BASE_DIR / "schedule.json"
TEMPLATES_FILE = BASE_DIR / "templates.json"
STATUS_FILE    = BASE_DIR / "status.json"
CONTROL_FILE   = BASE_DIR / "control.cmd"
LOG_FILE       = BASE_DIR / "logs" / "bells.log"

WEB_PASSWORD   = "qwerty12Q"   # ← поменяй пароль здесь
SECRET_KEY     = "bell_scheduler_secret_2024"
PORT           = 5000
MAX_SOUND_MB   = 20
ALLOWED_EXT    = {".mp3", ".wav", ".ogg"}

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = MAX_SOUND_MB * 1024 * 1024

# ═══════════════════════════════════════════════════
#  АВТОРИЗАЦИЯ
# ═══════════════════════════════════════════════════
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        if request.form.get("password") == WEB_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Неверный пароль"
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ═══════════════════════════════════════════════════
#  ОСНОВНЫЕ СТРАНИЦЫ
# ═══════════════════════════════════════════════════
@app.route("/")
@login_required
def index():
    return render_template_string(MAIN_HTML)

# ═══════════════════════════════════════════════════
#  API — СТАТУС И ЛОГ
# ═══════════════════════════════════════════════════
@app.route("/api/status")
@login_required
def api_status():
    try:
        if STATUS_FILE.exists():
            return jsonify(json.loads(STATUS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return jsonify({"running": False, "paused": False, "last_ring": None})

@app.route("/api/log")
@login_required
def api_log():
    n = int(request.args.get("n", 50))
    try:
        if LOG_FILE.exists():
            lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
            return jsonify({"lines": lines[-n:]})
    except Exception:
        pass
    return jsonify({"lines": []})

@app.route("/api/log/stream")
@login_required
def api_log_stream():
    """SSE — толкает новые строки лога в браузер сразу как они появляются."""
    def generate():
        # Сначала отдаём последние 50 строк
        try:
            if LOG_FILE.exists():
                lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
                for line in lines[-50:]:
                    yield f"data: {line}\n\n"
        except Exception:
            pass

        # Затем следим за файлом как tail -f
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                f.seek(0, 2)  # в конец файла
                while True:
                    line = f.readline()
                    if line:
                        yield f"data: {line.rstrip()}\n\n"
                    else:
                        # Пингуем каждые 2 сек чтобы соединение не закрылось
                        yield ": ping\n\n"
                        time.sleep(2)
        except GeneratorExit:
            pass
        except Exception:
            yield "data: [ошибка чтения лога]\n\n"

    return app.response_class(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # отключает буферизацию nginx если стоит
        }
    )

# ═══════════════════════════════════════════════════
#  API — УПРАВЛЕНИЕ
# ═══════════════════════════════════════════════════
@app.route("/api/command", methods=["POST"])
@login_required
def api_command():
    cmd = request.json.get("cmd", "").strip().lower()
    allowed = {"pause", "resume", "stop_sound", "stop", "reload", "restart"}
    if cmd not in allowed:
        return jsonify({"ok": False, "error": "Неизвестная команда"})
    try:
        if cmd == "restart":
            os.system("sudo systemctl restart bell_scheduler")
        else:
            CONTROL_FILE.write_text(cmd, encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ═══════════════════════════════════════════════════
#  API — ШАБЛОНЫ РАСПИСАНИЯ
# ═══════════════════════════════════════════════════
@app.route("/api/templates", methods=["GET"])
@login_required
def api_templates_get():
    try:
        if TEMPLATES_FILE.exists():
            return jsonify(json.loads(TEMPLATES_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return jsonify([])

@app.route("/api/templates", methods=["POST"])
@login_required
def api_templates_save():
    try:
        data = request.json
        TEMPLATES_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/apply_template", methods=["POST"])
@login_required
def api_apply_template():
    """Применить шаблон — сформировать schedule.json и перезагрузить расписание."""
    try:
        data        = request.json
        template    = data["template"]
        melody_start= data.get("melody_start", "bell_start.mp3")
        melody_end  = data.get("melody_end",   "bell_end.mp3")

        bells = []
        for b in template["bells"]:
            # Если у звонка своя мелодия — используем её, иначе общую
            sound = b.get("sound") or (melody_start if b["type"] == "start" else melody_end)
            bells.append({
                "id":          b["id"],
                "description": b["description"],
                "time":        b["time"],
                "days":        b["days"],
                "sound":       sound,
                "duration":    int(b.get("duration", 0)),
                "enabled":     b.get("enabled", True),
            })

        schedule = {"schedule": bells}
        SCHEDULE_FILE.write_text(
            json.dumps(schedule, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        CONTROL_FILE.write_text("reload", encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ═══════════════════════════════════════════════════
#  API — ЗВУКОТЕКА
# ═══════════════════════════════════════════════════
@app.route("/api/sounds", methods=["GET"])
@login_required
def api_sounds():
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(SOUNDS_DIR.iterdir()):
        if f.suffix.lower() in ALLOWED_EXT:
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "size_kb": round(stat.st_size / 1024, 1),
            })
    return jsonify(files)

@app.route("/api/sounds/upload", methods=["POST"])
@login_required
def api_sounds_upload():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Файл не выбран"})
    file = request.files["file"]
    if not file.filename:
        return jsonify({"ok": False, "error": "Имя файла пустое"})
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False, "error": f"Формат {ext} не поддерживается"})
    filename = secure_filename(file.filename)
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    file.save(SOUNDS_DIR / filename)
    return jsonify({"ok": True, "name": filename})

@app.route("/api/sounds/delete", methods=["POST"])
@login_required
def api_sounds_delete():
    name = request.json.get("name", "")
    path = SOUNDS_DIR / secure_filename(name)
    try:
        if path.exists() and path.parent == SOUNDS_DIR:
            path.unlink()
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "Файл не найден"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/sounds/trim", methods=["POST"])
@login_required
def api_sounds_trim():
    """Обрезает аудиофайл через ffmpeg и сохраняет с новым именем."""
    data      = request.json
    name      = secure_filename(data.get("name", ""))
    start     = float(data.get("start", 0))
    end       = float(data.get("end", 0))
    save_as   = secure_filename(data.get("save_as", ""))

    src = SOUNDS_DIR / name
    if not src.exists():
        return jsonify({"ok": False, "error": "Файл не найден"})
    if end <= start:
        return jsonify({"ok": False, "error": "Неверный диапазон"})
    if not save_as:
        save_as = name

    dst = SOUNDS_DIR / save_as
    duration = end - start

    # ffmpeg: -ss старт, -t длина, -c copy быстро без перекодирования (mp3 нужен перекод)
    ext = src.suffix.lower()
    if ext == ".wav":
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-t", str(duration),
               "-i", str(src), "-c", "copy", str(dst)]
    else:
        # mp3/ogg — нужен перекод чтобы обрезать точно
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-t", str(duration),
               "-i", str(src), "-q:a", "2", str(dst)]

    try:
        import subprocess
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[-300:]
            return jsonify({"ok": False, "error": "ffmpeg: " + err})
        return jsonify({"ok": True, "name": save_as})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "ffmpeg не установлен. Запусти: sudo apt install ffmpeg"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/sounds/<path:filename>")
@login_required
def serve_sound(filename):
    """Отдаёт звуковой файл для прослушивания в браузере."""
    return send_from_directory(str(SOUNDS_DIR), filename)

# ═══════════════════════════════════════════════════
#  HTML — СТРАНИЦА ВХОДА
# ═══════════════════════════════════════════════════
LOGIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вход — Управление звонками</title>
<link href="https://fonts.googleapis.com/css2?family=Unbounded:wght@400;700&family=Mulish:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#111009;--card:#1e1c17;--border:#2e2b22;
  --accent:#c9915a;--accent2:#b07a48;
  --text:#f0ebe3;--muted:#7a7468;
}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:var(--bg);font-family:'Mulish',sans-serif;color:var(--text)}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;
  padding:48px 40px;width:100%;max-width:400px;text-align:center}
.bell{font-size:48px;margin-bottom:16px}
h1{font-family:'Unbounded',sans-serif;font-size:18px;color:var(--accent);
  letter-spacing:0.05em;margin-bottom:6px}
.sub{color:var(--muted);font-size:13px;margin-bottom:36px}
input{width:100%;padding:13px 16px;background:#161510;border:1px solid var(--border);
  border-radius:8px;color:var(--text);font-family:'Mulish',sans-serif;font-size:15px;
  outline:none;transition:.2s}
input:focus{border-color:var(--accent)}
button{width:100%;margin-top:16px;padding:13px;background:var(--accent);
  border:none;border-radius:8px;color:#111;font-family:'Unbounded',sans-serif;
  font-size:14px;font-weight:700;cursor:pointer;transition:.2s;letter-spacing:.03em}
button:hover{background:var(--accent2)}
.error{color:#b5564e;font-size:13px;margin-top:12px}
</style>
</head>
<body>
<div class="card">
  
  <h1>Управление звонками</h1>
  <div class="sub">Raspberry Pi — введите пароль для входа</div>
  <form method="POST">
    <input type="password" name="password" placeholder="Пароль" autofocus>
    <button type="submit">Войти</button>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
  </form>
</div>
</body>
</html>"""

# ═══════════════════════════════════════════════════
#  HTML — ГЛАВНАЯ СТРАНИЦА
# ═══════════════════════════════════════════════════
MAIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Управление звонками</title>
<link href="https://fonts.googleapis.com/css2?family=Unbounded:wght@400;600;700&family=Mulish:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#111009;--panel:#161510;--card:#1e1c17;--card2:#252319;
  --border:#2e2b22;--border2:#3a3628;
  --accent:#c9915a;--accent2:#b07a48;--accentbg:#2a1f12;
  --green:#7a9e6e;--greenbg:#162213;
  --red:#b5564e;--redbg:#210f0d;
  --yellow:#c4a34a;--yellowbg:#221a08;
  --text:#f0ebe3;--muted:#7a7468;--muted2:#4a4640;
}
body{background:var(--bg);color:var(--text);font-family:'Mulish',sans-serif;min-height:100vh}

/* ── ШАПКА ── */
header{background:var(--panel);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 28px;height:60px;position:sticky;top:0;z-index:100}
.logo{display:flex;align-items:center;gap:10px}
.logo-icon{font-size:22px}
.logo-text{font-family:'Unbounded',sans-serif;font-size:15px;color:var(--accent)}
.logo-sub{font-size:12px;color:var(--muted);margin-left:4px}
.header-right{display:flex;align-items:center;gap:16px}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--muted2);transition:.3s}
.status-dot.online{background:var(--green);box-shadow:0 0 6px var(--green)}
.status-dot.paused{background:var(--yellow)}
#status-text{font-size:12px;color:var(--muted)}
.logout-btn{font-size:12px;color:var(--muted);text-decoration:none;
  padding:5px 12px;border:1px solid var(--border);border-radius:6px;transition:.2s}
.logout-btn:hover{border-color:var(--accent);color:var(--accent)}

/* ── НАВИГАЦИЯ ── */
nav{background:var(--panel);border-bottom:1px solid var(--border);
  display:flex;padding:0 20px;gap:4px}
.nav-btn{padding:14px 20px;font-family:'Mulish',sans-serif;font-size:13px;
  font-weight:600;color:var(--muted);background:none;border:none;
  border-bottom:2px solid transparent;cursor:pointer;transition:.2s;white-space:nowrap}
.nav-btn:hover{color:var(--text)}
.nav-btn.active{color:var(--accent);border-bottom-color:var(--accent)}

/* ── КОНТЕНТ ── */
main{padding:24px 28px;max-width:1200px;margin:0 auto}
.tab{display:none}.tab.active{display:block}
.page-title{font-family:'Unbounded',sans-serif;font-size:16px;
  color:var(--text);margin-bottom:20px}

/* ── КАРТОЧКИ ── */
.card{background:var(--card);border:1px solid var(--border);
  border-radius:12px;padding:20px}
.card-title{font-size:12px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--muted);margin-bottom:16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}

/* ── КНОПКИ ── */
.btn{padding:9px 18px;border:none;border-radius:8px;font-family:'Mulish',sans-serif;
  font-size:13px;font-weight:700;cursor:pointer;transition:.18s;display:inline-flex;
  align-items:center;gap:7px;white-space:nowrap}
.btn-accent{background:var(--accent);color:#111}
.btn-accent:hover{background:var(--accent2)}
.btn-green{background:var(--greenbg);color:var(--green);border:1px solid var(--green)}
.btn-green:hover{background:var(--green);color:#111}
.btn-red{background:var(--redbg);color:var(--red);border:1px solid var(--red)}
.btn-red:hover{background:var(--red);color:#fff}
.btn-yellow{background:var(--yellowbg);color:var(--yellow);border:1px solid var(--yellow)}
.btn-yellow:hover{background:var(--yellow);color:#111}
.btn-ghost{background:var(--card2);color:var(--muted);border:1px solid var(--border)}
.btn-ghost:hover{color:var(--text);border-color:var(--border2)}
.btn-sm{padding:5px 12px;font-size:12px}
.btn:disabled{opacity:.4;cursor:not-allowed}

/* ── ИНПУТЫ ── */
input,select,textarea{background:var(--bg);border:1px solid var(--border);
  border-radius:8px;color:var(--text);font-family:'Mulish',sans-serif;
  font-size:13px;padding:9px 12px;outline:none;transition:.2s;width:100%}
input:focus,select:focus{border-color:var(--accent)}
select option{background:var(--card)}
label{font-size:12px;color:var(--muted);display:block;margin-bottom:5px}

/* ── СТАТУС БЛОК ── */
.status-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.stat-item{background:var(--card2);border:1px solid var(--border);
  border-radius:8px;padding:14px 16px}
.stat-label{font-size:11px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:6px}
.stat-val{font-size:15px;font-weight:700}
.val-green{color:var(--green)}.val-red{color:var(--red)}
.val-yellow{color:var(--yellow)}.val-accent{color:var(--accent)}

/* ── ЛОГ ── */
#log-box{background:#0a0a08;border:1px solid var(--border);border-radius:8px;
  padding:14px;height:280px;overflow-y:auto;font-family:'Courier New',monospace;
  font-size:12px;line-height:1.7;color:#c8b89a}
#log-box .log-bell{color:var(--accent)}
#log-box .log-warn{color:var(--yellow)}
#log-box .log-err{color:var(--red)}

/* ── КНОПКИ УПРАВЛЕНИЯ ── */
.ctrl-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px}
.ctrl-btn{padding:13px;font-size:13px;justify-content:center;width:100%}

/* ── ШАБЛОНЫ ── */
.tmpl-list{display:flex;flex-direction:column;gap:6px;margin-bottom:14px;
  max-height:260px;overflow-y:auto}
.tmpl-item{background:var(--card2);border:1px solid var(--border);
  border-radius:8px;padding:11px 14px;cursor:pointer;transition:.15s;
  display:flex;align-items:center;justify-content:space-between}
.tmpl-item:hover{border-color:var(--border2)}
.tmpl-item.selected{border-color:var(--accent);background:var(--accentbg)}
.tmpl-name{font-weight:700;font-size:13px}
.tmpl-count{font-size:11px;color:var(--muted)}

/* ── ПРЕДПРОСМОТР РАСПИСАНИЯ ── */
.bell-list{display:flex;flex-direction:column;gap:4px;
  max-height:320px;overflow-y:auto}
.bell-row{display:grid;grid-template-columns:60px 1fr 100px 60px;
  gap:8px;align-items:center;padding:8px 12px;
  background:var(--card2);border-radius:6px;font-size:13px}
.bell-time{font-weight:700;font-family:'Unbounded',sans-serif;font-size:12px}
.bell-time.start{color:var(--green)}
.bell-time.end{color:var(--yellow)}
.bell-desc{color:var(--text)}
.bell-days{color:var(--muted);font-size:11px}
.bell-sound{font-size:11px;color:var(--muted);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.badge{display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700}
.badge-start{background:var(--greenbg);color:var(--green)}
.badge-end{background:var(--yellowbg);color:var(--yellow)}

/* ── ЗВУКОТЕКА ── */
.sound-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.sound-card{background:var(--card2);border:1px solid var(--border);
  border-radius:8px;padding:12px 14px;transition:.15s}
.sound-card:hover{border-color:var(--border2)}
.sound-name{font-size:13px;font-weight:600;margin-bottom:3px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sound-size{font-size:11px;color:var(--muted);margin-bottom:10px}
.sound-actions{display:flex;gap:6px}

/* ── UPLOAD ZONE ── */
.upload-zone{border:2px dashed var(--border2);border-radius:10px;
  padding:30px;text-align:center;cursor:pointer;transition:.2s;margin-bottom:16px}
.upload-zone:hover,.upload-zone.drag{border-color:var(--accent);background:var(--accentbg)}
.upload-icon{font-size:32px;margin-bottom:8px}
.upload-text{font-size:13px;color:var(--muted)}
.upload-text b{color:var(--accent)}
#upload-input{display:none}

/* ── ТОСТ ── */
#toast{position:fixed;bottom:24px;right:24px;background:var(--card2);
  border:1px solid var(--border2);border-radius:10px;padding:12px 18px;
  font-size:13px;font-weight:600;opacity:0;transform:translateY(10px);
  transition:.25s;pointer-events:none;z-index:999}
#toast.show{opacity:1;transform:translateY(0)}

/* ── МОДАЛКА РЕДАКТОРА ── */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);
  z-index:200;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:var(--card);border:1px solid var(--border2);
  border-radius:14px;padding:28px;width:560px;max-width:95vw;
  max-height:90vh;overflow-y:auto}
.modal-title{font-family:'Unbounded',sans-serif;font-size:14px;
  color:var(--accent);margin-bottom:22px}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.form-group{margin-bottom:12px}
.day-checks{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.day-check{display:none}
.day-label{padding:5px 11px;background:var(--card2);border:1px solid var(--border);
  border-radius:6px;font-size:12px;cursor:pointer;transition:.15s;user-select:none}
.day-check:checked+.day-label{background:var(--accentbg);border-color:var(--accent);color:var(--accent)}
.modal-actions{display:flex;gap:10px;margin-top:20px;justify-content:flex-end}

/* ── ВЫБОР ДЛИНЫ ── */
.dur-btns{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.dur-btn{padding:5px 12px;background:var(--card2);border:1px solid var(--border);
  border-radius:6px;font-size:12px;cursor:pointer;transition:.15s;user-select:none}
.dur-btn.active{background:var(--accentbg);border-color:var(--accent);color:var(--accent)}

/* ── РЕДАКТОР ОБРЕЗКИ ── */
.trim-modal .modal{width:680px}
#waveform-wrap{position:relative;margin:16px 0;cursor:crosshair;user-select:none}
#waveform-canvas{width:100%;height:100px;border-radius:8px;display:block;
  background:#0a0a08;border:1px solid var(--border)}
#waveform-sel{position:absolute;top:0;height:100%;background:rgba(201,145,90,.18);
  border-left:2px solid var(--accent);border-right:2px solid var(--accent);
  pointer-events:none;transition:none}
.trim-times{display:flex;gap:12px;margin-bottom:12px}
.trim-times .form-group{flex:1;margin:0}
.trim-info{font-size:12px;color:var(--muted);margin-bottom:14px}
.waveform-loading{text-align:center;padding:30px;color:var(--muted);font-size:13px}
#trim-preview-btn{background:var(--greenbg);color:var(--green);
  border:1px solid var(--green)}
#trim-preview-btn:hover{background:var(--green);color:#111}
#trim-preview-btn.playing{background:var(--redbg);color:var(--red);
  border-color:var(--red)}

/* ── АДАПТИВ ── */
@media(max-width:640px){
  main{padding:14px 12px}
  .grid2,.grid3,.status-grid,.ctrl-grid{grid-template-columns:1fr}
  .bell-row{grid-template-columns:56px 1fr;grid-template-rows:auto auto}
  .bell-days,.bell-sound{grid-column:1/-1}
}
</style>
</head>
<body>

<header>
  <div class="logo">
    <span class="logo-text">Управление звонками</span>
    <span class="logo-sub">Raspberry Pi</span>
  </div>
  <div class="header-right">
    <div class="status-dot" id="status-dot"></div>
    <span id="status-text">загрузка...</span>
    <a href="/logout" class="logout-btn">Выйти</a>
  </div>
</header>

<nav>
  <button class="nav-btn active" onclick="switchTab('dashboard')">Дашборд</button>
  <button class="nav-btn" onclick="switchTab('schedule')">Расписание</button>
  <button class="nav-btn" onclick="switchTab('sounds')">Звукотека</button>
</nav>

<main>

<!-- ══════════ ДАШБОРД ══════════ -->
<div class="tab active" id="tab-dashboard">
  <div class="grid2" style="margin-bottom:16px">

    <div class="card">
      <div class="card-title">Статус системы</div>
      <div class="status-grid">
        <div class="stat-item">
          <div class="stat-label">Сервис</div>
          <div class="stat-val" id="s-running">—</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">Режим</div>
          <div class="stat-val" id="s-paused">—</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">Последний звонок</div>
          <div class="stat-val val-accent" id="s-time">—</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">Описание</div>
          <div class="stat-val" id="s-desc" style="font-size:12px">—</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Управление</div>
      <div class="ctrl-grid">
        <button class="btn btn-ghost ctrl-btn" onclick="sendCmd('pause')">Пауза</button>
        <button class="btn btn-ghost ctrl-btn" onclick="sendCmd('resume')">Снять паузу</button>
        <button class="btn btn-ghost ctrl-btn" onclick="sendCmd('stop_sound')">Стоп звонка</button>
        <button class="btn btn-ghost ctrl-btn" onclick="sendCmd('reload')">Перезагр. расп.</button>
      </div>
      <button class="btn btn-ghost" style="width:100%" onclick="sendCmd('restart')">Рестарт сервиса</button>
    </div>
  </div>

  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
      <div class="card-title" style="margin:0">Лог событий</div>
      <button class="btn btn-ghost btn-sm" id="log-refresh-btn">↓ В конец</button>
    </div>
    <div id="log-box">загрузка...</div>
  </div>
</div>

<!-- ══════════ РАСПИСАНИЕ ══════════ -->
<div class="tab" id="tab-schedule">
  <div class="grid2">

    <div class="card">
      <div class="card-title">Шаблоны</div>
      <div class="tmpl-list" id="tmpl-list"></div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-green btn-sm" onclick="newTemplate()">Новый</button>
        <button class="btn btn-ghost btn-sm" onclick="editTemplate()">Изменить</button>
        <button class="btn btn-red btn-sm"   onclick="delTemplate()">Удалить</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Предпросмотр</div>
      <div class="bell-list" id="bell-preview"></div>

      <div style="margin-top:14px;padding-top:14px;border-top:1px solid var(--border)">
        <div class="form-row" style="margin-bottom:10px">
          <div class="form-group" style="margin:0">
            <label>Мелодия начала пары</label>
            <select id="sel-start"></select>
          </div>
          <div class="form-group" style="margin:0">
            <label>Мелодия конца пары</label>
            <select id="sel-end"></select>
          </div>
        </div>
        <button class="btn btn-accent" style="width:100%;justify-content:center;padding:13px"
          onclick="applyTemplate()">ПРИМЕНИТЬ НА Pi</button>
        <div id="active-tmpl" style="font-size:12px;color:var(--muted);margin-top:8px;text-align:center"></div>
      </div>
    </div>
  </div>
</div>

<!-- ══════════ ЗВУКОТЕКА ══════════ -->
<div class="tab" id="tab-sounds">
  <div class="card" style="margin-bottom:16px">
    <div class="card-title">Загрузить мелодию</div>
    <div class="upload-zone" id="upload-zone" onclick="document.getElementById('upload-input').click()">
      <div class="upload-icon" style="font-size:28px;color:var(--muted)">♪</div>
      <div class="upload-text">Нажмите или <b>перетащите файл</b><br>MP3, WAV, OGG — до 20 МБ</div>
    </div>
    <input type="file" id="upload-input" accept=".mp3,.wav,.ogg" multiple onchange="uploadFiles(this.files)">
    <div id="upload-status" style="font-size:12px;color:var(--muted)"></div>
  </div>

  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <div class="card-title" style="margin:0">Все мелодии</div>
      <button class="btn btn-ghost btn-sm" onclick="loadSounds()">Обновить</button>
    </div>
    <div class="sound-grid" id="sound-grid">загрузка...</div>
  </div>
</div>

</main>

<!-- ══ МОДАЛКА РЕДАКТОРА ШАБЛОНА ══ -->
<div class="modal-overlay" id="tmpl-modal">
  <div class="modal">
    <div class="modal-title" id="modal-title">Шаблон расписания</div>
    <div class="form-group">
      <label>Название шаблона</label>
      <input type="text" id="tmpl-name-input" placeholder="Стандартное расписание">
    </div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <div style="font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em">Звонки</div>
      <button class="btn btn-green btn-sm" onclick="addBellRow()">Добавить звонок</button>
    </div>
    <div id="bells-editor" style="display:flex;flex-direction:column;gap:6px;max-height:320px;overflow-y:auto;margin-bottom:12px"></div>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
      <button class="btn btn-accent" onclick="saveTemplate()">Сохранить</button>
    </div>
  </div>
</div>

<!-- ══ МОДАЛКА ДОБАВЛЕНИЯ ЗВОНКА ══ -->
<div class="modal-overlay" id="bell-modal">
  <div class="modal" style="width:480px">
    <div class="modal-title">Звонок</div>
    <input type="hidden" id="bell-edit-idx" value="-1">
    <div class="form-row">
      <div class="form-group">
        <label>Время (ЧЧ:ММ)</label>
        <input type="time" id="b-time">
      </div>
      <div class="form-group">
        <label>Тип</label>
        <select id="b-type">
          <option value="start">Начало пары</option>
          <option value="end">Конец пары</option>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label>Описание</label>
      <input type="text" id="b-desc" placeholder="Начало 1-й пары">
    </div>
    <div class="form-group">
      <label>Мелодия (оставь пустым — будет общая)</label>
      <select id="b-sound">
        <option value="">— Общая мелодия —</option>
      </select>
    </div>
    <div class="form-group">
      <label>Длина звонка</label>
      <div class="dur-btns" id="dur-btns">
        <span class="dur-btn active" data-dur="0">Полная</span>
        <span class="dur-btn" data-dur="10">10 сек</span>
        <span class="dur-btn" data-dur="15">15 сек</span>
        <span class="dur-btn" data-dur="20">20 сек</span>
        <span class="dur-btn" data-dur="30">30 сек</span>
        <span class="dur-btn" data-dur="45">45 сек</span>
        <span class="dur-btn" data-dur="60">60 сек</span>
      </div>
    </div>
    <div class="form-group">
      <label>Дни недели</label>
      <div class="day-checks">
        <input type="checkbox" class="day-check" id="d-mon" value="mon"><label class="day-label" for="d-mon">Пн</label>
        <input type="checkbox" class="day-check" id="d-tue" value="tue"><label class="day-label" for="d-tue">Вт</label>
        <input type="checkbox" class="day-check" id="d-wed" value="wed"><label class="day-label" for="d-wed">Ср</label>
        <input type="checkbox" class="day-check" id="d-thu" value="thu"><label class="day-label" for="d-thu">Чт</label>
        <input type="checkbox" class="day-check" id="d-fri" value="fri"><label class="day-label" for="d-fri">Пт</label>
        <input type="checkbox" class="day-check" id="d-sat" value="sat"><label class="day-label" for="d-sat">Сб</label>
        <input type="checkbox" class="day-check" id="d-sun" value="sun"><label class="day-label" for="d-sun">Вс</label>
      </div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeBellModal()">Отмена</button>
      <button class="btn btn-accent" onclick="saveBellRow()">Сохранить</button>
    </div>
  </div>
</div>

<!-- ══ МОДАЛКА ОБРЕЗКИ ЗВУКА ══ -->
<div class="modal-overlay trim-modal" id="trim-modal">
  <div class="modal">
    <div class="modal-title">Редактор звука</div>

    <div style="font-size:13px;color:var(--muted);margin-bottom:10px" id="trim-filename"></div>

    <!-- Волновая форма -->
    <div id="waveform-wrap">
      <canvas id="waveform-canvas" height="100"></canvas>
      <div id="waveform-sel" style="left:0;width:0"></div>
    </div>
    <div class="trim-info" id="trim-info">Выдели фрагмент мышкой на волновой форме</div>

    <!-- Ввод времени вручную -->
    <div class="trim-times">
      <div class="form-group">
        <label>Начало (сек)</label>
        <input type="number" id="trim-start" value="0" min="0" step="0.1" oninput="updateSelFromInputs()">
      </div>
      <div class="form-group">
        <label>Конец (сек)</label>
        <input type="number" id="trim-end" value="0" min="0" step="0.1" oninput="updateSelFromInputs()">
      </div>
      <div class="form-group">
        <label>Сохранить как</label>
        <input type="text" id="trim-saveas" placeholder="имя_файла.mp3">
      </div>
    </div>

    <!-- Кнопки -->
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <button class="btn" id="trim-preview-btn" onclick="togglePreview()">Прослушать фрагмент</button>
      <button class="btn btn-ghost" onclick="selectAll()">↔ Весь файл</button>
      <div style="flex:1"></div>
      <button class="btn btn-ghost" onclick="closeTrimModal()">Отмена</button>
      <button class="btn btn-accent" onclick="saveTrim()">Сохранить</button>
    </div>

    <div id="trim-status" style="font-size:12px;color:var(--muted);margin-top:10px"></div>
  </div>
</div>

<div id="toast"></div>

<script>
// ════════════════════════════════════════
//  СОСТОЯНИЕ
// ════════════════════════════════════════
let templates = [];
let selectedTmplIdx = -1;
let editBells = [];
let allSounds = [];
let selectedDur = 0;

const DAYS_RU = {mon:'Пн',tue:'Вт',wed:'Ср',thu:'Чт',fri:'Пт',sat:'Сб',sun:'Вс'};

// ════════════════════════════════════════
//  УТИЛИТЫ
// ════════════════════════════════════════
function toast(msg, ok=true){
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.borderColor = ok ? 'var(--green)' : 'var(--red)';
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 2800);
}

function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  event.target.classList.add('active');
  if(name==='schedule') loadSoundSelects();
  if(name==='sounds')   loadSounds();
}

async function api(url, opts={}){
  const r = await fetch(url, {headers:{'Content-Type':'application/json'}, ...opts});
  return r.json();
}

// ════════════════════════════════════════
//  СТАТУС И ЛОГ
// ════════════════════════════════════════
async function loadStatus(){
  try{
    const s = await api('/api/status');
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');

    if(s.running && !s.paused){
      dot.className='status-dot online';
      txt.textContent='Работает';
    } else if(s.paused){
      dot.className='status-dot paused';
      txt.textContent='На паузе';
    } else {
      dot.className='status-dot';
      txt.textContent='Остановлен';
    }

    document.getElementById('s-running').innerHTML =
      s.running ? '<span class="val-green">✅ Работает</span>' : '<span class="val-red">🔴 Остановлен</span>';
    document.getElementById('s-paused').innerHTML =
      s.paused  ? '<span class="val-yellow">⏸ Пауза</span>'   : '<span class="val-green">▶ Активен</span>';

    const lr = s.last_ring;
    if(lr){
      document.getElementById('s-time').textContent = (lr.day||'').toUpperCase()+' '+lr.time;
      document.getElementById('s-desc').textContent = lr.description||'—';
    }
  }catch(e){}
}

// ── SSE лог: мгновенное обновление ──────────────────
function initLogStream(){
  const box = document.getElementById('log-box');
  box.innerHTML = '';

  const es = new EventSource('/api/log/stream');

  es.onmessage = function(e){
    if(!e.data || e.data.trim()==='') return;
    const div = document.createElement('div');
    div.textContent = e.data;
    // Подсветка
    if(e.data.includes('ЗВОНОК'))                       div.className='log-bell';
    else if(e.data.includes('WARNING')||e.data.includes('⏸')||e.data.includes('⚠')) div.className='log-warn';
    else if(e.data.includes('ERROR') ||e.data.includes('❌'))  div.className='log-err';

    box.appendChild(div);
    // Держим не больше 200 строк в DOM
    while(box.children.length > 200) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;

    // Обновляем статус при новом звонке
    if(e.data.includes('ЗВОНОК')) loadStatus();
  };

  es.onerror = function(){
    // При обрыве — переподключимся через 3 сек
    es.close();
    setTimeout(initLogStream, 3000);
  };

  // Кнопка "Обновить" — просто скроллит вниз
  document.getElementById('log-refresh-btn').onclick = ()=>{
    box.scrollTop = box.scrollHeight;
  };
}

function escHtml(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ════════════════════════════════════════
//  УПРАВЛЕНИЕ
// ════════════════════════════════════════
async function sendCmd(cmd){
  const labels = {pause:'Пауза',resume:'Снята пауза',stop_sound:'Стоп звонка',
    reload:'Расписание перезагружено',restart:'Сервис перезапускается...'};
  const r = await api('/api/command',{method:'POST',body:JSON.stringify({cmd})});
  if(r.ok){ toast('✅ '+labels[cmd]); setTimeout(loadStatus,1500); }
  else toast('❌ '+r.error, false);
}

// ════════════════════════════════════════
//  ШАБЛОНЫ
// ════════════════════════════════════════
async function loadTemplates(){
  try{
    const data = await api('/api/templates');
    templates = Array.isArray(data) ? data : [];
    renderTmplList();
  }catch(e){}
}

function renderTmplList(){
  const el = document.getElementById('tmpl-list');
  if(!templates.length){ el.innerHTML='<div style="color:var(--muted);font-size:13px;padding:8px">Нет шаблонов</div>'; return; }
  el.innerHTML = templates.map((t,i)=>`
    <div class="tmpl-item ${i===selectedTmplIdx?'selected':''}" onclick="selectTmpl(${i})">
      <span class="tmpl-name">${escHtml(t.name)}</span>
      <span class="tmpl-count">${t.bells.length} зв.</span>
    </div>`).join('');
}

function selectTmpl(i){
  selectedTmplIdx = i;
  renderTmplList();
  renderPreview();
}

function renderPreview(){
  const el = document.getElementById('bell-preview');
  const t = templates[selectedTmplIdx];
  if(!t){ el.innerHTML='<div style="color:var(--muted);font-size:13px;padding:12px">← Выбери шаблон</div>'; return; }
  el.innerHTML = t.bells.map(b=>{
    const days = (b.days||[]).map(d=>DAYS_RU[d]||d).join(' ');
    const icon = b.type==='start'?'▶':'◼';
    const dur  = b.duration ? ` · ${b.duration}с` : '';
    return `<div class="bell-row">
      <span class="bell-time ${b.type}">${icon} ${b.time}</span>
      <span class="bell-desc">${escHtml(b.description)}</span>
      <span class="bell-days">${days}</span>
      <span class="bell-sound">${escHtml(b.sound||'—')}${dur}</span>
    </div>`;
  }).join('');
}

async function applyTemplate(){
  const t = templates[selectedTmplIdx];
  if(!t){ toast('❌ Выбери шаблон', false); return; }
  const ms = document.getElementById('sel-start').value;
  const me = document.getElementById('sel-end').value;
  const r  = await api('/api/apply_template',{method:'POST',
    body:JSON.stringify({template:t, melody_start:ms, melody_end:me})});
  if(r.ok){
    document.getElementById('active-tmpl').textContent='Активный: '+t.name;
    toast('✅ Шаблон «'+t.name+'» применён на Pi!');
  } else toast('❌ '+r.error, false);
}

// ── Редактор шаблона ──
function newTemplate(){
  editBells = [];
  document.getElementById('tmpl-name-input').value = '';
  document.getElementById('modal-title').textContent = 'Новый шаблон';
  document.getElementById('bell-edit-idx').dataset.tmpl = '-1';
  renderBellsEditor();
  document.getElementById('tmpl-modal').classList.add('open');
}

function editTemplate(){
  if(selectedTmplIdx<0){ toast('❌ Выбери шаблон', false); return; }
  const t = templates[selectedTmplIdx];
  editBells = t.bells.map(b=>({...b}));
  document.getElementById('tmpl-name-input').value = t.name;
  document.getElementById('modal-title').textContent = 'Редактировать шаблон';
  document.getElementById('bell-edit-idx').dataset.tmpl = selectedTmplIdx;
  renderBellsEditor();
  document.getElementById('tmpl-modal').classList.add('open');
}

function closeModal(){ document.getElementById('tmpl-modal').classList.remove('open'); }

function renderBellsEditor(){
  const el = document.getElementById('bells-editor');
  if(!editBells.length){ el.innerHTML='<div style="color:var(--muted);font-size:12px;padding:8px">Нет звонков</div>'; return; }
  el.innerHTML = editBells.map((b,i)=>{
    const days = (b.days||[]).map(d=>DAYS_RU[d]||d).join(' ');
    const icon = b.type==='start'?'▶':'◼';
    const col  = b.type==='start'?'var(--green)':'var(--yellow)';
    return `<div style="display:flex;align-items:center;gap:8px;background:var(--card2);
      border:1px solid var(--border);border-radius:7px;padding:8px 12px">
      <span style="color:${col};font-weight:700;font-size:13px;min-width:55px">${icon} ${b.time}</span>
      <span style="flex:1;font-size:13px">${escHtml(b.description)}</span>
      <span style="font-size:11px;color:var(--muted)">${days}</span>
      <button class="btn btn-ghost btn-sm" onclick="openEditBell(${i})">✏</button>
      <button class="btn btn-red btn-sm" onclick="deleteBell(${i})">✕</button>
    </div>`;
  }).join('');
}

function addBellRow(){ openEditBell(-1); }

function openEditBell(idx){
  const b = idx>=0 ? editBells[idx] : null;
  document.getElementById('bell-edit-idx').value = idx;
  document.getElementById('b-time').value  = b ? b.time  : '08:00';
  document.getElementById('b-type').value  = b ? b.type  : 'start';
  document.getElementById('b-desc').value  = b ? b.description : '';
  document.getElementById('b-sound').value = b ? (b.sound||'') : '';
  selectedDur = b ? (b.duration||0) : 0;
  document.querySelectorAll('.dur-btn').forEach(d=>{
    d.classList.toggle('active', parseInt(d.dataset.dur)===selectedDur);
  });
  document.querySelectorAll('.day-check').forEach(c=>{
    c.checked = b ? (b.days||[]).includes(c.value) : ['mon','tue','wed','thu','fri'].includes(c.value);
  });
  document.getElementById('bell-modal').classList.add('open');
}

function closeBellModal(){ document.getElementById('bell-modal').classList.remove('open'); }

function saveBellRow(){
  const idx   = parseInt(document.getElementById('bell-edit-idx').value);
  const days  = [...document.querySelectorAll('.day-check:checked')].map(c=>c.value);
  const bell  = {
    id:          idx>=0 ? editBells[idx].id : (Date.now()%100000),
    time:        document.getElementById('b-time').value,
    type:        document.getElementById('b-type').value,
    description: document.getElementById('b-desc').value || 'Звонок',
    sound:       document.getElementById('b-sound').value || '',
    duration:    selectedDur,
    days:        days,
    enabled:     true,
  };
  if(idx>=0) editBells[idx]=bell; else editBells.push(bell);
  editBells.sort((a,b)=>a.time.localeCompare(b.time));
  renderBellsEditor();
  closeBellModal();
}

function deleteBell(i){
  editBells.splice(i,1);
  renderBellsEditor();
}

async function saveTemplate(){
  const name = document.getElementById('tmpl-name-input').value.trim();
  if(!name){ toast('❌ Введи название', false); return; }
  const tmplIdx = parseInt(document.getElementById('bell-edit-idx').dataset.tmpl||'-1');
  const tmpl = {
    id:    tmplIdx>=0 ? templates[tmplIdx].id : Date.now()%100000,
    name,
    bells: editBells,
  };
  if(tmplIdx>=0) templates[tmplIdx]=tmpl; else templates.push(tmpl);
  const r = await api('/api/templates',{method:'POST',body:JSON.stringify(templates)});
  if(r.ok){ toast('✅ Шаблон сохранён'); closeModal(); renderTmplList(); renderPreview(); }
  else toast('❌ '+r.error, false);
}

async function delTemplate(){
  if(selectedTmplIdx<0){ toast('❌ Выбери шаблон', false); return; }
  if(!confirm('Удалить шаблон «'+templates[selectedTmplIdx].name+'»?')) return;
  templates.splice(selectedTmplIdx,1);
  selectedTmplIdx=-1;
  const r = await api('/api/templates',{method:'POST',body:JSON.stringify(templates)});
  if(r.ok){ toast('Удалено'); renderTmplList(); renderPreview(); }
}

// ════════════════════════════════════════
//  ЗВУКОТЕКА
// ════════════════════════════════════════
async function loadSounds(){
  try{
    allSounds = await api('/api/sounds');
    renderSounds();
  }catch(e){}
}

function renderSounds(){
  const el = document.getElementById('sound-grid');
  if(!allSounds.length){ el.innerHTML='<div style="color:var(--muted);font-size:13px">Нет файлов</div>'; return; }
  el.innerHTML = allSounds.map(s=>`
    <div class="sound-card">
      <div class="sound-name" title="${escHtml(s.name)}">${escHtml(s.name)}</div>
      <div class="sound-size">${s.size_kb} КБ</div>
      <div class="sound-actions">
        <button class="btn btn-ghost btn-sm" onclick="playSound('${escHtml(s.name)}')">Слушать</button>
        <button class="btn btn-ghost btn-sm" onclick="openTrimModal('${escHtml(s.name)}')">Обрезать</button>
        <button class="btn btn-red btn-sm"   onclick="deleteSound('${escHtml(s.name)}')">✕</button>
      </div>
    </div>`).join('');
}

async function loadSoundSelects(){
  try{
    if(!allSounds.length) allSounds = await api('/api/sounds');
    const opts = allSounds.map(s=>`<option value="${escHtml(s.name)}">${escHtml(s.name)}</option>`).join('');
    const bOpts = '<option value="">— Общая мелодия —</option>' + opts;
    document.getElementById('sel-start').innerHTML = opts;
    document.getElementById('sel-end').innerHTML   = opts;
    document.querySelectorAll('#b-sound').forEach(s=>s.innerHTML=bOpts);
  }catch(e){}
}

let currentAudio = null;
function playSound(name){
  if(currentAudio){ currentAudio.pause(); currentAudio=null; }
  currentAudio = new Audio('/sounds/'+encodeURIComponent(name));
  currentAudio.play();
}

async function deleteSound(name){
  if(!confirm('Удалить файл «'+name+'»?')) return;
  const r = await api('/api/sounds/delete',{method:'POST',body:JSON.stringify({name})});
  if(r.ok){ toast('Удалено'); loadSounds(); }
  else toast('❌ '+r.error, false);
}

async function uploadFiles(files){
  const status = document.getElementById('upload-status');
  for(const file of files){
    status.textContent = 'Загружается: '+file.name+'...';
    const fd = new FormData();
    fd.append('file', file);
    try{
      const r = await fetch('/api/sounds/upload',{method:'POST',body:fd});
      const d = await r.json();
      if(d.ok){ toast('✅ '+d.name+' загружен'); await loadSounds(); await loadSoundSelects(); }
      else toast('❌ '+d.error, false);
    }catch(e){ toast('❌ Ошибка загрузки', false); }
  }
  status.textContent = '';
}

// Drag & drop
const zone = document.getElementById('upload-zone');
zone.addEventListener('dragover',e=>{e.preventDefault();zone.classList.add('drag')});
zone.addEventListener('dragleave',()=>zone.classList.remove('drag'));
zone.addEventListener('drop',e=>{
  e.preventDefault(); zone.classList.remove('drag');
  uploadFiles(e.dataTransfer.files);
});

// Длина звонка
document.getElementById('dur-btns').addEventListener('click',e=>{
  if(e.target.classList.contains('dur-btn')){
    selectedDur = parseInt(e.target.dataset.dur);
    document.querySelectorAll('.dur-btn').forEach(b=>b.classList.toggle('active',b===e.target));
  }
});

// ════════════════════════════════════════
//  РЕДАКТОР ОБРЕЗКИ ЗВУКА
// ════════════════════════════════════════
let trimFile      = null;   // имя файла
let trimDuration  = 0;      // длина в сек
let trimAudioCtx  = null;
let trimBuffer    = null;
let trimSource    = null;   // текущий воспроизводимый источник
let trimPlaying   = false;
let selStart      = 0;
let selEnd        = 0;
let dragStartX    = null;

function openTrimModal(name){
  trimFile = name;
  selStart = 0; selEnd = 0;
  trimBuffer = null;
  document.getElementById('trim-filename').textContent = name;
  document.getElementById('trim-saveas').value = name;
  document.getElementById('trim-status').textContent = '';
  document.getElementById('trim-info').textContent = 'Загрузка волновой формы...';
  document.getElementById('trim-modal').classList.add('open');
  clearCanvas();
  loadWaveform(name);
}

function closeTrimModal(){
  stopPreview();
  document.getElementById('trim-modal').classList.remove('open');
}

// ── Загрузка и рисование волновой формы ──
async function loadWaveform(name){
  try{
    const resp = await fetch('/sounds/'+encodeURIComponent(name));
    const buf  = await resp.arrayBuffer();
    if(!trimAudioCtx) trimAudioCtx = new (window.AudioContext||window.webkitAudioContext)();
    trimBuffer  = await trimAudioCtx.decodeAudioData(buf);
    trimDuration = trimBuffer.duration;
    selStart = 0;
    selEnd   = trimDuration;
    document.getElementById('trim-start').value = selStart.toFixed(2);
    document.getElementById('trim-end').value   = selEnd.toFixed(2);
    document.getElementById('trim-end').max     = trimDuration;
    document.getElementById('trim-start').max   = trimDuration;
    document.getElementById('trim-info').textContent =
      `Длина: ${trimDuration.toFixed(2)} сек — выдели фрагмент мышкой`;
    drawWaveform(trimBuffer);
    updateSel();
  }catch(e){
    document.getElementById('trim-info').textContent = '❌ Не удалось загрузить файл: '+e.message;
  }
}

function drawWaveform(buffer){
  const canvas = document.getElementById('waveform-canvas');
  canvas.width = canvas.offsetWidth * window.devicePixelRatio;
  const ctx    = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const data   = buffer.getChannelData(0);
  const step   = Math.ceil(data.length / W);
  const mid    = H / 2;

  ctx.fillStyle = '#0a0a08';
  ctx.fillRect(0, 0, W, H);

  // Сетка
  ctx.strokeStyle = '#1e1c17';
  ctx.lineWidth   = 1;
  for(let i=0;i<10;i++){
    ctx.beginPath(); ctx.moveTo(W*i/10,0); ctx.lineTo(W*i/10,H); ctx.stroke();
  }

  // Волна
  ctx.strokeStyle = '#c9915a';
  ctx.lineWidth   = 1;
  ctx.beginPath();
  for(let x=0;x<W;x++){
    let min=1,max=-1;
    for(let j=0;j<step;j++){
      const v = data[x*step+j]||0;
      if(v<min) min=v; if(v>max) max=v;
    }
    const yMax = mid - max*mid*0.9;
    const yMin = mid - min*mid*0.9;
    x===0 ? ctx.moveTo(x,yMax) : ctx.lineTo(x,yMax);
    ctx.lineTo(x, yMin);
  }
  ctx.stroke();

  // Подписи времени
  ctx.fillStyle = '#7a7468';
  ctx.font = `${10*window.devicePixelRatio}px monospace`;
  const marks = 10;
  for(let i=0;i<=marks;i++){
    const t = trimDuration*i/marks;
    const x = W*i/marks;
    ctx.fillText(t.toFixed(1)+'s', x+2, H-2);
  }
}

function clearCanvas(){
  const canvas = document.getElementById('waveform-canvas');
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#0a0a08';
  ctx.fillRect(0,0,canvas.width,canvas.height);
}

// ── Выделение мышкой ──
const wrapEl = ()=>document.getElementById('waveform-wrap');
const canvasEl = ()=>document.getElementById('waveform-canvas');

function xToTime(x){
  const rect = canvasEl().getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (x - rect.left) / rect.width));
  return ratio * trimDuration;
}

document.addEventListener('DOMContentLoaded',()=>{
  const wrap = document.getElementById('waveform-wrap');
  wrap.addEventListener('mousedown', e=>{
    if(!trimBuffer) return;
    stopPreview();
    dragStartX = e.clientX;
    selStart = xToTime(e.clientX);
    selEnd   = selStart;
    updateSel();
  });
  wrap.addEventListener('mousemove', e=>{
    if(dragStartX===null) return;
    const t = xToTime(e.clientX);
    if(t < xToTime(dragStartX)){ selStart=t; selEnd=xToTime(dragStartX); }
    else { selStart=xToTime(dragStartX); selEnd=t; }
    updateSel();
  });
  document.addEventListener('mouseup', ()=>{ dragStartX=null; });

  // Touch support
  wrap.addEventListener('touchstart', e=>{
    if(!trimBuffer) return;
    dragStartX = e.touches[0].clientX;
    selStart = xToTime(e.touches[0].clientX);
    selEnd   = selStart;
    updateSel();
  },{passive:true});
  wrap.addEventListener('touchmove', e=>{
    if(dragStartX===null) return;
    const t = xToTime(e.touches[0].clientX);
    if(t < xToTime(dragStartX)){ selStart=t; selEnd=xToTime(dragStartX); }
    else { selStart=xToTime(dragStartX); selEnd=t; }
    updateSel();
  },{passive:true});
  document.addEventListener('touchend', ()=>{ dragStartX=null; });
});

function updateSel(){
  const canvas  = canvasEl();
  const rect    = canvas.getBoundingClientRect();
  const W       = rect.width;
  const selEl   = document.getElementById('waveform-sel');
  const left    = (selStart / trimDuration) * W;
  const width   = ((selEnd - selStart) / trimDuration) * W;
  selEl.style.left  = left  + 'px';
  selEl.style.width = Math.max(0,width) + 'px';
  document.getElementById('trim-start').value = selStart.toFixed(2);
  document.getElementById('trim-end').value   = selEnd.toFixed(2);
  const dur = selEnd - selStart;
  document.getElementById('trim-info').textContent =
    dur > 0
      ? `Выбрано: ${selStart.toFixed(2)}с — ${selEnd.toFixed(2)}с (длина ${dur.toFixed(2)}с)`
      : `Длина файла: ${trimDuration.toFixed(2)} сек — выдели фрагмент мышкой`;
}

function updateSelFromInputs(){
  selStart = parseFloat(document.getElementById('trim-start').value)||0;
  selEnd   = parseFloat(document.getElementById('trim-end').value)||0;
  updateSel();
}

function selectAll(){
  selStart=0; selEnd=trimDuration; updateSel();
}

// ── Превью выделенного фрагмента ──
function togglePreview(){
  if(trimPlaying) stopPreview();
  else startPreview();
}

function startPreview(){
  if(!trimBuffer||selEnd<=selStart) return;
  if(!trimAudioCtx) return;
  stopPreview();
  trimSource = trimAudioCtx.createBufferSource();
  trimSource.buffer = trimBuffer;
  trimSource.connect(trimAudioCtx.destination);
  const dur = selEnd - selStart;
  trimSource.start(0, selStart, dur);
  trimPlaying = true;
  const btn = document.getElementById('trim-preview-btn');
  btn.textContent = 'Остановить';
  btn.classList.add('playing');
  trimSource.onended = ()=>{ trimPlaying=false; btn.textContent='Прослушать фрагмент'; btn.classList.remove('playing'); };
}

function stopPreview(){
  if(trimSource){ try{ trimSource.stop(); }catch(e){} trimSource=null; }
  trimPlaying = false;
  const btn = document.getElementById('trim-preview-btn');
  if(btn){ btn.textContent='Прослушать фрагмент'; btn.classList.remove('playing'); }
}

// ── Сохранение ──
async function saveTrim(){
  if(!trimFile){ toast('❌ Файл не выбран',false); return; }
  if(selEnd<=selStart){ toast('❌ Выдели фрагмент',false); return; }
  const saveAs = document.getElementById('trim-saveas').value.trim();
  if(!saveAs){ toast('❌ Введи имя файла',false); return; }
  const status = document.getElementById('trim-status');
  status.textContent = '⏳ Сохраняю...';
  const r = await api('/api/sounds/trim',{method:'POST', body:JSON.stringify({
    name: trimFile, start: selStart, end: selEnd, save_as: saveAs
  })});
  if(r.ok){
    status.textContent = '';
    toast('✅ Сохранено: '+r.name);
    closeTrimModal();
    loadSounds();
  } else {
    status.textContent = '❌ '+r.error;
    toast('❌ '+r.error, false);
  }
}
async function init(){
  await loadStatus();
  initLogStream();   // SSE — мгновенный лог, без поллинга
  await loadTemplates();
  await loadSounds();
}

setInterval(loadStatus, 10000);  // статус каждые 10 сек
init();
</script>
</body>
</html>"""

# ═══════════════════════════════════════════════════
#  ЗАПУСК
# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"🌐 Веб-интерфейс запущен: http://0.0.0.0:{PORT}")
    print(f"📁 Данные: {BASE_DIR}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
