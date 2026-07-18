from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gym_agent.db import Database


@dataclass
class FakeSnapshot:
    id: str
    data: dict[str, Any] | None

    @property
    def exists(self) -> bool:
        return self.data is not None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data or {})


class FakeDocument:
    def __init__(self, client: "FakeClient", path: str):
        self.client = client
        self.path = path
        self.id = path.rsplit("/", 1)[-1]

    def set(self, data: dict[str, Any], merge: bool = False) -> None:
        if merge:
            self.client.data.setdefault(self.path, {}).update(data)
        else:
            self.client.data[self.path] = dict(data)

    def get(self) -> FakeSnapshot:
        return FakeSnapshot(self.id, self.client.data.get(self.path))

    def collection(self, name: str) -> "FakeCollection":
        return FakeCollection(self.client, f"{self.path}/{name}")


class FakeCollection:
    def __init__(self, client: "FakeClient", path: str):
        self.client = client
        self.path = path
        self.descending = False
        self.maximum: int | None = None

    def document(self, document_id: str | None = None) -> FakeDocument:
        if document_id is None:
            self.client.counter += 1
            document_id = f"auto-{self.client.counter}"
        return FakeDocument(self.client, f"{self.path}/{document_id}")

    def order_by(self, field: str, direction: Any = None) -> "FakeCollection":
        query = FakeCollection(self.client, self.path)
        query.descending = direction == "DESCENDING"
        return query

    def limit(self, maximum: int) -> "FakeCollection":
        self.maximum = maximum
        return self

    def stream(self) -> list[FakeSnapshot]:
        prefix = f"{self.path}/"
        rows = [
            FakeSnapshot(path.rsplit("/", 1)[-1], data)
            for path, data in self.client.data.items()
            if path.startswith(prefix) and "/" not in path[len(prefix) :]
        ]
        if rows and "performed_at" in rows[0].to_dict():
            rows.sort(
                key=lambda row: row.to_dict()["performed_at"],
                reverse=self.descending,
            )
        elif rows and "updated_at" in rows[0].to_dict():
            rows.sort(
                key=lambda row: row.to_dict()["updated_at"],
                reverse=self.descending,
            )
        elif rows and "created_at" in rows[0].to_dict():
            rows.sort(
                key=lambda row: row.to_dict()["created_at"],
                reverse=self.descending,
            )
        return rows[: self.maximum] if self.maximum is not None else rows


class FakeBatch:
    def __init__(self):
        self.operations: list[tuple[FakeDocument, dict[str, Any]]] = []

    def set(self, document: FakeDocument, data: dict[str, Any]) -> None:
        self.operations.append((document, data))

    def commit(self) -> None:
        for document, data in self.operations:
            document.set(data)


class FakeClient:
    def __init__(self):
        self.data: dict[str, dict[str, Any]] = {}
        self.counter = 0

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, name)

    def batch(self) -> FakeBatch:
        return FakeBatch()


def test_profile_workout_and_records():
    database = Database(client=FakeClient())
    database.upsert_profile(7, "Ada", {"goals": "strength", "units": "kg"})
    assert database.profile(7)["goals"] == "strength"

    database.log_sets(
        7,
        [
            {"exercise": "Squat", "weight": 100.0, "reps": 5, "rpe": 8.0},
            {"exercise": "Squat", "weight": 105.0, "reps": 3, "rpe": 8.0},
        ],
    )
    assert len(database.recent_sets(7)) == 2
    record = database.personal_records(7)[0]
    assert record["max_weight"] == 105.0
    assert record["estimated_1rm"] > 115


def test_feedback_weight_suggestion_and_saved_plan():
    database = Database(client=FakeClient())
    database.upsert_profile(7, "Ada", {"units": "kg"})
    database.log_sets(
        7, [{"exercise": "Bench Press", "weight": 60.0, "reps": 8, "rpe": 7.0}]
    )
    database.save_feedback(7, "bench press", "increase", "felt easy")
    suggestion = database.weight_suggestions(7)[0]
    assert suggestion["suggested_weight"] == 62.5
    assert suggestion["adjustment"] == "increase"
    assert database.feedback(7)[0]["note"] == "felt easy"
    plan_id = database.save_plan(7, "Upper-body day")
    plan = database.latest_plan(7)
    assert plan and plan["id"] == plan_id and plan["plan"] == "Upper-body day"
