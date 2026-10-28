# 🔔 Bell Scheduler

> Система автоматической подачи звуковых сигналов для учебных заведений на базе Raspberry Pi 4

[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry_Pi-4_Model_B-c51a4a?style=flat-square&logo=raspberrypi&logoColor=white)](https://raspberrypi.com)
[![License](https://img.shields.io/badge/License-MIT-7a9e6e?style=flat-square)](LICENSE)

---

## Что это

Замена ручной подачи звонков на автоматическую. Raspberry Pi воспроизводит мелодии по расписанию, управление — через браузер с любого устройства в локальной сети. Никаких приложений устанавливать не нужно.

Разработано как дипломный проект для ГПОУ «Сибирский политехнический техникум».

---

## Как выглядит

| Дашборд | Расписание | Звукотека |
|---------|-----------|-----------|
| Статус, управление, лог в реальном времени | Шаблоны расписания, редактор звонков | Загрузка мелодий, обрезка прямо в браузере |

---

## Архитектура

```
Браузер (любое устройство)
        │ HTTP :5000
        ▼
┌─────────────────────────────────────────┐
│           Raspberry Pi 4                │
│                                         │
│  web_server.py      bell_scheduler.py   │
│  (Flask, порт 5000) (планировщик)       │
│         │                  │            │
│         └──── файлы ───────┘            │
│          schedule.json                  │
│          control.cmd                    │
│          status.json                    │
│          logs/bells.log                 │
│          sounds/*.mp3                   │
└─────────────────────────────────────────┘
        │ AUX 3.5мм → RCA
        ▼
  Усилитель (100V)
        │
        ▼
  Потолочные громкоговорители
```

---

## Файлы проекта

| Файл | Назначение |
|------|-----------|
| `bell_scheduler.py` | Основной демон — следит за временем, играет звонки |
| `web_server.py` | Flask веб-интерфейс управления |
| `bell_manager.py` | Десктопное приложение (Windows/Mac, CustomTkinter + SSH) |
| `bell_control.py` | CLI-управление прямо на Pi |
| `bell_scheduler.service` | systemd unit для автозапуска |
| `bell_web.service` | systemd unit для веб-сервера |
| `schedule.json` | Расписание звонков |

---

## Быстрый старт

### На Raspberry Pi

```bash
# Зависимости
sudo apt update
sudo apt install -y python3 mpg123 alsa-utils ffmpeg
pip3 install flask --break-system-packages

# Скопировать файлы
git clone https://github.com/<user>/bell-scheduler
cd bell-scheduler

# Настроить аудиовыход на AUX
sudo raspi-config
# → System Options → Audio → Headphones

# Запустить
python3 web_server.py        # веб-интерфейс
python3 bell_scheduler.py    # планировщик
```

Открыть в браузере: **`http://<IP Pi>:5000`**  
Пароль задаётся в `web_server.py` → `WEB_PASSWORD`

### Автозапуск через systemd

```bash
sudo cp bell_scheduler.service /etc/systemd/system/
sudo cp bell_web.service       /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bell_scheduler bell_web
sudo systemctl start  bell_scheduler bell_web
```

### Тестовый режим (без Pi, на обычном ПК)

```bash
pip install pygame numpy

# Ускорение x60 — весь учебный день за 15 минут
python3 bell_scheduler.py --test --speed 60
```

---

## Веб-интерфейс

### Дашборд
- Статус сервиса и режим работы (активен / пауза)
- Время последнего звонка
- Кнопки: **Пауза**, **Стоп звонка**, **Перезагр. расп.**, **Рестарт сервиса**
- Журнал событий в реальном времени (Server-Sent Events — без задержек)

### Расписание
- Несколько шаблонов (стандартное, сокращённое и любые свои)
- Редактор каждого звонка: время, тип, дни недели, мелодия, **длительность** (10 / 15 / 20 / 30 / 45 / 60 сек или полная)
- Применение на Pi одной кнопкой

### Звукотека
- Загрузка MP3 / WAV / OGG через drag & drop
- Прослушивание в браузере
- Встроенный редактор обрезки — волновая форма, выделение мышью, превью фрагмента, сохранение через ffmpeg

---

## Расписание (schedule.json)

```json
{
  "schedule": [
    {
      "id": 1,
      "description": "Начало 1-й пары",
      "time": "08:00",
      "days": ["mon", "tue", "wed", "thu", "fri"],
      "sound": "bell_start.mp3",
      "duration": 15,
      "enabled": true
    }
  ]
}
```

| Поле | Описание |
|------|---------|
| `time` | Время в формате `ЧЧ:ММ` |
| `days` | Дни: `mon tue wed thu fri sat sun` |
| `sound` | Имя файла из папки `sounds/` |
| `duration` | Максимальная длина в секундах, `0` = полный файл |
| `enabled` | `false` — временно отключить без удаления |

---

## Команды управления

Планировщик читает файл `control.cmd` каждые 20 секунд:

```bash
# Пауза
echo pause > /home/pi/bell_scheduler/control.cmd

# Снять паузу
echo resume > /home/pi/bell_scheduler/control.cmd

# Прервать текущий звонок
echo stop_sound > /home/pi/bell_scheduler/control.cmd

# Перезагрузить расписание
echo reload > /home/pi/bell_scheduler/control.cmd
```

Или через CLI-утилиту:

```bash
python3 bell_control.py pause
python3 bell_control.py status
```

---

## Железо

| Компонент | Модель |
|-----------|-------|
| Микрокомпьютер | Raspberry Pi 4 Model B |
| Усилитель | Roxton AA-120 (120W, 100V) |
| Громкоговорители | System Sensor SS-ETF221 (потолочные, 10W/100V) |
| Подключение Pi → усилитель | AUX 3.5мм → RCA (линейный вход) |
| Подключение колонки | Синий → клемма 0, Зелёный → клемма 100V |

---

## Стек

- **Python 3** — планировщик и веб-сервер
- **Flask** — веб-интерфейс
- **mpg123 / aplay** — воспроизведение звука
- **ffmpeg** — обрезка аудиофайлов
- **pygame** — воспроизведение в тестовом режиме
- **systemd** — автозапуск сервисов
- **Web Audio API** — волновая форма в браузере
- **Server-Sent Events** — мгновенный лог без поллинга
- **CustomTkinter + Paramiko** — десктопное приложение (опционально)

---

## Структура папок

```
/home/pi/bell_scheduler/
├── bell_scheduler.py
├── web_server.py
├── bell_manager.py
├── bell_control.py
├── schedule.json
├── templates.json
├── status.json
├── control.cmd
├── sounds/
│   ├── bell_start.mp3
│   └── bell_end.mp3
└── logs/
    └── bells.log
```

---

## Лицензия

MIT — делай что хочешь.
