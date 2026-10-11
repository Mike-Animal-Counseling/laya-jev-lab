"""Hosted Jev entry point; importing it does not load the ML runtime."""
from .engine import TicketEngine
from .transport import DEFAULT_MODEL


class JevEngine(TicketEngine):
    def __init__(self, api_key, *, model=DEFAULT_MODEL, timeout=30):
        super().__init__('jev', api_key=api_key, model=model, timeout=timeout)
