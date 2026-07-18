from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS profiles (
    telegram_user_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    goals TEXT NOT NULL DEFAULT '',
    experience TEXT NOT NULL DEFAULT '',
    schedule TEXT NOT NULL DEFAULT '',
    equipment TEXT NOT NULL DEFAULT '',
    limitations TEXT NOT NULL DEFAULT '',
    units TEXT NOT NULL DEFAULT 'lb',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    performed_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    exercise TEXT NOT NULL COLLATE NOCASE,
    weight REAL NOT NULL CHECK(weight >= 0),
    reps INTEGER NOT NULL CHECK(reps > 0),
    rpe REAL CHECK(rpe IS NULL OR (rpe >= 1 AND rpe <= 10))
);

CREATE INDEX IF NOT EXISTS idx_workouts_user_date
ON workouts(telegram_user_id, performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sets_exercise ON sets(exercise);

CREATE TABLE IF NOT EXISTS exercise_feedback (
    telegram_user_id INTEGER NOT NULL,
    exercise TEXT NOT NULL COLLATE NOCASE,
    adjustment TEXT NOT NULL CHECK(adjustment IN ('increase', 'same', 'decrease')),
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (telegram_user_id, exercise)
);

CREATE TABLE IF NOT EXISTS workout_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    plan TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plans_user_date
ON workout_plans(telegram_user_id, created_at DESC);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def upsert_profile(self, user_id: int, display_name: str, fields: dict[str, str]) -> None:
        allowed = {"goals", "experience", "schedule", "equipment", "limitations", "units"}
        clean = {key: value.strip() for key, value in fields.items() if key in allowed}
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO profiles (telegram_user_id, display_name, updated_at) "
                "VALUES (?, ?, ?)",
                (user_id, display_name, now),
            )
            assignments = ["display_name = ?", "updated_at = ?"]
            values: list[object] = [display_name, now]
            for key, value in clean.items():
                assignments.append(f"{key} = ?")
                values.append(value)
            values.append(user_id)
            connection.execute(
                f"UPDATE profiles SET {', '.join(assignments)} WHERE telegram_user_id = ?",
                values,
            )

    def profile(self, user_id: int) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM profiles WHERE telegram_user_id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def log_sets(self, user_id: int, sets: list[dict[str, object]], notes: str = "") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO workouts (telegram_user_id, performed_at, notes) VALUES (?, ?, ?)",
                (user_id, now, notes),
            )
            workout_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO sets (workout_id, exercise, weight, reps, rpe) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (workout_id, s["exercise"], s["weight"], s["reps"], s.get("rpe"))
                    for s in sets
                ],
            )
        return workout_id

    def recent_sets(self, user_id: int, limit: int = 40) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT w.performed_at, s.exercise, s.weight, s.reps, s.rpe
                   FROM sets s JOIN workouts w ON w.id = s.workout_id
                   WHERE w.telegram_user_id = ?
                   ORDER BY w.performed_at DESC, s.id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def personal_records(self, user_id: int) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT s.exercise, MAX(s.weight) AS max_weight,
                          MAX(s.weight * (1.0 + s.reps / 30.0)) AS estimated_1rm
                   FROM sets s JOIN workouts w ON w.id = s.workout_id
                   WHERE w.telegram_user_id = ? GROUP BY lower(s.exercise)
                   ORDER BY exercise""",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_feedback(
        self, user_id: int, exercise: str, adjustment: str, note: str = ""
    ) -> None:
        if adjustment not in {"increase", "same", "decrease"}:
            raise ValueError("Adjustment must be increase, same, or decrease")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO exercise_feedback
                   (telegram_user_id, exercise, adjustment, note, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(telegram_user_id, exercise) DO UPDATE SET
                     adjustment = excluded.adjustment, note = excluded.note,
                     updated_at = excluded.updated_at""",
                (user_id, exercise.strip().title(), adjustment, note.strip(), now),
            )

    def feedback(self, user_id: int) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT exercise, adjustment, note, updated_at
                   FROM exercise_feedback WHERE telegram_user_id = ?
                   ORDER BY updated_at DESC""",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def weight_suggestions(self, user_id: int) -> list[dict[str, object]]:
        """Suggest the next load from the latest set and saved athlete feedback."""
        profile = self.profile(user_id) or {}
        units = str(profile.get("units", "lb")).lower()
        default_step = 2.5 if units in {"kg", "kgs", "kilograms"} else 5.0
        with self.connect() as connection:
            rows = connection.execute(
                """WITH ranked AS (
                       SELECT s.exercise, s.weight, s.reps, s.rpe,
                              ROW_NUMBER() OVER (
                                  PARTITION BY lower(s.exercise)
                                  ORDER BY w.performed_at DESC, s.id DESC
                              ) AS position
                       FROM sets s JOIN workouts w ON w.id = s.workout_id
                       WHERE w.telegram_user_id = ?
                   )
                   SELECT r.exercise, r.weight, r.reps, r.rpe,
                          f.adjustment, f.note
                   FROM ranked r
                   LEFT JOIN exercise_feedback f
                     ON f.telegram_user_id = ? AND f.exercise = r.exercise
                   WHERE r.position = 1 ORDER BY r.exercise""",
                (user_id, user_id),
            ).fetchall()
        suggestions = []
        for row in rows:
            item = dict(row)
            adjustment = item.get("adjustment")
            delta = default_step if adjustment == "increase" else 0.0
            if adjustment == "decrease":
                delta = -default_step
            item["suggested_weight"] = max(0.0, float(item["weight"]) + delta)
            item["units"] = units
            suggestions.append(item)
        return suggestions

    def save_plan(self, user_id: int, plan: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO workout_plans (telegram_user_id, created_at, plan) VALUES (?, ?, ?)",
                (user_id, now, plan),
            )
        return int(cursor.lastrowid)

    def latest_plan(self, user_id: int) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, created_at, plan FROM workout_plans
                   WHERE telegram_user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None
