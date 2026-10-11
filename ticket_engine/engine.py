"""Stateless ticket classification with explicit model/credential configuration."""
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from typing import Literal

from .artifacts import EXPECTED, full_rubric_id, verify_checkpoint
from .errors import EngineError
from .normalization import normalize
from .rules import QUESTIONS
from .runtime import load_agent
from .transport import DEFAULT_MODEL, request_jev, validate_config

Provider = Literal["laya", "jev"]


@dataclass(frozen=True)
class ClassificationResult:
    provider: Provider
    model: str
    category: str
    category_label: str
    suggested_team: str
    priority: str
    urgency: float
    complaint: float
    churn: float
    refund: float
    confidence: float
    probabilities: dict[str, float]
    needs_review: bool
    elapsed_ms: int
    input_tokens: int
    analyzed_at: str
    rubric_id: str
    input_id: str
    review_reasons: tuple[str, ...]
    checkpoint_sha256: str | None
    schema_version: int = 1

    def to_dict(self) -> dict:
        value = asdict(self)
        value["review_reasons"] = list(self.review_reasons)
        return value


def validate_input(message, subject):
    if not isinstance(message, str) or len(message) > 3000 or not message.strip():
        raise EngineError("invalid_input", "message must contain 1 to 3000 characters")
    if not isinstance(subject, str) or len(subject) > 120:
        raise EngineError("invalid_input", "subject must be a string of at most 120 characters")
    return {"subject": subject.strip(), "message": message.strip()}


class TicketEngine:
    """Reuse one instance per worker. Calls on an instance are serialized.

    No ticket persistence, web server, configuration discovery, implicit retries
    or automatic provider fallback. Importing this class does not import torch.
    """

    def __init__(self, provider: Provider, *, model_path=None, api_key=None,
                 model=DEFAULT_MODEL, timeout=30):
        if provider not in ("laya", "jev"):
            raise EngineError("invalid_config", "provider must be laya or jev")
        self.provider = provider
        self._lock = threading.Lock()
        self._agent = None
        if provider == "laya":
            if model_path is None or api_key is not None or model != DEFAULT_MODEL or timeout != 30:
                raise EngineError("invalid_config", "Laya requires model_path and accepts no API configuration")
            try:
                self._model_path = Path(model_path).resolve()
            except (TypeError, ValueError, OSError):
                raise EngineError("invalid_config", "model_path must be a local directory path") from None
        else:
            if model_path is not None:
                raise EngineError("invalid_config", "Jev does not accept a local model path")
            validate_config(api_key, model, timeout)
            self._api_key = api_key
            self._model = model
            self._timeout = timeout

    def _prepare_local(self):
        if self._agent is not None:
            return
        try:
            verify_checkpoint(self._model_path, QUESTIONS)
        except (OSError, ValueError, TypeError, KeyError):
            raise EngineError("invalid_checkpoint", "Install the reviewed local checkpoint and verify its files") from None
        try:
            self._agent = load_agent(self._model_path)
        except ImportError:
            raise EngineError("missing_dependency", "Install the local inference dependencies: pip install '.[local]'") from None
        except Exception:
            raise EngineError("model_load_failed", "The verified local model could not be loaded") from None

    def prepare(self):
        """Verify and load local Laya without classifying or invoking a hosted API."""
        if self.provider != "laya":
            raise EngineError("invalid_config", "prepare is only available for local Laya")
        with self._lock:
            self._prepare_local()
        return self

    def classify(self, message: str, *, subject: str = "") -> ClassificationResult:
        state = validate_input(message, subject)
        if full_rubric_id(QUESTIONS) != EXPECTED["rubric_id"]:
            raise EngineError("invalid_config", "The supported classification rules have changed; revalidation is required")
        with self._lock:
            start = time.perf_counter()
            if self.provider == "laya":
                self._prepare_local()
                try:
                    raw = self._agent.predict(deepcopy(state), deepcopy(QUESTIONS))
                    raw = {**raw, "model": "laya-ticket-full-" + EXPECTED["checkpoint_sha256"][:12]}
                except Exception:
                    raise EngineError("inference_failed", "Local classification failed") from None
                checkpoint = EXPECTED["checkpoint_sha256"]
            else:
                raw = request_jev(state, deepcopy(QUESTIONS), api_key=self._api_key,
                                  model=self._model, timeout=self._timeout)
                checkpoint = None
            try:
                data = normalize(raw, self.provider, round((time.perf_counter() - start) * 1000),
                                 state, datetime.now(timezone.utc).isoformat())
            except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
                raise EngineError("invalid_response", "The engine returned an invalid classification result") from None
            reasons = []
            if data["confidence"] < .65:
                reasons.append("low_confidence")
            if data["churn"] >= .5:
                reasons.append("churn_risk")
            return ClassificationResult(**data, review_reasons=tuple(reasons), checkpoint_sha256=checkpoint)


@dataclass(frozen=True)
class ComparisonResult:
    laya: ClassificationResult
    jev: ClassificationResult
    differences: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"laya": self.laya.to_dict(), "jev": self.jev.to_dict(),
                "differences": list(self.differences), "agreement": not self.differences}


def compare(laya: TicketEngine, jev: TicketEngine, message: str, *, subject: str = "") -> ComparisonResult:
    """Explicitly invoke both engines on one input. Failures raise; no retries.

    Jev may charge for a failed/timed-out call. Agreement is not accuracy.
    """
    if not isinstance(laya, TicketEngine) or not isinstance(jev, TicketEngine) or laya.provider != "laya" or jev.provider != "jev":
        raise EngineError("invalid_config", "compare requires a Laya engine followed by a Jev engine")
    state = validate_input(message, subject)
    left = laya.classify(state["message"], subject=state["subject"])
    right = jev.classify(state["message"], subject=state["subject"])
    differences = []
    for name in ("category", "priority", "complaint", "churn", "refund"):
        a, b = getattr(left, name), getattr(right, name)
        if name in ("complaint", "churn", "refund"):
            a, b = a >= .5, b >= .5
        if a != b:
            differences.append(name)
    return ComparisonResult(left, right, tuple(differences))
