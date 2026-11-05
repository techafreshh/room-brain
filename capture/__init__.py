"""Capture package: injection guard plus passive debounced extractor."""

from capture.extract import (
    BATCH_SIZE,
    CONFIDENCE_THRESHOLD,
    DEBOUNCE_SECONDS,
    CaptureQueue,
    ExtractionResult,
    extract_and_store,
    llm,
    parse_extraction,
    process_extraction,
)
from capture.guard import clean

__all__ = [
    "clean",
    "CaptureQueue",
    "ExtractionResult",
    "extract_and_store",
    "llm",
    "parse_extraction",
    "process_extraction",
    "BATCH_SIZE",
    "CONFIDENCE_THRESHOLD",
    "DEBOUNCE_SECONDS",
]
