from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .coach import Coach
from .config import Settings
from .db import Database
from .parsing import parse_feedback, parse_profile, parse_sets


logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

HELP = """<b>Gym Agent</b>

/profile goals=strength; experience=intermediate; schedule=4 days; equipment=full gym; limitations=none; units=lb
/workout — create and save a new session
/plan — remind me of the latest saved session
/log Bench Press 185x5@8, Bench Press 185x5@8.5
/feedback Bench Press increase — adjust its recommended weight next time
/history — recent sets
/progress — estimated records
/whoami — show your Telegram user ID

Or just message me: “My shoulder feels odd on incline press” or “What should I train today?”"""


class GymBot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings.database_path)
        self.coach = Coach(settings.openai_api_key, settings.model, self.database)

    def allowed(self, update: Update) -> bool:
        user = update.effective_user
        return bool(user) and (
            self.settings.allowed_user_id is None
            or user.id == self.settings.allowed_user_id
        )

    async def guard(self, update: Update) -> bool:
        if self.allowed(update):
            return True
        if update.effective_message:
            await update.effective_message.reply_text("This is a private training bot.")
        return False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.guard(update):
            return
        user = update.effective_user
        assert user and update.effective_message
        self.database.upsert_profile(user.id, user.full_name, {})
        await update.effective_message.reply_text(HELP, parse_mode=ParseMode.HTML)

    async def whoami(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user and update.effective_message:
            await update.effective_message.reply_text(str(update.effective_user.id))

    async def profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.guard(update):
            return
        user = update.effective_user
        assert user and update.effective_message
        if not context.args:
            profile = self.database.profile(user.id)
            await update.effective_message.reply_text(
                html.escape(str(profile)) if profile else "No profile yet. See /start for an example."
            )
            return
        try:
            fields = parse_profile(" ".join(context.args))
            self.database.upsert_profile(user.id, user.full_name, fields)
            await update.effective_message.reply_text("Profile saved.")
        except ValueError as error:
            await update.effective_message.reply_text(f"Profile not saved: {error}")

    async def log(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.guard(update):
            return
        user = update.effective_user
        assert user and update.effective_message
        try:
            sets = parse_sets(" ".join(context.args))
            self.database.log_sets(user.id, sets)
            await update.effective_message.reply_text(f"Logged {len(sets)} set(s). Nice work.")
        except ValueError as error:
            await update.effective_message.reply_text(
                f"Nothing logged: {error}\nExample: /log Squat 225x5@8, Squat 225x5@8.5"
            )

    async def history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.guard(update):
            return
        user = update.effective_user
        assert user and update.effective_message
        rows = self.database.recent_sets(user.id, 15)
        if not rows:
            await update.effective_message.reply_text("No sets logged yet.")
            return
        lines = [
            f"{str(row['performed_at'])[:10]} · {row['exercise']} — {row['weight']:g}×{row['reps']}"
            + (f" @ {row['rpe']:g}" if row["rpe"] is not None else "")
            for row in rows
        ]
        await update.effective_message.reply_text("\n".join(lines))

    async def progress(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.guard(update):
            return
        user = update.effective_user
        assert user and update.effective_message
        rows = self.database.personal_records(user.id)
        if not rows:
            await update.effective_message.reply_text("Log a workout first, then I can show progress.")
            return
        lines = [
            f"{row['exercise']}: max {row['max_weight']:g}, est. 1RM {row['estimated_1rm']:.1f}"
            for row in rows
        ]
        await update.effective_message.reply_text("\n".join(lines))

    async def workout(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        answer = await self._coach(
            update,
            "Create today's workout based on my goals, schedule, recent training, recovery, "
            "and next-weight suggestions. Make the session easy to follow at the gym.",
            reply=False,
        )
        if answer is not None and update.effective_user and update.effective_message:
            self.database.save_plan(update.effective_user.id, answer)
            await update.effective_message.reply_text(answer[:4096])

    async def plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.guard(update):
            return
        user = update.effective_user
        assert user and update.effective_message
        plan = self.database.latest_plan(user.id)
        if not plan:
            await update.effective_message.reply_text(
                "No saved workout yet. Use /workout and I'll create one."
            )
            return
        created = str(plan["created_at"])[:10]
        await update.effective_message.reply_text(
            f"Latest plan ({created}):\n\n{str(plan['plan'])}"[:4096]
        )

    async def feedback_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self.guard(update):
            return
        user = update.effective_user
        assert user and update.effective_message
        try:
            item = parse_feedback(" ".join(context.args))
            self.database.save_feedback(
                user.id, item["exercise"], item["adjustment"], item["note"]
            )
            suggestions = {
                str(row["exercise"]).lower(): row
                for row in self.database.weight_suggestions(user.id)
            }
            suggestion = suggestions.get(item["exercise"].lower())
            message = f"Saved: {item['exercise']} → {item['adjustment']} next time."
            if suggestion:
                message += (
                    f" Current next-load suggestion: {suggestion['suggested_weight']:g} "
                    f"{suggestion['units']}."
                )
            else:
                message += " Log a set for it so I have a starting weight."
            await update.effective_message.reply_text(message)
        except ValueError as error:
            await update.effective_message.reply_text(
                f"Feedback not saved: {error}\nExample: /feedback Bench Press increase"
            )

    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message and update.effective_message.text:
            await self._coach(update, update.effective_message.text)

    async def _coach(self, update: Update, message: str, reply: bool = True) -> str | None:
        if not await self.guard(update):
            return None
        user = update.effective_user
        assert user and update.effective_message
        self.database.upsert_profile(user.id, user.full_name, {})
        await update.effective_message.reply_chat_action("typing")
        try:
            answer = await self.coach.answer(user.id, message)
            if reply:
                await update.effective_message.reply_text(answer[:4096])
            return answer
        except Exception:
            logger.exception("Coach request failed")
            await update.effective_message.reply_text(
                "I couldn't reach the coaching service. Your logged data is safe; try again shortly."
            )
            return None

    async def error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Unhandled Telegram update", exc_info=context.error)

    def application(self) -> Application:
        app = Application.builder().token(self.settings.telegram_token).build()
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("help", self.start))
        app.add_handler(CommandHandler("whoami", self.whoami))
        app.add_handler(CommandHandler("profile", self.profile))
        app.add_handler(CommandHandler("log", self.log))
        app.add_handler(CommandHandler("history", self.history))
        app.add_handler(CommandHandler("progress", self.progress))
        app.add_handler(CommandHandler("workout", self.workout))
        app.add_handler(CommandHandler("plan", self.plan))
        app.add_handler(CommandHandler("feedback", self.feedback_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.chat))
        app.add_error_handler(self.error)
        return app


def main() -> None:
    settings = Settings.from_env()
    GymBot(settings).application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
