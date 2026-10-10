"""Demo-only configuration boundary around the shared explicit-key transport."""
from pathlib import Path
from ticket_engine.transport import DEFAULT_MODEL, ENDPOINT, ProviderError, request_jev

ROOT = Path(__file__).resolve().parents[2]


def config():
    values = {}
    path = ROOT / ".env.local"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in ("TYPESAFE_API_KEY", "JEV_MODEL"):
                values[key] = value.strip().strip("\"'")
    return {key: values.get(key, "") for key in ("TYPESAFE_API_KEY", "JEV_MODEL")}


def status():
    values = config()
    return {"status": "ready" if values["TYPESAFE_API_KEY"] else "unconfigured",
            "message": "API configured; verified on use" if values["TYPESAFE_API_KEY"] else "Add your Jev API key",
            "model": values["JEV_MODEL"] or DEFAULT_MODEL, "offline": False}


def predict(state, questions):
    values = config()
    if not values["TYPESAFE_API_KEY"]:
        raise ProviderError("Configure TYPESAFE_API_KEY in .env.local first.", 503)
    return request_jev(state, questions, api_key=values["TYPESAFE_API_KEY"],
                       model=values["JEV_MODEL"] or DEFAULT_MODEL)
