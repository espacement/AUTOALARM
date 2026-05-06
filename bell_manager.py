#!/usr/bin/env python3
"""
Bell Scheduler Manager — десктопное приложение для управления
звонками на Raspberry Pi. Всё через SSH, без консоли.

Установка зависимостей:
    pip install customtkinter paramiko pygame
"""

import json
import os
import sys
import threading
import time
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

# ─── SSH / SFTP ────────────────────────────────────────────────────────
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

# ─── Аудио превью ──────────────────────────────────────────────────────
try:
    import pygame
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="pygame")
    pygame.mixer.init()
    HAS_PYGAME = True
except Exception:
    HAS_PYGAME = False

# ═══════════════════════════════════════════════════════════════════════
#  КОНСТАНТЫ
# ═══════════════════════════════════════════════════════════════════════
APP_DIR       = Path(__file__).parent
CONFIG_FILE   = APP_DIR / "manager_config.json"
TEMPLATES_FILE= APP_DIR / "templates.json"
REMOTE_BASE   = "/home/pi/bell_scheduler"

DAYS_RU = {"mon":"Пн","tue":"Вт","wed":"Ср","thu":"Чт","fri":"Пт","sat":"Сб","sun":"Вс"}
DAYS_ALL= list(DAYS_RU.keys())

# ── Цветовая схема — тёплая тёмно-бежевая ─────────────────────────────
C_BG      = "#1a1916"
C_PANEL   = "#232120"
C_CARD    = "#2c2a27"
C_CARD2   = "#353230"
C_ACCENT  = "#c9915a"
C_ACCENT2 = "#b07a48"
C_SEL     = "#4a3828"
C_GREEN   = "#7a9e6e"
C_RED     = "#b5564e"
C_YELLOW  = "#c4a34a"
C_TEXT    = "#f0ebe3"
C_MUTED   = "#8a837a"
C_BORDER  = "#3d3830"
C_HDR     = "#1e1c19"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ═══════════════════════════════════════════════════════════════════════
#  МЕНЕДЖЕР КОНФИГУРАЦИИ
# ═══════════════════════════════════════════════════════════════════════
class ConfigManager:
    DEFAULTS = {
        "host": "", "port": 22, "username": "pi", "password": "",
        "remote_base": REMOTE_BASE,
        "melody_start": "bell_start.mp3",
        "melody_end":   "bell_end.mp3",
        "local_melody_start": "",
        "local_melody_end":   "",
    }

    def __init__(self):
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except Exception:
                pass

    def save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def __getitem__(self, k): return self.data.get(k, "")
    def __setitem__(self, k, v): self.data[k] = v


# ═══════════════════════════════════════════════════════════════════════
#  МЕНЕДЖЕР ШАБЛОНОВ
# ═══════════════════════════════════════════════════════════════════════
class TemplateManager:
    def __init__(self):
        self.templates = []
        self.load()
        if not self.templates:
            self._add_defaults()

    def load(self):
        if TEMPLATES_FILE.exists():
            try:
                with open(TEMPLATES_FILE, encoding="utf-8") as f:
                    self.templates = json.load(f)
            except Exception:
                self.templates = []

    def save(self):
        with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.templates, f, ensure_ascii=False, indent=2)

    def _add_defaults(self):
        self.templates = [
            {
                "id": 1, "name": "Стандартное (Пн–Пт)",
                "bells": [
                    {"id":1,"time":"08:00","description":"Начало 1-й пары","type":"start","days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":2,"time":"09:30","description":"Конец 1-й пары",  "type":"end",  "days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":3,"time":"09:45","description":"Начало 2-й пары","type":"start","days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":4,"time":"11:15","description":"Конец 2-й пары",  "type":"end",  "days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":5,"time":"11:30","description":"Начало 3-й пары","type":"start","days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":6,"time":"13:00","description":"Конец 3-й пары",  "type":"end",  "days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":7,"time":"13:45","description":"Начало 4-й пары","type":"start","days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":8,"time":"15:15","description":"Конец 4-й пары",  "type":"end",  "days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":9,"time":"15:30","description":"Начало 5-й пары","type":"start","days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":10,"time":"17:00","description":"Конец 5-й пары", "type":"end",  "days":["mon","tue","wed","thu","fri"],"enabled":True},
                ]
            },
            {
                "id": 2, "name": "Сокращённое",
                "bells": [
                    {"id":1,"time":"08:00","description":"Начало 1-й пары","type":"start","days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":2,"time":"09:20","description":"Конец 1-й пары",  "type":"end",  "days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":3,"time":"09:30","description":"Начало 2-й пары","type":"start","days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":4,"time":"10:50","description":"Конец 2-й пары",  "type":"end",  "days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":5,"time":"11:00","description":"Начало 3-й пары","type":"start","days":["mon","tue","wed","thu","fri"],"enabled":True},
                    {"id":6,"time":"12:20","description":"Конец 3-й пары",  "type":"end",  "days":["mon","tue","wed","thu","fri"],"enabled":True},
                ]
            },
        ]
        self.save()

    def get_names(self):
        return [t["name"] for t in self.templates]

    def get_by_name(self, name):
        return next((t for t in self.templates if t["name"] == name), None)

    def get_by_id(self, tid):
        return next((t for t in self.templates if t["id"] == tid), None)

    def add(self, name, bells):
        new_id = max((t["id"] for t in self.templates), default=0) + 1
        self.templates.append({"id": new_id, "name": name, "bells": bells})
        self.save()
        return new_id

    def update(self, tid, name, bells):
        for t in self.templates:
            if t["id"] == tid:
                t["name"] = name
                t["bells"] = bells
        self.save()

    def delete(self, tid):
        self.templates = [t for t in self.templates if t["id"] != tid]
        self.save()

    def to_schedule_json(self, template, melody_start, melody_end):
        bells = []
        for b in template["bells"]:
            sound = melody_start if b["type"] == "start" else melody_end
            bells.append({
                "id":          b["id"],
                "description": b["description"],
                "time":        b["time"],
                "days":        b["days"],
                "sound":       sound,
                "enabled":     b["enabled"],
            })
        return {"schedule": bells}


