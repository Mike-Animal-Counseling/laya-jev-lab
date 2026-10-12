"""Local Laya entry point; no API credential or hosted service required."""
from .engine import TicketEngine


class LayaEngine(TicketEngine):
    def __init__(self, model_path, *, adapter_path=None):
        super().__init__('laya', model_path=model_path, adapter_path=adapter_path)
