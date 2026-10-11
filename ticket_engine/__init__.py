"""SaaS ticket classification: five supported categories, two explicit engines."""
from .engine import ClassificationResult, ComparisonResult, TicketEngine, compare
from .errors import EngineError
from .laya import LayaEngine
from .jev import JevEngine
from .http import ServiceClient

__all__ = ["TicketEngine", "LayaEngine", "JevEngine", "ServiceClient", "ClassificationResult", "ComparisonResult", "compare", "EngineError"]
