"""Pinned inference artifact verification, with no model loading on import."""
import hashlib
import json
from pathlib import Path

FULL_FIELDS = ["category", "urgency", "complaint", "churn", "refund"]
REQUIRED_FILES = ("rl_agent_config.json", "model.safetensors", "encoder/config.json", "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json")
EXPECTED = json.loads((Path(__file__).parent / "model-manifest.json").read_text(encoding="utf-8"))

def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def full_rubric_id(questions):
    return hashlib.sha256(json.dumps(questions, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def verify_checkpoint(path, questions, expected=None):
    expected = EXPECTED if expected is None else expected
    path = Path(path)
    record = json.loads((path / "training_manifest.json").read_text(encoding="utf-8"))
    if (record.get("schema_version") != 2 or type(record.get("artifact_version")) is not int
            or record["artifact_version"] != 5 or record.get("trained_fields") != FULL_FIELDS
            or type(record.get("training_steps")) is not int or record["training_steps"] <= 0
            or record.get("rubric_id") != full_rubric_id(questions)
            or record.get("base_checkpoint_sha256") != expected["base_checkpoint_sha256"]
            or record.get("checkpoint_sha256") != expected["checkpoint_sha256"]):
        raise ValueError("Checkpoint identity or task rules do not match the reviewed V5 release")
    files = record.get("files")
    if not isinstance(files, dict) or set(files) != set(REQUIRED_FILES):
        raise ValueError("Only the minimal V5 inference files are accepted")
    for name in REQUIRED_FILES:
        candidate = path / name
        # Reject links and junctions in every component before reading artifacts.
        components = [candidate, *candidate.parents]
        if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in components):
            raise ValueError("Linked model paths are not accepted")
        if not candidate.resolve().is_relative_to(path.resolve()):
            raise ValueError("Checkpoint file escaped model directory")
        expected_hash = expected["files"][name]["sha256"]
        if files[name].get("sha256") != expected_hash or not candidate.is_file() or digest(candidate) != expected_hash:
            raise ValueError("Missing or modified reviewed checkpoint file: " + name)
    encoder = json.loads((path / "encoder/config.json").read_text(encoding="utf-8"))
    tokenizer = json.loads((path / "tokenizer/tokenizer_config.json").read_text(encoding="utf-8"))
    if encoder.get("model_type") != "modernbert" or encoder.get("auto_map") or tokenizer.get("auto_map"):
        raise ValueError("Unexpected architecture or executable remote-code mapping")
    return record

