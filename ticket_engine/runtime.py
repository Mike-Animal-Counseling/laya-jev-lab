"""Lazy, private local runtime. Does not alter host environment or sys.path."""
from pathlib import Path


def load_agent(model_path: Path):
    from ._vendor.laya.agent import load
    return load(str(model_path.resolve()), device="cpu")
