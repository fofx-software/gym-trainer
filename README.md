# Gym Agent

A private Telegram personal trainer that remembers your profile and lifting history, logs sets,
shows estimated progress, and uses OpenAI for context-aware workout suggestions and coaching.

## What it does

- Stores profile, workouts, sets, RPE, and estimated personal records in local SQLite.
- Suggests workouts from your goals, constraints, schedule, equipment, and recent sessions.
- Accepts concise gym-floor logging such as `/log Squat 225x5@8, Squat 225x5@8.5`.
- Restricts access to one Telegram user when `ALLOWED_TELEGRAM_USER_ID` is configured.
- Keeps fitness data local; only the profile and latest 30 sets are sent to OpenAI when coaching.

This is a coaching aid, not medical care. Stop training and seek appropriate medical help for
chest pain, fainting, severe shortness of breath, or an acute injury.

## Setup

1. In Telegram, message `@BotFather`, run `/newbot`, and copy the bot token.
2. Create a Python 3.11+ virtual environment and install the project:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e '.[dev]'
   ```

3. Copy `.env.example` to `.env` and add your Telegram token and OpenAI API key.
4. Initially leave `ALLOWED_TELEGRAM_USER_ID` empty. Start the bot and send `/whoami`:

   ```bash
   gym-agent
   ```

5. Stop it, put the returned ID in `.env`, and restart. This makes the bot private.
6. Send `/start`, save your `/profile`, then use `/workout` or chat naturally.

## Commands

```text
/profile goals=strength; experience=intermediate; schedule=4 days; equipment=full gym; limitations=none; units=lb
/workout
/plan
/log Bench Press 185x5@8, Bench Press 185x5@8.5
/feedback Bench Press increase - all sets felt strong
/history
/progress
```

`/workout` creates and saves a goal-aware session. At the gym, `/plan` recalls it. After logging
an exercise, use `/feedback Exercise increase`, `same`, or `decrease`; the bot stores that choice
and applies a conservative 5 lb or 2.5 kg adjustment when recommending the exercise next time.

The bot uses long polling, so it works locally without a public URL. For always-on use, run the
same command on a small server or container with a persistent `data/` directory.

## Development

```bash
pytest
ruff check .
```