# ═══════════════════════════════════════════════════════════════════════
#  SSH МЕНЕДЖЕР
# ═══════════════════════════════════════════════════════════════════════
class SSHManager:
    def __init__(self, config: ConfigManager):
        self.cfg = config
        self._client = None
        self.connected = False

    def connect(self):
        if not HAS_PARAMIKO:
            raise RuntimeError("Установи paramiko: pip install paramiko")
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=self.cfg["host"],
            port=int(self.cfg["port"]),
            username=self.cfg["username"],
            password=self.cfg["password"],
            timeout=10,
        )
        self.connected = True

    def disconnect(self):
        if self._client:
            self._client.close()
        self.connected = False
        self._client = None

    def exec(self, cmd: str) -> tuple[str, str]:
        _, stdout, stderr = self._client.exec_command(cmd, timeout=15)
        return stdout.read().decode(), stderr.read().decode()

    def send_file(self, local_path: str, remote_path: str):
        sftp = self._client.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()

    def send_text(self, content: str, remote_path: str):
        """Отправить строку как файл на Pi."""
        import io
        sftp = self._client.open_sftp()
        with sftp.file(remote_path, "w") as f:
            f.write(content)
        sftp.close()

    def read_remote(self, remote_path: str) -> str:
        sftp = self._client.open_sftp()
        try:
            with sftp.file(remote_path, "r") as f:
                return f.read().decode("utf-8")
        finally:
            sftp.close()

    def send_command(self, cmd: str):
        remote = f"{self.cfg['remote_base']}/control.cmd"
        self.send_text(cmd, remote)

    def get_status(self) -> dict:
        remote = f"{self.cfg['remote_base']}/status.json"
        try:
            txt = self.read_remote(remote)
            return json.loads(txt)
        except Exception:
            return {}

    def get_log_tail(self, n=30) -> str:
        out, _ = self.exec(
            f"tail -n {n} {self.cfg['remote_base']}/logs/bells.log 2>/dev/null"
        )
        return out

    def ensure_remote_dirs(self):
        base = self.cfg["remote_base"]
        self.exec(f"mkdir -p {base}/sounds {base}/logs")


