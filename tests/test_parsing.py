import pytest

from gym_agent.parsing import parse_feedback, parse_profile, parse_sets


def test_parse_multiple_sets():
    assert parse_sets("Bench Press 185x5@8, Bench Press 190 x 4 @ 8.5") == [
        {"exercise": "Bench Press", "weight": 185.0, "reps": 5, "rpe": 8.0},
        {"exercise": "Bench Press", "weight": 190.0, "reps": 4, "rpe": 8.5},
    ]


def test_rejects_invalid_set():
    with pytest.raises(ValueError):
        parse_sets("bench was pretty good")


def test_rejects_invalid_rpe():
    with pytest.raises(ValueError, match="RPE"):
        parse_sets("Squat 225x5@11")


def test_parse_profile():
    assert parse_profile("goals=strength; schedule=4 days") == {
        "goals": "strength",
        "schedule": "4 days",
    }


def test_parse_feedback():
    assert parse_feedback("bench press increase - felt easy") == {
        "exercise": "Bench Press",
        "adjustment": "increase",
        "note": "felt easy",
    }


def test_rejects_invalid_feedback():
    with pytest.raises(ValueError):
        parse_feedback("bench felt good")
