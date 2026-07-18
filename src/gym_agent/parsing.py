from __future__ import annotations

import re


SET_PATTERN = re.compile(
    r"^\s*(?P<exercise>.+?)\s+(?P<weight>\d+(?:\.\d+)?)\s*[x×]\s*"
    r"(?P<reps>\d+)(?:\s*@\s*(?P<rpe>\d+(?:\.\d+)?))?\s*$",
    re.IGNORECASE,
)


def parse_sets(text: str) -> list[dict[str, object]]:
    """Parse `exercise weight x reps @ rpe`, one set per comma or newline."""
    parsed: list[dict[str, object]] = []
    for item in re.split(r"[,;\n]+", text):
        if not item.strip():
            continue
        match = SET_PATTERN.match(item)
        if not match:
            raise ValueError(f"Could not parse: {item.strip()!r}")
        rpe = float(match.group("rpe")) if match.group("rpe") else None
        if rpe is not None and not 1 <= rpe <= 10:
            raise ValueError("RPE must be between 1 and 10")
        parsed.append(
            {
                "exercise": match.group("exercise").strip().title(),
                "weight": float(match.group("weight")),
                "reps": int(match.group("reps")),
                "rpe": rpe,
            }
        )
    if not parsed:
        raise ValueError("No sets found")
    return parsed


def parse_profile(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for item in re.split(r"[;\n]+", text):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError(f"Expected key=value, got {item.strip()!r}")
        key, value = item.split("=", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


FEEDBACK_PATTERN = re.compile(
    r"^\s*(?P<exercise>.+?)\s+(?P<adjustment>increase|same|decrease)"
    r"(?:\s*[-:]\s*(?P<note>.+))?\s*$",
    re.IGNORECASE,
)


def parse_feedback(text: str) -> dict[str, str]:
    """Parse an exercise adjustment with an optional note."""
    match = FEEDBACK_PATTERN.match(text)
    if not match:
        raise ValueError("Use: Exercise increase, Exercise same, or Exercise decrease")
    return {
        "exercise": match.group("exercise").strip().title(),
        "adjustment": match.group("adjustment").lower(),
        "note": (match.group("note") or "").strip(),
    }
