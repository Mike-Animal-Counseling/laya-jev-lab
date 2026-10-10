"""Shared normalization and validation for both providers; never fabricates a score."""
import hashlib
import json
import math
from .rules import CATEGORIES, QUESTIONS, TEAMS


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


RUBRIC_ID = fingerprint(QUESTIONS)


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Invalid model score")
    return value


def normalize(prediction, provider, elapsed_ms, state, now):
    answers = prediction["answers"]
    category = answers["category"]["choice"]
    if category not in CATEGORIES:
        raise ValueError("Unknown category")
    urgency = number(answers["urgency"]["score"], 0, 3)
    confidence = number(answers["category"]["confidence"], 0, 1)
    probs = answers["category"]["probabilities"]
    if not isinstance(probs, dict) or set(probs) != set(CATEGORIES):
        raise ValueError("Invalid category probabilities")
    for value in probs.values():
        number(value, 0, 1)
    if abs(sum(probs.values()) - 1) > .03 or probs[category] < max(probs.values()):
        raise ValueError("Inconsistent category distribution")
    flags = {key: number(answers[key]["noul"], 0, 1) for key in ("complaint", "churn", "refund")}
    tokens = prediction["usage"]["input_tokens"]
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
        raise ValueError("Invalid usage")
    model = prediction.get("model")
    if not isinstance(model, str) or not 1 <= len(model) <= 256:
        raise ValueError("Invalid model identity")
    return {"category": category, "category_label": CATEGORIES[category],
            "priority": "P1" if urgency >= 1.7 else "P2" if urgency >= .9 else "P3",
            "urgency": urgency, **flags, "confidence": confidence, "probabilities": dict(probs),
            "suggested_team": TEAMS[category], "needs_review": confidence < .65 or flags["churn"] >= .5,
            "elapsed_ms": elapsed_ms, "input_tokens": tokens, "model": model,
            "provider": provider, "analyzed_at": now, "rubric_id": RUBRIC_ID, "input_id": fingerprint(state)}

