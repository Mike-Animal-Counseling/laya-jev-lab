"""Demo lifecycle adapter around the shared local classification runtime."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "models/ticket-finetuned-v5"
agent = None
manifest = None
model_status = {"status": "unconfigured", "message": "Install the Laya V5 weights. See README.",
                "model": "laya-finetuned", "offline": True, "trained_fields": [],
                "other_fields": None, "artifact_version": None}


from ticket_engine.artifacts import (EXPECTED, FULL_FIELDS, REQUIRED_FILES, digest, full_rubric_id, verify_checkpoint as _verify)
from ticket_engine.runtime import load_agent


def verify_checkpoint(path, questions):
    return _verify(path, questions, expected=EXPECTED)


def load(questions):
    global agent, manifest
    agent, manifest = None, None
    model_status.update(status="unconfigured", message="Install the Laya V5 weights. See README.",
                        trained_fields=[], artifact_version=None)
    try:
        if not (MODEL / "training_manifest.json").is_file():
            return
        model_status.update(status="loading", message="Loading Laya V5")
        checked = verify_checkpoint(MODEL, questions)
        # This demo owns its process; embedded SDK callers choose their own budget.
        import torch
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        loaded = load_agent(MODEL)
        agent, manifest = loaded, checked
        model_status.update(status="ready", message="Laya V5 ready",
            model="laya-ticket-full-" + checked["checkpoint_sha256"][:12],
            trained_fields=FULL_FIELDS, artifact_version=5)
        print("Laya V5 ready (CPU, verified, offline)", flush=True)
    except Exception as exc:
        model_status.update(status="error", message="Model verification or loading failed. See README.")
        print(f"Laya V5 unavailable: {type(exc).__name__}", flush=True)


def predict(state, questions):
    if agent is None or manifest is None or model_status["status"] != "ready":
        raise RuntimeError("Laya V5 is not ready")
    if full_rubric_id(questions) != manifest["rubric_id"]:
        raise RuntimeError("Rules changed. Verify the model again.")
    result = agent.predict(state, questions)
    if set(result["answers"]) != set(FULL_FIELDS):
        raise RuntimeError("Model response is missing signals")
    return {**result, "model": model_status["model"],
            "field_sources": {key: "laya-ft" for key in questions},
            "checkpoint_sha256": manifest["checkpoint_sha256"]}
