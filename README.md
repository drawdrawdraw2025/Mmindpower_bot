# Mmindpower_bot 🤖

A Telegram bot with AI chat powered by the **Groq** inference engine (Llama 3.3 70B).

Talk to it: **[@Mmindpower_bot](https://t.me/Mmindpower_bot)**

## Features
- 💬 AI chat — send any message, get an AI answer (with per-chat memory)
- `/start`, `/help`, `/about`, `/reset` commands
- Zero-dependency: only `requests`; long-polling (no webhook/hosting service needed)

## Running
```bash
export TG_TOKEN="***"
export GROQ_KEY="***"
python3 bot.py
```

## Roadmap
- 📚 Quizzes & study tools
- 📢 Broadcasts / announcements
- 🛠 More abilities (enhanced step by step)
