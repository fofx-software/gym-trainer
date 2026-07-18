from pathlib import Path

from gym_agent.db import Database


def test_profile_workout_and_records(tmp_path: Path):
    database = Database(tmp_path / "test.db")
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


def test_feedback_weight_suggestion_and_saved_plan(tmp_path: Path):
    database = Database(tmp_path / "test.db")
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
