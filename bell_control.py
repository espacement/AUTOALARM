#!/usr/bin/env python3
"""
bell_control.py — Утилита управления Bell Scheduler из командной строки.

Использование:
  python3 bell_control.py pause        — поставить на паузу
  python3 bell_control.py resume       — снять с паузы
  python3 bell_control.py stop_sound   — прервать текущий звонок
  python3 bell_control.py stop         — полностью остановить сервис
  python3 bell_control.py reload       — перезагрузить расписание
  python3 bell_control.py status       — показать текущий статус
"""

import sys
import json
from pathlib import Path
from datetime import datetime

BASE_DIR     = Path("/home/pi/bell_scheduler")
CONTROL_FILE = BASE_DIR / "control.cmd"
STATUS_FILE  = BASE_DIR / "status.json"

VALID_COMMANDS = {"pause", "resume", "stop_sound", "stop", "reload"}

HELP = """
╔══════════════════════════════════════════════╗
║         🔔 Bell Scheduler — Control          ║
╠══════════════════════════════════════════════╣
║  pause      — приостановить звонки           ║
║  resume     — возобновить звонки             ║
║  stop_sound — прервать текущий звонок        ║
║  stop       — остановить сервис              ║
║  reload     — перезагрузить расписание       ║
║  status     — показать текущий статус        ║
╚══════════════════════════════════════════════╝
"""


def send_command(cmd: str):
    """Записывает команду в control.cmd."""
    try:
        CONTROL_FILE.write_text(cmd, encoding="utf-8")
        print(f"✅ Команда '{cmd}' отправлена.")
    except Exception as e:
        print(f"❌ Не удалось отправить команду: {e}")
        sys.exit(1)


def show_status():
    """Читает и выводит status.json."""
    if not STATUS_FILE.exists():
        print("⚠  Файл статуса не найден. Сервис не запущен или ещё не записал статус.")
        return

    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            s = json.load(f)

        paused  = s.get("paused", False)
        running = s.get("running", False)
        updated = s.get("updated_at", "—")
        last    = s.get("last_ring")

        print("\n📊 Статус Bell Scheduler")
        print("─" * 36)
        print(f"  Сервис   : {'✅ Работает' if running else '🔴 Остановлен'}")
        print(f"  Режим    : {'⏸  На паузе' if paused else '▶  Активен'}")
        print(f"  Обновлён : {updated}")

        if last:
            print(f"\n  Последний звонок:")
            print(f"    #{last.get('id')} | {last.get('description')}")
            print(f"    {last.get('day', '').upper()} {last.get('time')} "
                  f"| файл: {last.get('sound')}")
            print(f"    {last.get('timestamp')}")
        else:
            print("\n  Последний звонок: —")

        print()

    except Exception as e:
        print(f"❌ Ошибка чтения статуса: {e}")


def main():
    if len(sys.argv) < 2:
        print(HELP)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        show_status()
    elif cmd in VALID_COMMANDS:
        send_command(cmd)
    else:
        print(f"❌ Неизвестная команда: '{cmd}'")
        print(HELP)
        sys.exit(1)


if __name__ == "__main__":
    main()
