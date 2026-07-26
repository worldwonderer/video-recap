"""Public narration-brief API for this self-contained skill."""
# GENERATED FILE — do not edit here.
# Source: shared/brief_entry.py. Edit that, then run: python scripts/sync_shared.py
# Copied rather than imported because skills must stay self-contained.

from agent_brief import build_agent_brief
from brief_context import assess_understanding_substrate
from narration_lint import lint_narration, validate_narration_or_raise

__all__ = [
    "assess_understanding_substrate",
    "build_agent_brief",
    "lint_narration",
    "validate_narration_or_raise",
]
