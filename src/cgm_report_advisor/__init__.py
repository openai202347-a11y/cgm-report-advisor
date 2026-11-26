"""CGM graphic-report advisor pipeline skeleton.

This package encodes a reusable workflow: extract only what a report actually
states, ask for missing clinical intake required by a local knowledge base,
interpret metrics in a fixed order, and draft diet or activity advice only
when the advice can be traced to that knowledge base.

It is decision-support text, not a formal medical opinion and not a medical
device. It does not adjust prescription drug doses.
"""

__version__ = "0.1.0"

from .pipeline import PipelineResult, run_pipeline

__all__ = ["PipelineResult", "run_pipeline", "__version__"]
