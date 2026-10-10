"""SaaS ticket classification: five supported categories, two explicit engines."""
from .engine import ClassificationResult, ComparisonResult, TicketEngine, compare
from .errors import EngineError

__all__ = ["TicketEngine", "ClassificationResult", "ComparisonResult", "compare", "EngineError"]
