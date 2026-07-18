from __future__ import annotations

import asyncio
import json

from openai import OpenAI

from .db import Database


SYSTEM_PROMPT = """You are a careful, encouraging personal weightlifting coach speaking through
Telegram. Be concise and practical. Use the athlete profile and logged training as the source of
truth. For workouts, give exercise, warm-up guidance, working sets, reps, target RPE/RIR, rest, and
one progression rule. Use provided next-weight suggestions when available. Treat an athlete's
increase/same/decrease feedback as their preference for the next session, but choose a conservative
load and never invent a known weight. Do not diagnose injuries or prescribe treatment. If pain,
fainting, chest
pain, severe shortness of breath, or an acute injury is mentioned, advise stopping and seeking an
appropriate medical professional. Never encourage maximal attempts without adequate history.
Distinguish estimates from known facts. Ask at most one useful question at a time.
"""


class Coach:
    def __init__(self, api_key: str, model: str, database: Database):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.database = database

    async def answer(self, user_id: int, message: str) -> str:
        profile = self.database.profile(user_id) or {}
        recent = self.database.recent_sets(user_id, limit=30)
        context = json.dumps(
            {
                "profile": profile,
                "recent_sets": recent,
                "exercise_feedback": self.database.feedback(user_id),
                "next_weight_suggestions": self.database.weight_suggestions(user_id),
            },
            default=str,
        )

        def request() -> str:
            response = self.client.responses.create(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=f"ATHLETE DATA:\n{context}\n\nATHLETE MESSAGE:\n{message}",
            )
            return response.output_text

        return await asyncio.to_thread(request)
