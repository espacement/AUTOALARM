# 🔔 Bell Scheduler — Raspberry Pi 4

Система автоматического управления звонками на пары и с пар.
Воспроизводит `.mp3` / `.wav` файлы через аудиовыход Raspberry Pi.

---

## 📁 Структура проекта

```
/home/pi/bell_scheduler/
├── bell_scheduler.py      # Основной сервис (демон)
├── bell_control.py        # CLI-управление (пауза, стоп, статус)
├── bell_scheduler.service # Файл systemd для автозапуска
├── schedule.json          # Расписание звонков
├── sounds/                # Папка с аудиофайлами
│   ├── bell_start.mp3     # Мелодия начала пары
│   └── bell_end.mp3       # Мелодия конца пары
├── logs/
│   ├── bells.log          # Лог всех звонков
│   └── service.log        # Лог systemd
└── status.json            # Текущий статус (читается приложением на ПК)
```

---

## 🚀 Установка

### 1. Скопировать файлы на Pi

```bash
scp -r bell_scheduler/ pi@<IP-адрес>:/home/pi/
```

### 2. Установить зависимости

```bash
# Основные аудиоплееры
sudo apt update
sudo apt install -y mpg123 alsa-utils

# Опционально — если не установлен python3
sudo apt install -y python3
```

### 3. Положить звуковые файлы

```bash
scp bell_start.mp3 bell_end.mp3 pi@<IP>:/home/pi/bell_scheduler/sounds/
```

### 4. Проверить вручную

```bash
python3 /home/pi/bell_scheduler/bell_scheduler.py
```

### 5. Установить как системный сервис (автозапуск)

```bash
# Копируем unit-файл
sudo cp /home/pi/bell_scheduler/bell_scheduler.service /etc/systemd/system/

# Активируем и запускаем
sudo systemctl daemon-reload
sudo systemctl enable bell_scheduler
sudo systemctl start bell_scheduler

# Проверяем статус
sudo systemctl status bell_scheduler
```

---

## 🎛 Управление из командной строки (на Pi)

```bash
python3 bell_control.py pause       # Поставить на паузу
python3 bell_control.py resume      # Снять с паузы
python3 bell_control.py stop_sound  # Прервать текущий звонок
python3 bell_control.py stop        # Остановить сервис
python3 bell_control.py reload      # Перезагрузить расписание
python3 bell_control.py status      # Показать текущий статус
```

---

## 💻 Управление с компьютера (через SSH/SCP)

### Обновить расписание

```bash
# С компьютера — отправить новый schedule.json и перезагрузить
scp schedule.json pi@<IP>:/home/pi/bell_scheduler/schedule.json
ssh pi@<IP> "echo reload > /home/pi/bell_scheduler/control.cmd"
```

### Экстренная пауза

```bash
ssh pi@<IP> "echo pause > /home/pi/bell_scheduler/control.cmd"
```

### Снять паузу

```bash
ssh pi@<IP> "echo resume > /home/pi/bell_scheduler/control.cmd"
```

### Прочитать статус

```bash
scp pi@<IP>:/home/pi/bell_scheduler/status.json ./
cat status.json
```

---

## 📋 Формат расписания (schedule.json)

```json
{
  "schedule": [
    {
      "id": 1,
      "description": "Начало 1-й пары",
      "time": "08:00",
      "days": ["mon", "tue", "wed", "thu", "fri"],
      "sound": "bell_start.mp3",
      "enabled": true
    }
  ]
}
```

| Поле          | Тип     | Описание                                         |
|---------------|---------|--------------------------------------------------|
| `id`          | число   | Уникальный идентификатор                         |
| `description` | строка  | Описание (отображается в логе)                   |
| `time`        | `HH:MM` | Время срабатывания                               |
| `days`        | массив  | Дни: `mon tue wed thu fri sat sun`               |
| `sound`       | строка  | Имя файла из папки `sounds/`                     |
| `enabled`     | bool    | `false` — временно отключить без удаления        |

---

## 🔊 Настройка аудиовыхода

```bash
# Проверить доступные устройства вывода
aplay -l

# Выбрать выход: 0 = авто, 1 = AUX (3.5мм), 2 = HDMI
sudo raspi-config
# Выбрать: System Options → Audio
```

---

## 🛠 Устранение неполадок

| Проблема                          | Решение                                               |
|-----------------------------------|-------------------------------------------------------|
| Нет звука                         | `aplay -l`, проверить выход в `raspi-config`          |
| `mpg123: not found`               | `sudo apt install mpg123`                             |
| Сервис не запускается             | `sudo journalctl -u bell_scheduler -n 50`             |
| Расписание не применяется         | Отправить команду `reload` или перезапустить сервис   |
| Время на Pi не совпадает          | `sudo timedatectl set-timezone Europe/Moscow`         |

---

## 📝 Просмотр логов

```bash
# Лог звонков в реальном времени
tail -f /home/pi/bell_scheduler/logs/bells.log

# Лог сервиса systemd
sudo journalctl -u bell_scheduler -f
```
