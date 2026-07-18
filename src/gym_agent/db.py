from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

from google.cloud import firestore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _feedback_id(exercise: str) -> str:
    return hashlib.sha256(exercise.strip().casefold().encode()).hexdigest()


class Database:
    """Firestore persistence for athlete profiles, training, feedback, and plans."""

    def __init__(
        self,
        project: str | None = None,
        database: str = "(default)",
        client: Any | None = None,
    ):
        self.client = client or firestore.Client(project=project, database=database)

    def _user(self, user_id: int) -> Any:
        return self.client.collection("users").document(str(user_id))

    def upsert_profile(self, user_id: int, display_name: str, fields: dict[str, str]) -> None:
        allowed = {"goals", "experience", "schedule", "equipment", "limitations", "units"}
        clean = {key: value.strip() for key, value in fields.items() if key in allowed}
        clean.update({"display_name": display_name, "updated_at": _now()})
        self._user(user_id).set(clean, merge=True)

    def profile(self, user_id: int) -> dict[str, object] | None:
        snapshot = self._user(user_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def log_sets(self, user_id: int, sets: list[dict[str, object]], notes: str = "") -> str:
        user = self._user(user_id)
        workout = user.collection("workouts").document()
        performed_at = _now()
        batch = self.client.batch()
        batch.set(workout, {"performed_at": performed_at, "notes": notes})
        for item in sets:
            set_ref = user.collection("sets").document()
            batch.set(
                set_ref,
                {
                    "workout_id": workout.id,
                    "performed_at": performed_at,
                    "exercise": item["exercise"],
                    "weight": float(item["weight"]),
                    "reps": int(item["reps"]),
                    "rpe": item.get("rpe"),
                },
            )
        batch.commit()
        return workout.id

    def recent_sets(self, user_id: int, limit: int = 40) -> list[dict[str, object]]:
        query = (
            self._user(user_id)
            .collection("sets")
            .order_by("performed_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [snapshot.to_dict() for snapshot in query.stream()]

    def personal_records(self, user_id: int) -> list[dict[str, object]]:
        records: dict[str, dict[str, object]] = {}
        for snapshot in self._user(user_id).collection("sets").stream():
            item = snapshot.to_dict()
            key = str(item["exercise"]).casefold()
            estimate = float(item["weight"]) * (1.0 + int(item["reps"]) / 30.0)
            record = records.setdefault(
                key,
                {
                    "exercise": item["exercise"],
                    "max_weight": float(item["weight"]),
                    "estimated_1rm": estimate,
                },
            )
            record["max_weight"] = max(float(record["max_weight"]), float(item["weight"]))
            record["estimated_1rm"] = max(float(record["estimated_1rm"]), estimate)
        return sorted(records.values(), key=lambda item: str(item["exercise"]).casefold())

    def save_feedback(
        self, user_id: int, exercise: str, adjustment: str, note: str = ""
    ) -> None:
        if adjustment not in {"increase", "same", "decrease"}:
            raise ValueError("Adjustment must be increase, same, or decrease")
        normalized = exercise.strip().title()
        self._user(user_id).collection("feedback").document(_feedback_id(normalized)).set(
            {
                "exercise": normalized,
                "adjustment": adjustment,
                "note": note.strip(),
                "updated_at": _now(),
            }
        )

    def feedback(self, user_id: int) -> list[dict[str, object]]:
        query = self._user(user_id).collection("feedback").order_by(
            "updated_at", direction=firestore.Query.DESCENDING
        )
        return [snapshot.to_dict() for snapshot in query.stream()]

    def weight_suggestions(self, user_id: int) -> list[dict[str, object]]:
        profile = self.profile(user_id) or {}
        units = str(profile.get("units", "lb")).lower()
        default_step = 2.5 if units in {"kg", "kgs", "kilograms"} else 5.0
        feedback = {
            str(item["exercise"]).casefold(): item for item in self.feedback(user_id)
        }
        latest: dict[str, dict[str, object]] = {}
        for item in self.recent_sets(user_id, limit=500):
            key = str(item["exercise"]).casefold()
            latest.setdefault(key, item)

        suggestions = []
        for key, source in latest.items():
            item = dict(source)
            saved = feedback.get(key, {})
            adjustment = saved.get("adjustment")
            delta = default_step if adjustment == "increase" else 0.0
            if adjustment == "decrease":
                delta = -default_step
            item.update(
                {
                    "adjustment": adjustment,
                    "note": saved.get("note", ""),
                    "suggested_weight": max(0.0, float(item["weight"]) + delta),
                    "units": units,
                }
            )
            suggestions.append(item)
        return sorted(suggestions, key=lambda item: str(item["exercise"]).casefold())

    def save_plan(self, user_id: int, plan: str) -> str:
        reference = self._user(user_id).collection("plans").document()
        reference.set({"created_at": _now(), "plan": plan})
        return reference.id

    def latest_plan(self, user_id: int) -> dict[str, object] | None:
        query = (
            self._user(user_id)
            .collection("plans")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(1)
        )
        snapshots = list(query.stream())
        if not snapshots:
            return None
        result = snapshots[0].to_dict()
        result["id"] = snapshots[0].id
        return result
