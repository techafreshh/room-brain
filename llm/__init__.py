"""LLM package: swappable OpenRouter entry point with keyword fallback."""

from llm.client import LLMUnavailable, llm

__all__ = ["LLMUnavailable", "llm"]
