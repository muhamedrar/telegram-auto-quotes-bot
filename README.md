# Telegram Personalized Messaging Bot

This project creates a Telegram bot that can:

- send a personalized message from an API,
- send your own custom message,
- attach an image to every message,
- schedule automatic sends every few days.

## 1. What works right now

- Messages come from an API by default, with a built-in fallback library if the API fails.
- Every send can also include an image from a free image API URL template.
- Scheduled sending works with a saved runtime state file.
- You control the bot using Telegram commands from your admin chat.

## 2. Setup

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your values.

Important values:

- `TELEGRAM_BOT_TOKEN`: your bot token from BotFather
- `TELEGRAM_CHAT_ID`: the Telegram chat ID that should receive messages
- `ADMIN_CHAT_ID`: your own Telegram chat ID, used to control the bot
- `SEND_TIME`: scheduled send time like `20:00`
- `INTERVAL_DAYS`: send every N days
- `SENDS_PER_DAY`: how many times to send on each schedule day
- `RANDOM_TIME_MODE`: `true` or `false` for random daily send times
- `QUOTE_API_URL`: API endpoint for message text. Default is `https://www.affirmations.dev/`
- `MESSAGE_TONE_TAGS`: comma-separated tone tags like `romantic,gentle,encouraging`
- `IMAGE_API_URL_TEMPLATE`: image URL template. Default uses LoremFlickr.
- `IMAGE_TAGS`: one or more image tag groups separated by `|`, for example `flowers,roses,petals/all|sunset,sky,clouds/all`

Then start the bot:

```bash
python3 main.py
```

If you want to run it with Docker in the background instead:

```bash
docker compose up -d --build
```

## 3. Deploy So It Stays Running

The simplest deployment for this bot is a small Linux server or VPS with `systemd`.

1. Copy the project to the server.
2. Create a virtual environment and install dependencies.
3. Put your real values in `.env`.
4. Copy [deploy/telegram-love-bot.service](/mnt/shared/Projects/Nahla/telegram_voice_project/deploy/telegram-love-bot.service) to `/etc/systemd/system/telegram-love-bot.service`.
5. Edit that service file so `User`, `WorkingDirectory`, and `ExecStart` match your server paths.
6. Enable and start the bot service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-love-bot
sudo systemctl status telegram-love-bot
```

Useful commands later:

```bash
sudo systemctl restart telegram-love-bot
sudo journalctl -u telegram-love-bot -f
```

## 4. Bot commands

- `/send_quote`
- `/send_custom Your custom message here`
- `/schedule_on`
- `/schedule_off`
- `/set_time 20:00`
- `/set_interval 2`
- `/set_daily_count 3`
- `/set_random_time on`
- `/set_source api`
- `/set_source custom`
- `/set_custom_schedule You make every day brighter.`
- `/status`

## 5. Telegram notes

The target user or chat usually has to start the bot at least once before the bot can message that account.

If you want the bot to send into a private chat, make sure the `TELEGRAM_CHAT_ID` belongs to that chat.

## 6. API format

The bot can read message text from APIs that return JSON fields like:

- `affirmation`
- `reason`
- `message`
- `text`
- `quote`
- `body`

If the API also returns `author`, the bot includes it in the message caption/text.
