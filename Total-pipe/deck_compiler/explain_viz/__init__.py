"""Optional, source-bound native teaching diagrams. No model or renderer service."""
from .adapter import DeckIRAdapter
from .plugin import EnhanceResult, ExplainVizPlugin, enhance
from .prompts import make_prompt

__all__ = ['DeckIRAdapter', 'EnhanceResult', 'ExplainVizPlugin', 'enhance', 'make_prompt']