# ═══════════════════════════════════════════════════════════════════════
#  МОК SSH — тестовый режим без Raspberry Pi
# ═══════════════════════════════════════════════════════════════════════
class MockSSHManager:
    """
    Эмулирует SSH-соединение локально.
    Все «удалённые» файлы хранятся в папке test_pi/ рядом со скриптом.
    """
    MOCK_DIR = APP_DIR / "test_pi"

    def __init__(self, config: ConfigManager):
        self.cfg = config
        self.connected = False
        self._log_lines: list[str] = []
        self._status: dict = {
            "running": True, "paused": False,
            "last_ring": None, "test_mode": True,
            "updated_at": datetime.now().isoformat(),
        }

    def connect(self):
        self.MOCK_DIR.mkdir(parents=True, exist_ok=True)
        (self.MOCK_DIR / "sounds").mkdir(exist_ok=True)
        (self.MOCK_DIR / "logs").mkdir(exist_ok=True)
        self.connected = True
        self._log("🧪 [ТЕСТ] Подключение к эмулятору Pi установлено")
        self._log(f"🧪 [ТЕСТ] Файлы хранятся в: {self.MOCK_DIR}")
        self._save_status()

    def disconnect(self):
        self.connected = False

    def exec(self, cmd: str) -> tuple[str, str]:
        # Просто логируем команду и возвращаем пустой результат
        self._log(f"$ {cmd}")
        return "", ""

    def send_file(self, local_path: str, remote_path: str):
        # Кладём файл в test_pi/sounds/
        import shutil
        fname = Path(remote_path).name
        dest  = self.MOCK_DIR / "sounds" / fname
        shutil.copy2(local_path, dest)
        self._log(f"📤 [ТЕСТ] Файл загружен: {fname} → {dest}")

    def send_text(self, content: str, remote_path: str):
        # Пишем текст в локальный файл, сохраняя структуру путей
        fname = Path(remote_path).name
        dest  = self.MOCK_DIR / fname
        dest.write_text(content, encoding="utf-8")
        self._log(f"📝 [ТЕСТ] Файл записан: {fname}")

    def read_remote(self, remote_path: str) -> str:
        fname = Path(remote_path).name
        dest  = self.MOCK_DIR / fname
        if dest.exists():
            return dest.read_text(encoding="utf-8")
        raise FileNotFoundError(f"[ТЕСТ] Файл не найден: {dest}")

    def send_command(self, cmd: str):
        self._log(f"🎛  [ТЕСТ] Команда получена: {cmd}")
        if cmd == "pause":
            self._status["paused"] = True
            self._log("⏸  [ТЕСТ] Система на паузе")
        elif cmd == "resume":
            self._status["paused"] = False
            self._log("▶  [ТЕСТ] Система возобновлена")
        elif cmd == "stop_sound":
            self._log("⏹  [ТЕСТ] Текущий звонок остановлен")
        elif cmd == "stop":
            self._status["running"] = False
            self._log("🔴 [ТЕСТ] Сервис остановлен")
        elif cmd == "reload":
            self._log("🔄 [ТЕСТ] Расписание перезагружено")
            # Показываем следующий звонок из загруженного schedule.json
            self._simulate_next_ring()
        self._save_status()

    def get_status(self) -> dict:
        self._status["updated_at"] = datetime.now().isoformat()
        return dict(self._status)

    def get_log_tail(self, n=30) -> str:
        return "\n".join(self._log_lines[-n:])

    def ensure_remote_dirs(self):
        (self.MOCK_DIR / "sounds").mkdir(parents=True, exist_ok=True)
        (self.MOCK_DIR / "logs").mkdir(parents=True, exist_ok=True)

    # ── Внутренние методы ────────────────────────────────────────────
    def _log(self, msg: str):
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} [INFO] {msg}"
        self._log_lines.append(line)
        # Дублируем в файл
        log_file = self.MOCK_DIR / "logs" / "bells.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _save_status(self):
        self._status["updated_at"] = datetime.now().isoformat()
        dest = self.MOCK_DIR / "status.json"
        dest.write_text(
            json.dumps(self._status, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _simulate_next_ring(self):
        """После reload — симулирует ближайший звонок из расписания."""
        sched_file = self.MOCK_DIR / "schedule.json"
        if not sched_file.exists():
            return
        try:
            data = json.loads(sched_file.read_text(encoding="utf-8"))
            now_str = datetime.now().strftime("%H:%M")
            day_key = ["mon","tue","wed","thu","fri","sat","sun"][datetime.now().weekday()]
            upcoming = [
                b for b in data.get("schedule", [])
                if b.get("enabled") and b.get("time","") >= now_str
                   and day_key in b.get("days", [])
            ]
            if upcoming:
                nx = upcoming[0]
                self._log(
                    f"📅 [ТЕСТ] Ближайший звонок: {nx['time']} — {nx['description']}"
                )
                self._status["last_ring"] = {
                    "id": nx.get("id"), "time": nx["time"],
                    "day": day_key, "description": nx["description"],
                    "sound": nx.get("sound",""), "timestamp": datetime.now().isoformat(),
                }
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ UI-КОМПОНЕНТЫ
# ═══════════════════════════════════════════════════════════════════════

def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=12, **kw)

def label(parent, text, size=13, bold=False, color=C_TEXT, **kw):
    return ctk.CTkLabel(parent, text=text,
                        font=ctk.CTkFont("Segoe UI", size, "bold" if bold else "normal"),
                        text_color=color, **kw)

def btn(parent, text, cmd, color=C_ACCENT, width=140, **kw):
    return ctk.CTkButton(parent, text=text, command=cmd,
                         fg_color=color, hover_color=_darken(color),
                         font=ctk.CTkFont("Segoe UI", 13, "bold"),
                         corner_radius=8, width=width, **kw)

def _darken(hex_color):
    r = int(hex_color[1:3],16); g = int(hex_color[3:5],16); b = int(hex_color[5:7],16)
    f = 0.78
    return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

def entry(parent, textvariable=None, placeholder="", width=200, show="", **kw):
    return ctk.CTkEntry(parent, textvariable=textvariable,
                        placeholder_text=placeholder,
                        fg_color=C_BG, border_color=C_BORDER,
                        text_color=C_TEXT, width=width,
                        font=ctk.CTkFont("Segoe UI", 13),
                        show=show, **kw)

def bind_recursive(widget, event, callback):
    """Биндит событие на виджет и все его дочерние элементы."""
    widget.bind(event, callback)
    for child in widget.winfo_children():
        bind_recursive(child, event, callback)


# ═══════════════════════════════════════════════════════════════════════
#  ДИАЛОГ РЕДАКТОРА ЗВОНКА
# ═══════════════════════════════════════════════════════════════════════
class BellDialog(ctk.CTkToplevel):
    def __init__(self, parent, bell=None, title="Звонок"):
        super().__init__(parent)
        self.title(title)
        self.geometry("480x420")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)
        self.grab_set()
        self.result = None

        self._build(bell)

    def _build(self, b):
        p = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=0)
        p.pack(fill="both", expand=True, padx=20, pady=20)

        label(p, "⏰  Редактор звонка", size=16, bold=True).pack(pady=(16,20))

        # Время
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=6)
        label(row, "Время (ЧЧ:ММ):", width=160, anchor="w").pack(side="left")
        self.var_time = tk.StringVar(value=b["time"] if b else "08:00")
        entry(row, textvariable=self.var_time, width=120).pack(side="left")

        # Описание
        row2 = ctk.CTkFrame(p, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=6)
        label(row2, "Описание:", width=160, anchor="w").pack(side="left")
        self.var_desc = tk.StringVar(value=b["description"] if b else "")
        entry(row2, textvariable=self.var_desc, width=240).pack(side="left")

        # Тип
        row3 = ctk.CTkFrame(p, fg_color="transparent")
        row3.pack(fill="x", padx=20, pady=6)
        label(row3, "Тип:", width=160, anchor="w").pack(side="left")
        self.var_type = tk.StringVar(value=b["type"] if b else "start")
        ctk.CTkSegmentedButton(row3, values=["start","end"],
                               variable=self.var_type,
                               fg_color=C_BG, selected_color=C_ACCENT,
                               font=ctk.CTkFont("Segoe UI", 13)).pack(side="left")

        # Дни
        label(p, "Дни недели:", anchor="w").pack(fill="x", padx=20, pady=(12,4))
        days_frame = ctk.CTkFrame(p, fg_color="transparent")
        days_frame.pack(padx=20, pady=4)
        active_days = b["days"] if b else ["mon","tue","wed","thu","fri"]
        self.day_vars = {}
        for d, ru in DAYS_RU.items():
            v = tk.BooleanVar(value=d in active_days)
            self.day_vars[d] = v
            ctk.CTkCheckBox(days_frame, text=ru, variable=v,
                            fg_color=C_ACCENT, hover_color=C_ACCENT2,
                            font=ctk.CTkFont("Segoe UI", 13),
                            text_color=C_TEXT).pack(side="left", padx=6)

        # Включён
        row4 = ctk.CTkFrame(p, fg_color="transparent")
        row4.pack(fill="x", padx=20, pady=12)
        label(row4, "Активен:", width=160, anchor="w").pack(side="left")
        self.var_enabled = tk.BooleanVar(value=b["enabled"] if b else True)
        ctk.CTkSwitch(row4, text="", variable=self.var_enabled,
                      progress_color=C_GREEN).pack(side="left")

        # Кнопки
        btns = ctk.CTkFrame(p, fg_color="transparent")
        btns.pack(pady=16)
        btn(btns, "✓  Сохранить", self._save, color=C_GREEN, width=160).pack(side="left", padx=8)
        btn(btns, "✕  Отмена",    self.destroy, color="#555555", width=120).pack(side="left")

    def _save(self):
        t = self.var_time.get().strip()
        if len(t) != 5 or t[2] != ":" or not t[:2].isdigit() or not t[3:].isdigit():
            mb.showerror("Ошибка", "Неверный формат времени. Используй ЧЧ:ММ", parent=self)
            return
        self.result = {
            "time":        t,
            "description": self.var_desc.get().strip() or f"Звонок {t}",
            "type":        self.var_type.get(),
            "days":        [d for d, v in self.day_vars.items() if v.get()],
            "enabled":     self.var_enabled.get(),
        }
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════
#  ДИАЛОГ РЕДАКТОРА ШАБЛОНА
# ═══════════════════════════════════════════════════════════════════════
class TemplateDialog(ctk.CTkToplevel):
    def __init__(self, parent, template=None):
        super().__init__(parent)
        self.title("Редактор шаблона")
        self.geometry("720x620")
        self.configure(fg_color=C_BG)
        self.grab_set()
        self.result = None

        # Копия звонков для редактирования
        self.bells = list(template["bells"]) if template else []
        for i, b in enumerate(self.bells):
            self.bells[i] = dict(b)

        self._build(template)

    def _build(self, t):
        top = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=0)
        top.pack(fill="both", expand=True, padx=0, pady=0)

        # Заголовок
        hdr = ctk.CTkFrame(top, fg_color=C_CARD, corner_radius=0, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        label(hdr, "📋  Шаблон расписания", size=16, bold=True).pack(side="left", padx=20, pady=16)

        body = ctk.CTkFrame(top, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=12)

        # Имя шаблона
        name_row = ctk.CTkFrame(body, fg_color="transparent")
        name_row.pack(fill="x", pady=(0,12))
        label(name_row, "Название:", width=100, anchor="w").pack(side="left")
        self.var_name = tk.StringVar(value=t["name"] if t else "Новый шаблон")
        entry(name_row, textvariable=self.var_name, width=380).pack(side="left", padx=8)

        # Список звонков
        label(body, "Звонки:", anchor="w").pack(fill="x", pady=(4,6))

        list_frame = ctk.CTkScrollableFrame(body, fg_color=C_BG, corner_radius=8, height=340)
        list_frame.pack(fill="both", expand=True)
        self.list_frame = list_frame
        self._render_bells()

        # Кнопки управления списком
        ctrl = ctk.CTkFrame(body, fg_color="transparent")
        ctrl.pack(fill="x", pady=12)
        btn(ctrl, "＋  Добавить звонок", self._add_bell,  color=C_GREEN,  width=190).pack(side="left", padx=4)
        btn(ctrl, "✓  Сохранить шаблон", self._save,      color=C_ACCENT, width=190).pack(side="left", padx=4)
        btn(ctrl, "✕  Отмена",           self.destroy,    color="#555555", width=120).pack(side="left", padx=4)

    def _render_bells(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        if not self.bells:
            label(self.list_frame, "Нет звонков. Нажмите «Добавить».", color=C_MUTED).pack(pady=20)
            return

        for i, b in enumerate(self.bells):
            row = ctk.CTkFrame(self.list_frame,
                               fg_color=C_CARD if i % 2 == 0 else C_PANEL,
                               corner_radius=6)
            row.pack(fill="x", pady=2, padx=4)

            type_icon = "▶" if b["type"] == "start" else "⏹"
            type_color= C_GREEN if b["type"] == "start" else C_YELLOW
            days_str  = " ".join(DAYS_RU[d] for d in b["days"])
            status    = "" if b["enabled"] else "  [откл]"

            label(row, f"{type_icon} {b['time']}", bold=True, color=type_color, width=80).pack(side="left", padx=(10,4), pady=8)
            label(row, b["description"] + status, color=C_TEXT, width=280, anchor="w").pack(side="left", padx=4)
            label(row, days_str, color=C_MUTED, width=160, anchor="w").pack(side="left", padx=4)

            idx = i
            btn(row, "✏", lambda idx=idx: self._edit_bell(idx),  color=C_ACCENT,  width=36, height=28).pack(side="right", padx=4, pady=6)
            btn(row, "✕", lambda idx=idx: self._del_bell(idx),   color=C_RED,     width=36, height=28).pack(side="right", padx=2)

    def _add_bell(self):
        dlg = BellDialog(self, title="Добавить звонок")
        self.wait_window(dlg)
        if dlg.result:
            new_id = max((b["id"] for b in self.bells), default=0) + 1
            dlg.result["id"] = new_id
            dlg.result["enabled"] = dlg.result.get("enabled", True)
            self.bells.append(dlg.result)
            self.bells.sort(key=lambda x: x["time"])
            self._render_bells()

    def _edit_bell(self, idx):
        dlg = BellDialog(self, bell=self.bells[idx], title="Редактировать звонок")
        self.wait_window(dlg)
        if dlg.result:
            dlg.result["id"] = self.bells[idx]["id"]
            self.bells[idx] = dlg.result
            self.bells.sort(key=lambda x: x["time"])
            self._render_bells()

    def _del_bell(self, idx):
        if mb.askyesno("Удалить?", f"Удалить звонок {self.bells[idx]['time']}?", parent=self):
            self.bells.pop(idx)
            self._render_bells()

    def _save(self):
        name = self.var_name.get().strip()
        if not name:
            mb.showerror("Ошибка", "Введи название шаблона", parent=self)
            return
        self.result = {"name": name, "bells": self.bells}
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════
#  ГЛАВНОЕ ПРИЛОЖЕНИЕ
# ═══════════════════════════════════════════════════════════════════════
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Управление звонками — Raspberry Pi")
        self.geometry("980x720")
        self.minsize(860, 640)
        self.configure(fg_color=C_BG)

        self.cfg  = ConfigManager()
        self.tmpl = TemplateManager()
        self._test_mode = False
        self.ssh  = SSHManager(self.cfg)

        self._build_ui()
        self._refresh_status_loop()

    # ── ОБЩИЙ МАКЕТ ───────────────────────────────────────────────────
    def _build_ui(self):
        # Шапка
        hdr = ctk.CTkFrame(self, fg_color=C_HDR, corner_radius=0, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        label(hdr, "🔔  Управление звонками", size=20, bold=True, color=C_ACCENT).pack(side="left", padx=24, pady=16)
        label(hdr, "Raspberry Pi — автоматические звонки на пары", size=13, color=C_MUTED).pack(side="left", padx=4)

        # Метка тест-режима в шапке (скрыта по умолчанию)
        self.test_badge = ctk.CTkLabel(hdr, text="  🧪 ТЕСТ-РЕЖИМ  ",
                                       fg_color=C_YELLOW, text_color="#1a1916",
                                       font=ctk.CTkFont("Segoe UI", 12, "bold"),
                                       corner_radius=6)
        # Не пакуем пока — покажем при включении теста

        # Статус подключения в шапке
        self.conn_dot = ctk.CTkLabel(hdr, text="●", text_color=C_RED,
                                     font=ctk.CTkFont("Segoe UI", 18))
        self.conn_dot.pack(side="right", padx=(4,4))
        self.conn_lbl = ctk.CTkLabel(hdr, text="Нет подключения",
                                     text_color=C_MUTED,
                                     font=ctk.CTkFont("Segoe UI", 13))
        self.conn_lbl.pack(side="right", padx=(12,0))

        # ── Кастомная панель вкладок ──────────────────────────────────
        tab_bar = ctk.CTkFrame(self, fg_color=C_HDR, corner_radius=0, height=52)
        tab_bar.pack(fill="x")
        tab_bar.pack_propagate(False)

        self._tab_names = ["🔌  Подключение", "📋  Расписание", "🎵  Мелодии", "🎛  Управление"]
        self._tab_frames:   dict[str, ctk.CTkFrame] = {}
        self._tab_btns:     dict[str, ctk.CTkButton] = {}
        self._tab_built:    dict[str, bool] = {}   # построена ли вкладка уже
        self._tab_builders  = {                     # функции постройки
            "🔌  Подключение": self._build_tab_conn,
            "📋  Расписание":  self._build_tab_schedule,
            "🎵  Мелодии":     self._build_tab_melodies,
            "🎛  Управление":  self._build_tab_control,
        }
        self._active_tab = tk.StringVar(value=self._tab_names[0])

        # Контейнер для содержимого вкладок
        self._tab_container = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=0)
        self._tab_container.pack(fill="both", expand=True)
        self._tab_container.grid_rowconfigure(0, weight=1)
        self._tab_container.grid_columnconfigure(0, weight=1)

        for name in self._tab_names:
            b = ctk.CTkButton(
                tab_bar, text=name,
                command=lambda n=name: self._switch_tab(n),
                fg_color="transparent",
                hover_color=C_CARD,
                text_color=C_MUTED,
                font=ctk.CTkFont("Segoe UI", 14, "bold"),
                corner_radius=0,
                width=180, height=52,
                border_spacing=0,
            )
            b.pack(side="left")
            self._tab_btns[name] = b

            f = ctk.CTkFrame(self._tab_container, fg_color=C_BG, corner_radius=0)
            f.grid(row=0, column=0, sticky="nsew")
            self._tab_frames[name] = f
            self._tab_built[name] = False

        # Строим ТОЛЬКО первую вкладку сразу, остальные — при первом открытии
        self._switch_tab(self._tab_names[0])

    def _switch_tab(self, name: str):
        # Подсветка кнопок
        for n, b in self._tab_btns.items():
            b.configure(fg_color="transparent", text_color=C_MUTED)
        self._tab_btns[name].configure(fg_color=C_CARD, text_color=C_TEXT)
        self._active_tab.set(name)

        # Если вкладка ещё не построена — строим прямо сейчас
        if not self._tab_built[name]:
            self._tab_built[name] = True
            # Заморозить отрисовку на время постройки
            self._tab_frames[name].update_idletasks()
            self._tab_builders[name](self._tab_frames[name])

        # Поднять фрейм — мгновенно, без перерисовки
        self._tab_frames[name].lift()

    # ── ВКЛАДКА: ПОДКЛЮЧЕНИЕ ─────────────────────────────────────────
    def _build_tab_conn(self, tab):
        outer = ctk.CTkFrame(tab, fg_color="transparent")
        outer.pack(expand=True)

        c = card(outer, width=480)
        c.pack(pady=40, padx=40, ipady=20)

        label(c, "SSH Подключение к Raspberry Pi", size=16, bold=True).pack(pady=(20,24))

        fields = [
            ("IP-адрес Pi:", "host", "192.168.1.105", False, 280),
            ("Порт:",        "port", "22",             False, 80),
            ("Пользователь:","username","pi",          False, 180),
            ("Пароль:",      "password","",            True,  180),
        ]
        self._conn_vars = {}
        for lbl, key, ph, is_pass, w in fields:
            row = ctk.CTkFrame(c, fg_color="transparent")
            row.pack(fill="x", padx=30, pady=6)
            label(row, lbl, width=140, anchor="w").pack(side="left")
            v = tk.StringVar(value=str(self.cfg[key]))
            self._conn_vars[key] = v
            entry(row, textvariable=v, placeholder=ph,
                  show="●" if is_pass else "", width=w).pack(side="left")

        # Remote path
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=30, pady=6)
        label(row, "Путь на Pi:", width=140, anchor="w").pack(side="left")
        v = tk.StringVar(value=str(self.cfg["remote_base"]))
        self._conn_vars["remote_base"] = v
        entry(row, textvariable=v, width=280).pack(side="left")

        btns = ctk.CTkFrame(c, fg_color="transparent")
        btns.pack(pady=24)
        btn(btns, "💾  Сохранить", self._save_conn,    color=C_CARD2,  width=150).pack(side="left", padx=8)
        btn(btns, "🔗  Подключить", self._connect,     color=C_ACCENT,  width=160).pack(side="left", padx=8)
        btn(btns, "✕  Отключить",  self._disconnect,   color=C_RED,     width=140).pack(side="left", padx=8)

        self.conn_status_lbl = label(c, "", color=C_MUTED, size=12)
        self.conn_status_lbl.pack(pady=(0,8))

        # Разделитель
        sep = ctk.CTkFrame(c, fg_color=C_BORDER, height=1)
        sep.pack(fill="x", padx=30, pady=(4,16))

        # Тест-режим
        test_row = ctk.CTkFrame(c, fg_color="transparent")
        test_row.pack(pady=(0,20))
        label(test_row, "Нет Raspberry Pi под рукой?", color=C_MUTED, size=12).pack(pady=(0,8))
        self.test_btn = ctk.CTkButton(
            test_row,
            text="🧪  Включить тест-режим",
            command=self._toggle_test_mode,
            fg_color=C_CARD2, hover_color=C_SEL,
            border_width=1, border_color=C_YELLOW,
            text_color=C_YELLOW,
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            corner_radius=8, width=240, height=38,
        )
        self.test_btn.pack()

    def _save_conn(self):
        for k, v in self._conn_vars.items():
            self.cfg[k] = v.get()
        self.cfg.save()
        self._set_conn_status("💾 Настройки сохранены", C_GREEN)

    def _connect(self):
        self._save_conn()
        self._set_conn_status("⏳ Подключение...", C_YELLOW)
        threading.Thread(target=self._do_connect, daemon=True).start()

    def _set_conn_status(self, msg, color):
        self.conn_status_lbl.configure(text=msg, text_color=color)

    def _do_connect(self):
        try:
            self.ssh.disconnect()
            self.ssh.connect()
            self.ssh.ensure_remote_dirs()
            self.after(0, lambda: self._set_conn_status("✅ Подключено!", C_GREEN))
            self.after(0, lambda: self._update_conn_indicator(True))
        except Exception as e:
            self.after(0, lambda: self._set_conn_status(f"❌ {e}", C_RED))
            self.after(0, lambda: self._update_conn_indicator(False))

    def _disconnect(self):
        self.ssh.disconnect()
        self._update_conn_indicator(False)
        self._set_conn_status("Отключено", C_MUTED)

    def _toggle_test_mode(self):
        if self._test_mode:
            self._exit_test_mode()
        else:
            self._enter_test_mode()

    def _enter_test_mode(self):
        self._test_mode = True
        self.ssh = MockSSHManager(self.cfg)
        self.ssh.connect()
        self._update_conn_indicator(True, test=True)
        self._set_conn_status("🧪 Тест-режим активен — файлы пишутся в папку test_pi/", C_YELLOW)
        self.test_btn.configure(
            text="✕  Выключить тест-режим",
            fg_color=C_SEL, border_color=C_RED, text_color=C_RED,
        )
        self.test_badge.pack(side="right", padx=12, pady=16)
        self._toast("🧪 Тест-режим включён! Pi не нужен.")

    def _exit_test_mode(self):
        self._test_mode = False
        self.ssh.disconnect()
        self.ssh = SSHManager(self.cfg)
        self._update_conn_indicator(False)
        self._set_conn_status("Тест-режим выключен", C_MUTED)
        self.test_btn.configure(
            text="🧪  Включить тест-режим",
            fg_color=C_CARD2, border_color=C_YELLOW, text_color=C_YELLOW,
        )
        self.test_badge.pack_forget()

    def _update_conn_indicator(self, connected, test=False):
        if connected and test:
            self.conn_dot.configure(text_color=C_YELLOW)
            self.conn_lbl.configure(text="  Тест-режим", text_color=C_YELLOW)
        elif connected:
            self.conn_dot.configure(text_color=C_GREEN)
            self.conn_lbl.configure(text=f"  {self.cfg['host']}", text_color=C_GREEN)
        else:
            self.conn_dot.configure(text_color=C_RED)
            self.conn_lbl.configure(text="  Нет подключения", text_color=C_MUTED)

    # ── ВКЛАДКА: РАСПИСАНИЕ ──────────────────────────────────────────
    def _build_tab_schedule(self, tab):
        left = ctk.CTkFrame(tab, fg_color=C_PANEL, corner_radius=12, width=260)
        left.pack(side="left", fill="y", padx=(16,8), pady=16)
        left.pack_propagate(False)

        right = ctk.CTkFrame(tab, fg_color=C_PANEL, corner_radius=12)
        right.pack(side="left", fill="both", expand=True, padx=(0,16), pady=16)

        # ── Левая панель: список шаблонов ──
        label(left, "Шаблоны", size=15, bold=True).pack(pady=(16,12), padx=16)

        self.tmpl_listbox = ctk.CTkScrollableFrame(left, fg_color=C_BG, corner_radius=8)
        self.tmpl_listbox.pack(fill="both", expand=True, padx=12, pady=(0,8))
        self._selected_tmpl_id = tk.IntVar(value=-1)

        self._render_template_list()

        # Кнопки внизу
        ctrl = ctk.CTkFrame(left, fg_color="transparent")
        ctrl.pack(padx=10, pady=(4,4), anchor="w")
        btn(ctrl, "＋  Новый",    self._new_template,  color=C_GREEN,  width=108, height=36).pack(side="left", padx=(0,4))
        btn(ctrl, "✏  Изменить", self._edit_template,  color=C_ACCENT, width=108, height=36).pack(side="left")

        del_row = ctk.CTkFrame(left, fg_color="transparent")
        del_row.pack(padx=10, pady=(4,12), anchor="w")
        btn(del_row, "🗑  Удалить шаблон", self._del_template, color=C_RED, width=224, height=36).pack()

        # ── Правая панель: предпросмотр + применить ──
        label(right, "Предпросмотр шаблона", size=15, bold=True).pack(pady=(16,8), padx=20, anchor="w")

        self.preview_frame = ctk.CTkScrollableFrame(right, fg_color=C_BG, corner_radius=8)
        self.preview_frame.pack(fill="both", expand=True, padx=16, pady=(0,8))

        apply_area = ctk.CTkFrame(right, fg_color=C_CARD2, corner_radius=10)
        apply_area.pack(fill="x", padx=16, pady=(0,16))

        self.active_tmpl_lbl = label(apply_area, "Активный шаблон: —", color=C_MUTED, size=13)
        self.active_tmpl_lbl.pack(side="left", padx=16, pady=14)

        btn(apply_area, "🚀  ПРИМЕНИТЬ НА Pi",
            self._apply_template, color=C_ACCENT, width=220,
            height=44).pack(side="right", padx=16, pady=10)

        self._render_preview()

    def _render_template_list(self):
        for w in self.tmpl_listbox.winfo_children():
            w.destroy()
        for t in self.tmpl.templates:
            tid = t["id"]
            is_sel = self._selected_tmpl_id.get() == tid

            row = ctk.CTkFrame(self.tmpl_listbox,
                               fg_color=C_SEL if is_sel else C_CARD,
                               corner_radius=6, cursor="hand2",
                               border_width=2 if is_sel else 0,
                               border_color=C_ACCENT)
            row.pack(fill="x", pady=3, padx=2)
            row.pack_propagate(False)
            row.configure(height=44)

            n_bells = len(t["bells"])
            label(row, t["name"], bold=True,
                  color=C_ACCENT if is_sel else C_TEXT).pack(
                side="left", padx=14, pady=0, anchor="center")
            label(row, f"{n_bells} зв.", color=C_MUTED, size=11).pack(
                side="right", padx=10, anchor="center")

            bind_recursive(row, "<Button-1>", lambda e, i=tid: self._select_template(i))

    def _select_template(self, tid):
        self._selected_tmpl_id.set(tid)
        self._render_template_list()
        self._render_preview()

    def _render_preview(self):
        for w in self.preview_frame.winfo_children():
            w.destroy()

        tid = self._selected_tmpl_id.get()
        t = self.tmpl.get_by_id(tid) if tid != -1 else None
        if not t:
            label(self.preview_frame, "← Выбери шаблон из списка", color=C_MUTED).pack(pady=30)
            return

        for b in t["bells"]:
            row = ctk.CTkFrame(self.preview_frame, fg_color=C_CARD, corner_radius=6)
            row.pack(fill="x", pady=2, padx=4)
            icon  = "▶" if b["type"]=="start" else "⏹"
            color = C_GREEN if b["type"]=="start" else C_YELLOW
            days  = " ".join(DAYS_RU[d] for d in b["days"])
            label(row, f"{icon} {b['time']}", bold=True, color=color, width=80).pack(side="left", padx=(10,4), pady=6)
            label(row, b["description"], width=260, anchor="w", color=C_TEXT if b["enabled"] else C_MUTED).pack(side="left")
            label(row, days, color=C_MUTED, size=11).pack(side="right", padx=10)

    def _new_template(self):
        dlg = TemplateDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            new_id = self.tmpl.add(dlg.result["name"], dlg.result["bells"])
            self._selected_tmpl_id.set(new_id)
            self._render_template_list()
            self._render_preview()

    def _edit_template(self):
        tid = self._selected_tmpl_id.get()
        t = self.tmpl.get_by_id(tid)
        if not t:
            mb.showwarning("Нет выбора", "Сначала выбери шаблон из списка")
            return
        dlg = TemplateDialog(self, template=t)
        self.wait_window(dlg)
        if dlg.result:
            self.tmpl.update(tid, dlg.result["name"], dlg.result["bells"])
            self._render_template_list()
            self._render_preview()

    def _del_template(self):
        tid = self._selected_tmpl_id.get()
        t = self.tmpl.get_by_id(tid)
        if not t:
            mb.showwarning("Нет выбора", "Сначала выбери шаблон")
            return
        if mb.askyesno("Удалить?", f"Удалить шаблон «{t['name']}»?"):
            self.tmpl.delete(tid)
            self._selected_tmpl_id.set(-1)
            self._render_template_list()
            self._render_preview()

    def _apply_template(self):
        tid = self._selected_tmpl_id.get()
        t = self.tmpl.get_by_id(tid)
        if not t:
            mb.showwarning("Нет выбора", "Сначала выбери шаблон")
            return
        if not self._check_connected():
            return
        threading.Thread(target=self._do_apply_template, args=(t,), daemon=True).start()

    def _do_apply_template(self, t):
        try:
            sched = self.tmpl.to_schedule_json(
                t, self.cfg["melody_start"], self.cfg["melody_end"]
            )
            content = json.dumps(sched, ensure_ascii=False, indent=2)
            remote  = f"{self.cfg['remote_base']}/schedule.json"
            self.ssh.send_text(content, remote)
            self.ssh.send_command("reload")
            self.after(0, lambda: [
                self.active_tmpl_lbl.configure(
                    text=f"Активный шаблон: {t['name']}", text_color=C_GREEN),
                self._toast(f"✅ Шаблон «{t['name']}» применён на Pi!")
            ])
        except Exception as e:
            self.after(0, lambda: mb.showerror("Ошибка", str(e)))

    # ── ВКЛАДКА: МЕЛОДИИ ─────────────────────────────────────────────
    def _build_tab_melodies(self, tab):
        outer = ctk.CTkFrame(tab, fg_color="transparent")
        outer.pack(expand=True, pady=20)

        label(outer, "🎵  Мелодии звонков", size=16, bold=True).pack(pady=(0,20))

        for mtype, label_text, cfg_key, local_key in [
            ("start", "▶  Мелодия начала пары",  "melody_start", "local_melody_start"),
            ("end",   "⏹  Мелодия конца пары",   "melody_end",   "local_melody_end"),
        ]:
            c = card(outer, width=600)
            c.pack(pady=10, padx=20, ipady=8)

            label(c, label_text, size=14, bold=True,
                  color=C_GREEN if mtype=="start" else C_YELLOW).pack(pady=(14,10), padx=20, anchor="w")

            # Имя файла на Pi
            row1 = ctk.CTkFrame(c, fg_color="transparent")
            row1.pack(fill="x", padx=20, pady=4)
            label(row1, "Имя на Pi:", width=130, anchor="w").pack(side="left")
            var = tk.StringVar(value=self.cfg[cfg_key])
            setattr(self, f"_var_{cfg_key}", var)
            entry(row1, textvariable=var, width=250).pack(side="left", padx=4)
            label(row1, "(например: bell_start.mp3)", color=C_MUTED, size=11).pack(side="left", padx=6)

            # Локальный файл
            row2 = ctk.CTkFrame(c, fg_color="transparent")
            row2.pack(fill="x", padx=20, pady=4)
            label(row2, "Локальный файл:", width=130, anchor="w").pack(side="left")
            lvar = tk.StringVar(value=self.cfg[local_key])
            setattr(self, f"_var_{local_key}", lvar)
            path_lbl = ctk.CTkLabel(row2, textvariable=lvar,
                                    text_color=C_MUTED, font=ctk.CTkFont("Segoe UI", 12),
                                    width=260, anchor="w")
            path_lbl.pack(side="left", padx=4)

            brow_lbl = path_lbl
            def _browse(lv=lvar):
                p = fd.askopenfilename(filetypes=[("Аудио","*.mp3 *.wav *.ogg"), ("Все","*.*")])
                if p: lv.set(p)

            btn_row = ctk.CTkFrame(c, fg_color="transparent")
            btn_row.pack(fill="x", padx=20, pady=(4,12))
            btn(btn_row, "📂  Выбрать файл",
                _browse,                                   color="#555555", width=170).pack(side="left", padx=4)
            btn(btn_row, "▶  Прослушать",
                lambda lv=lvar: self._preview_audio(lv.get()),
                color=C_ACCENT2, width=150).pack(side="left", padx=4)
            btn(btn_row, "📤  Загрузить на Pi",
                lambda lv=lvar, cv=var, lk=local_key, ck=cfg_key: self._upload_melody(lv, cv, lk, ck),
                color=C_ACCENT, width=170).pack(side="left", padx=4)

        btn(outer, "💾  Сохранить имена файлов", self._save_melody_names,
            color=C_GREEN, width=260).pack(pady=16)

    def _preview_audio(self, path):
        if not path:
            mb.showinfo("Нет файла", "Сначала выбери файл")
            return
        if not HAS_PYGAME:
            mb.showwarning("pygame не найден", "pip install pygame")
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
        except Exception as e:
            mb.showerror("Ошибка", str(e))

    def _upload_melody(self, local_var, name_var, local_key, cfg_key):
        local  = local_var.get()
        remote_name = name_var.get().strip()
        if not local or not os.path.exists(local):
            mb.showerror("Ошибка", "Выбери локальный файл")
            return
        if not remote_name:
            mb.showerror("Ошибка", "Укажи имя файла на Pi")
            return
        if not self._check_connected():
            return
        self.cfg[local_key] = local
        self.cfg[cfg_key]   = remote_name
        self.cfg.save()
        threading.Thread(target=self._do_upload_melody,
                         args=(local, remote_name), daemon=True).start()

    def _do_upload_melody(self, local, name):
        try:
            remote = f"{self.cfg['remote_base']}/sounds/{name}"
            self.ssh.send_file(local, remote)
            self.after(0, lambda: self._toast(f"✅ Файл «{name}» загружен на Pi!"))
        except Exception as e:
            self.after(0, lambda: mb.showerror("Ошибка загрузки", str(e)))

    def _save_melody_names(self):
        for key in ("melody_start","melody_end","local_melody_start","local_melody_end"):
            v = getattr(self, f"_var_{key}", None)
            if v: self.cfg[key] = v.get()
        self.cfg.save()
        self._toast("💾 Названия мелодий сохранены")

    # ── ВКЛАДКА: УПРАВЛЕНИЕ ──────────────────────────────────────────
    def _build_tab_control(self, tab):

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=16)

        # Статус карточка
        status_card = card(top)
        status_card.pack(side="left", fill="both", expand=True, padx=(0,8))
        label(status_card, "Статус системы", size=14, bold=True).pack(pady=(16,12), padx=16, anchor="w")

        self.status_rows = {}
        for key, lbl_text in [
            ("running", "Сервис:"),
            ("paused",  "Режим:"),
            ("last_ring_time", "Последний звонок:"),
            ("last_ring_desc", "Описание:"),
        ]:
            row = ctk.CTkFrame(status_card, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=3)
            label(row, lbl_text, width=160, anchor="w", color=C_MUTED).pack(side="left")
            v = ctk.CTkLabel(row, text="—", text_color=C_TEXT,
                             font=ctk.CTkFont("Segoe UI", 13, "bold"))
            v.pack(side="left")
            self.status_rows[key] = v

        btn(status_card, "🔄  Обновить статус", self._refresh_status,
            color="#444444", width=200).pack(pady=14, padx=16, anchor="w")

        # Кнопки управления
        ctrl_card = card(top, width=260)
        ctrl_card.pack(side="left", fill="y", padx=(8,0))
        ctrl_card.pack_propagate(False)

        label(ctrl_card, "Управление", size=14, bold=True).pack(pady=(16,14))

        controls = [
            ("⏸  ПАУЗА",             lambda: self._send_cmd("pause"),      C_YELLOW),
            ("▶  СНЯТЬ ПАУЗУ",        lambda: self._send_cmd("resume"),     C_GREEN),
            ("⏹  СТОП ЗВОНКА",       lambda: self._send_cmd("stop_sound"), C_RED),
            ("🔄  ПЕРЕЗАГР. РАСП.",   lambda: self._send_cmd("reload"),     C_ACCENT),
            ("🔁  РЕСТАРТ СЕРВИСА",  self._restart_service,                C_CARD2),
        ]
        for text, cmd, color in controls:
            btn(ctrl_card, text, cmd, color=color, width=220, height=40).pack(pady=4)

        # Лог
        log_card = card(tab)
        log_card.pack(fill="both", expand=True, padx=16, pady=(0,16))

        hdr = ctk.CTkFrame(log_card, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(12,6))
        label(hdr, "📋  Лог звонков (последние 30 строк)", size=13, bold=True).pack(side="left")
        btn(hdr, "🔄", self._refresh_log, color="#444444", width=40, height=30).pack(side="right")

        self.log_text = ctk.CTkTextbox(
            log_card, fg_color=C_BG, text_color="#c8b89a",
            font=ctk.CTkFont("Consolas", 12), corner_radius=8
        )
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0,12))
        self.log_text.configure(state="disabled")

    def _check_connected(self) -> bool:
        """Проверяет реальное состояние соединения, сбрасывает если мёртвое."""
        if not self.ssh.connected:
            mb.showerror("Нет подключения",
                         "Сначала подключись к Pi на вкладке «Подключение»")
            return False
        # Для реального SSH — проверяем что соединение живое
        if isinstance(self.ssh, SSHManager):
            try:
                self.ssh._client.get_transport().send_ignore()
            except Exception:
                self.ssh.connected = False
                self._update_conn_indicator(False)
                mb.showerror("Соединение потеряно",
                             "Подключение к Pi прервалось.\n"
                             "Нажми «Подключить» снова на вкладке «Подключение».")
                return False
        return True

    def _send_cmd(self, cmd):
        if not self._check_connected():
            return
        threading.Thread(target=self._do_send_cmd, args=(cmd,), daemon=True).start()

    def _do_send_cmd(self, cmd):
        try:
            self.ssh.send_command(cmd)
            self.after(0, lambda: self._toast(f"✅ Команда «{cmd}» отправлена"))
            time.sleep(1.5)
            self.after(0, self._refresh_status)
        except Exception as e:
            self.after(0, lambda: mb.showerror("Ошибка", str(e)))

    def _restart_service(self):
        if not self._check_connected():
            return
        if self._test_mode:
            self.ssh._status["running"] = True
            self.ssh._log("🔁 [ТЕСТ] Сервис перезапущен (эмуляция)")
            self.ssh._save_status()
            self._toast("🔁 [ТЕСТ] Сервис перезапущен")
            return
        if mb.askyesno("Рестарт?", "Перезапустить сервис Bell Scheduler на Pi?"):
            threading.Thread(target=lambda: [
                self.ssh.exec("sudo systemctl restart bell_scheduler"),
                self.after(0, lambda: self._toast("🔁 Сервис перезапущен"))
            ], daemon=True).start()

    def _refresh_status(self):
        if not self.ssh.connected:
            return
        threading.Thread(target=self._do_refresh_status, daemon=True).start()

    def _do_refresh_status(self):
        try:
            s = self.ssh.get_status()
            def upd():
                if s.get("running"):
                    self.status_rows["running"].configure(text="✅ Работает", text_color=C_GREEN)
                else:
                    self.status_rows["running"].configure(text="🔴 Остановлен", text_color=C_RED)

                if s.get("paused"):
                    self.status_rows["paused"].configure(text="⏸ На паузе", text_color=C_YELLOW)
                else:
                    self.status_rows["paused"].configure(text="▶ Активен", text_color=C_GREEN)

                lr = s.get("last_ring")
                if lr:
                    self.status_rows["last_ring_time"].configure(
                        text=f"{lr.get('day','').upper()}  {lr.get('time','—')}",
                        text_color=C_TEXT)
                    self.status_rows["last_ring_desc"].configure(
                        text=lr.get("description","—"), text_color=C_TEXT)
            self.after(0, upd)
        except Exception:
            pass

    def _refresh_log(self):
        if not self.ssh.connected:
            return
        threading.Thread(target=self._do_refresh_log, daemon=True).start()

    def _do_refresh_log(self):
        try:
            txt = self.ssh.get_log_tail(30)
            def upd():
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", "end")
                self.log_text.insert("end", txt or "(лог пуст)")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            self.after(0, upd)
        except Exception:
            pass

    def _refresh_status_loop(self):
        """Автообновление статуса каждые 15 секунд."""
        self._refresh_status()
        self._refresh_log()
        self.after(15000, self._refresh_status_loop)

    # ── ТОСТ-УВЕДОМЛЕНИЕ ─────────────────────────────────────────────
    def _toast(self, msg):
        t = ctk.CTkToplevel(self)
        t.overrideredirect(True)
        t.configure(fg_color=C_CARD2)
        t.attributes("-topmost", True)
        ctk.CTkLabel(t, text=msg, font=ctk.CTkFont("Segoe UI", 13),
                     text_color=C_TEXT, padx=20, pady=12).pack()
        # Позиция: правый нижний угол
        self.update_idletasks()
        x = self.winfo_x() + self.winfo_width()  - 400
        y = self.winfo_y() + self.winfo_height() - 80
        t.geometry(f"+{x}+{y}")
        t.after(2500, t.destroy)


# ═══════════════════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not HAS_PARAMIKO:
        print("⚠  Установи зависимости: pip install customtkinter paramiko pygame")
    app = App()
    app.mainloop()
