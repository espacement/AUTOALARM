#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════╗
║          🔔 Bell Scheduler — Raspberry Pi 4          ║
║   Автоматические звонки на пары и с пар              ║
╠══════════════════════════════════════════════════════╣
║  Запуск в боевом режиме:                             ║
║    python3 bell_scheduler.py                         ║
║                                                      ║
║  Тестовый режим (на ПК, без Pi):                     ║
║    python3 bell_scheduler.py --test                  ║
║    python3 bell_scheduler.py --test --speed 60       ║
║       --speed N : 1 реальная секунда = N виртуальных ║
╚══════════════════════════════════════════════════════╝
"""

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pygame")

import json
import time
import logging
import signal
import sys
import subprocess
import threading
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# ─────────────────────────────────────────
#  ПАРСИНГ АРГУМЕНТОВ
# ─────────────────────────────────────────
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--test",  action="store_true", help="Тестовый режим")
parser.add_argument("--speed", type=int, default=60,
                    help="Ускорение виртуального времени (по умолчанию 60)")
parser.add_argument("--help",  action="store_true")
args, _ = parser.parse_known_args()

if args.help:
    print(__doc__)
    sys.exit(0)

TEST_MODE  = args.test
TIME_SPEED = args.speed   # 1 реальная секунда = N виртуальных секунд

# ─────────────────────────────────────────
#  ПУТИ — боевые или тестовые
# ─────────────────────────────────────────
_script_dir = Path(__file__).parent

if TEST_MODE:
    # Всё рядом со скриптом, в папке test_run/
    BASE_DIR = _script_dir / "test_run"
else:
    BASE_DIR = Path("/home/pi/bell_scheduler")

SCHEDULE_FILE = _script_dir / "schedule.json"    # общий для обоих режимов
SOUNDS_DIR    = _script_dir / "sounds"           # общий для обоих режимов
LOG_FILE      = BASE_DIR / "logs" / "bells.log"
CONTROL_FILE  = BASE_DIR / "control.cmd"
STATUS_FILE   = BASE_DIR / "status.json"

CHECK_INTERVAL  = 1      if TEST_MODE else 20    # секунд опроса
RELOAD_INTERVAL = 3600                            # секунд авто-reload

# ─────────────────────────────────────────
#  ВИРТУАЛЬНОЕ ВРЕМЯ (только --test)
# ─────────────────────────────────────────
_test_start_real = time.time()
_test_start_virt = datetime.now().replace(second=0, microsecond=0)

def virtual_now() -> datetime:
    """Возвращает ускоренное время в тесте, реальное — в боевом."""
    if not TEST_MODE:
        return datetime.now()
    elapsed_real = time.time() - _test_start_real
    return _test_start_virt + timedelta(seconds=elapsed_real * TIME_SPEED)

# ─────────────────────────────────────────
#  ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# ─────────────────────────────────────────
state = {
    "paused":          False,
    "running":         True,
    "current_process": None,
    "last_ring":       None,
}


# ══════════════════════════════════════════
#  ЛОГИРОВАНИЕ
# ══════════════════════════════════════════

def setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ══════════════════════════════════════════
#  РАСПИСАНИЕ
# ══════════════════════════════════════════

def load_schedule() -> list:
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        tasks = data.get("schedule", [])
        logging.info(f"📅 Расписание загружено: {len(tasks)} записей")
        return tasks
    except FileNotFoundError:
        logging.error(f"❌ Файл расписания не найден: {SCHEDULE_FILE}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"❌ Ошибка JSON: {e}")
        return []


def get_day_key(now: datetime = None) -> str:
    d = now or virtual_now()
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][d.weekday()]


def should_ring(task: dict, current_time: str, current_day: str) -> bool:
    if not task.get("enabled", True):
        return False
    if task.get("time") != current_time:
        return False
    return current_day in task.get("days", ["mon", "tue", "wed", "thu", "fri"])


# ══════════════════════════════════════════
#  ВОСПРОИЗВЕДЕНИЕ ЗВУКА
# ══════════════════════════════════════════

def _beep_pygame(label: str = ""):
    """
    Генерирует тоновый сигнал через pygame + numpy.
    Используется в тесте когда нет реального файла.
    """
    try:
        import numpy as np
        import pygame
        # Если уже инициализирован — закрываем и открываем заново с нужными параметрами
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        rate = 44100
        dur  = 1.5
        freq = 880.0
        t    = np.linspace(0, dur, int(rate * dur), endpoint=False)
        mono = (np.sin(2 * np.pi * freq * t) * 32767 * 0.6).astype(np.int16)
        # Стерео: дублируем канал (форма: [samples, 2])
        stereo = np.column_stack((mono, mono))
        pygame.sndarray.make_sound(stereo).play()
        logging.info(f"🔔 [ТЕСТ] Тон 880 Гц, 1.5 сек  ({label})")
        pygame.time.wait(int(dur * 1000))
    except ImportError:
        logging.info(f"   🔔🔔🔔  {label or 'ЗВОНОК'}  🔔🔔🔔")
        time.sleep(0.8)
    except Exception as e:
        logging.warning(f"⚠  Тон не воспроизведён: {e}")
        logging.info(f"   🔔🔔🔔  {label or 'ЗВОНОК'}  🔔🔔🔔")


def play_sound(sound_file: str, duration: int = 0) -> bool:
    """
    Воспроизводит звуковой файл.
    duration — максимальная длина в секундах (0 = полный файл).
    """
    sound_path = SOUNDS_DIR / sound_file

    # ── Файл не найден ─────────────────────────────
    if not sound_path.exists():
        if TEST_MODE:
            logging.warning(f"⚠  [ТЕСТ] Файл '{sound_file}' не найден — играю тон")
            _beep_pygame(sound_file)
            return True
        logging.error(f"❌ Файл не найден: {sound_path}")
        return False

    dur_str = f" (макс. {duration}с)" if duration else ""
    logging.info(f"▶  Воспроизведение: {sound_file}{dur_str}")

    # ── Тестовый режим → только pygame ─────────────
    if TEST_MODE:
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(str(sound_path))
            pygame.mixer.music.play()
            elapsed = 0.0
            while pygame.mixer.music.get_busy():
                if not state["running"]:
                    pygame.mixer.music.stop()
                    break
                if duration and elapsed >= duration:
                    pygame.mixer.music.stop()
                    logging.info(f"⏱  Остановлен по таймеру ({duration}с)")
                    break
                time.sleep(0.1)
                elapsed += 0.1
            return True
        except ImportError:
            logging.warning("⚠  pygame не установлен — симулирую")
            time.sleep(min(duration, 2) if duration else 1)
            return True
        except Exception as e:
            logging.error(f"❌ pygame: {e}")
            return False

    # ── Боевой режим → mpg123 / aplay ─────────────
    ext = sound_path.suffix.lower()
    if ext == ".mp3":
        cmd = ["mpg123", "-q", str(sound_path)]
    elif ext == ".wav":
        cmd = ["aplay", str(sound_path)]
    elif ext == ".ogg":
        cmd = ["ogg123", "-q", str(sound_path)]
    else:
        cmd = ["mpg123", "-q", str(sound_path)]

    try:
        proc = subprocess.Popen(cmd)
        state["current_process"] = proc

        if duration:
            # Ждём duration секунд, потом принудительно останавливаем
            deadline = time.time() + duration
            while proc.poll() is None:
                if time.time() >= deadline:
                    proc.terminate()
                    logging.info(f"⏱  Остановлен по таймеру ({duration}с)")
                    break
                time.sleep(0.1)
        else:
            proc.wait()

        state["current_process"] = None
        return True

    except FileNotFoundError:
        logging.warning("⚠  mpg123/aplay не найден, пробую pygame...")
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(str(sound_path))
            pygame.mixer.music.play()
            elapsed = 0.0
            while pygame.mixer.music.get_busy():
                if not state["running"]:
                    pygame.mixer.music.stop()
                    break
                if duration and elapsed >= duration:
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.1)
                elapsed += 0.1
            return True
        except Exception as e:
            logging.error(f"❌ pygame: {e}")
            return False
    except Exception as e:
        logging.error(f"❌ Воспроизведение: {e}")
        state["current_process"] = None
        return False


def stop_current_sound():
    proc = state.get("current_process")
    if proc and proc.poll() is None:
        proc.terminate()
        state["current_process"] = None
        logging.info("⏹  Процесс воспроизведения остановлен")
    try:
        import pygame
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
            logging.info("⏹  pygame остановлен")
    except Exception:
        pass


# ══════════════════════════════════════════
#  ЛОГИКА ЗВОНКОВ
# ══════════════════════════════════════════

def check_and_ring(schedule: list):
    now          = virtual_now()
    current_time = now.strftime("%H:%M")
    current_day  = get_day_key(now)

    for task in schedule:
        if not should_ring(task, current_time, current_day):
            continue

        desc     = task.get("description", "Звонок")
        sound    = task.get("sound", "")
        task_id  = task.get("id", "?")
        duration = int(task.get("duration", 0))

        logging.info(
            f"🔔 ЗВОНОК #{task_id} | {desc} | "
            f"{current_time} | {current_day.upper()} | {sound}"
            + (f" | {duration}с" if duration else "")
        )

        state["last_ring"] = {
            "id": task_id, "time": current_time,
            "day": current_day, "description": desc,
            "sound": sound, "timestamp": now.isoformat(),
        }
        save_status()

        if state["paused"]:
            logging.warning("⏸  На паузе — звонок пропущен")
            continue

        threading.Thread(target=play_sound, args=(sound, duration), daemon=True).start()


# ══════════════════════════════════════════
#  СТАТУС
# ══════════════════════════════════════════

def save_status():
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "paused":    state["paused"],
                "running":   state["running"],
                "last_ring": state["last_ring"],
                "test_mode": TEST_MODE,
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"⚠  Статус не сохранён: {e}")


# ══════════════════════════════════════════
#  КОМАНДЫ (control.cmd)
# ══════════════════════════════════════════

def handle_control() -> str | None:
    if not CONTROL_FILE.exists():
        return None
    try:
        cmd = CONTROL_FILE.read_text(encoding="utf-8").strip().lower()
        CONTROL_FILE.unlink()

        if cmd == "pause":
            state["paused"] = True
            logging.info("⏸  Система приостановлена")
            save_status()
        elif cmd == "resume":
            state["paused"] = False
            logging.info("▶  Система возобновлена")
            save_status()
        elif cmd == "stop_sound":
            stop_current_sound()
        elif cmd == "stop":
            stop_current_sound()
            state["running"] = False
            logging.info("⏹  Остановка по команде")
            save_status()
        elif cmd == "reload":
            logging.info("🔄 Перезагрузка расписания...")
            return "reload"
        else:
            logging.warning(f"⚠  Неизвестная команда: '{cmd}'")
    except Exception as e:
        logging.error(f"❌ handle_control: {e}")
    return None


# ══════════════════════════════════════════
#  ТЕСТ-МОНИТОР: клавиатурные команды
# ══════════════════════════════════════════

def _keyboard_thread():
    """Читает команды с клавиатуры в тестовом режиме (отдельный поток)."""
    shortcuts = {"p": "pause", "s": "stop_sound", "r": "reload", "q": "stop"}
    while state["running"]:
        try:
            key = input().strip().lower()
            if not key:
                continue
            cmd = shortcuts.get(key, key)
            BASE_DIR.mkdir(parents=True, exist_ok=True)
            CONTROL_FILE.write_text(cmd, encoding="utf-8")
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as e:
            print(f"  ❌ {e}")


def _print_test_banner(schedule: list):
    now     = virtual_now()
    enabled = [t for t in schedule if t.get("enabled", True)]
    # Следующий звонок сегодня
    cur_str = now.strftime("%H:%M")
    day_key = get_day_key(now)
    upcoming = [
        t for t in enabled
        if t.get("time", "") > cur_str and day_key in t.get("days", [])
    ]
    print()
    print("═" * 55)
    print("  🧪  ТЕСТОВЫЙ РЕЖИМ — Bell Scheduler v1.1")
    print(f"  Виртуальное время : {now.strftime('%H:%M')}  ({now.strftime('%A')})")
    print(f"  Ускорение времени : x{TIME_SPEED}  "
          f"(1 сек → {TIME_SPEED} сек виртуальных)")
    print(f"  Звонков в расписании : {len(enabled)} активных / {len(schedule)} всего")
    if upcoming:
        nx = upcoming[0]
        print(f"  Ближайший звонок  : {nx['time']} — {nx['description']}")
    print()
    print("  Клавиши управления:")
    print("    p  — пауза / снять паузу")
    print("    s  — стоп текущего звонка")
    print("    r  — перезагрузить расписание")
    print("    q  — выйти")
    print("═" * 55)
    print()


# ══════════════════════════════════════════
#  СИГНАЛЫ
# ══════════════════════════════════════════

def signal_handler(sig, frame):
    logging.info(f"🛑 Сигнал {sig}. Завершение...")
    stop_current_sound()
    state["running"] = False
    save_status()
    sys.exit(0)


# ══════════════════════════════════════════
#  ГЛАВНЫЙ ЦИКЛ
# ══════════════════════════════════════════

def run():
    setup_logging()
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT,  signal_handler)

    mode = "🧪 ТЕСТ" if TEST_MODE else "🎓 БОЕВОЙ"
    logging.info("=" * 55)
    logging.info(f"  Bell Scheduler v1.1  [{mode}]")
    logging.info(f"  Расписание : {SCHEDULE_FILE}")
    logging.info(f"  Звуки      : {SOUNDS_DIR}")
    logging.info(f"  Лог        : {LOG_FILE}")
    if TEST_MODE:
        logging.info(f"  Ускорение  : x{TIME_SPEED}")
    logging.info("=" * 55)

    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    schedule    = load_schedule()
    last_minute = None
    last_reload = datetime.now()

    save_status()

    if TEST_MODE:
        _print_test_banner(schedule)
        threading.Thread(target=_keyboard_thread, daemon=True).start()

    while state["running"]:
        now            = virtual_now()
        current_minute = now.strftime("%H:%M")

        result = handle_control()
        if result == "reload":
            schedule    = load_schedule()
            last_reload = datetime.now()

        if (datetime.now() - last_reload).total_seconds() >= RELOAD_INTERVAL:
            schedule    = load_schedule()
            last_reload = datetime.now()

        if current_minute != last_minute:
            last_minute = current_minute
            if TEST_MODE:
                logging.info(
                    f"🕐 [ТЕСТ] {current_minute} ({get_day_key(now).upper()})"
                )
            check_and_ring(schedule)

        time.sleep(CHECK_INTERVAL)

    logging.info("👋  Bell Scheduler завершил работу.")


if __name__ == "__main__":
    run()
