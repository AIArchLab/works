"""handoff-kit: fail-closed session handoff for LLM agents.

Public API:
    handoff_kit.core      - hashing, naming, generation ids
    handoff_kit.gate      - offline verification of a handoff generation
    handoff_kit.cli       - command line interface
"""

from .core import (
    GEN_RE,
    artifact_name,
    generation_id,
    lf_utf8_v1,
    sha256_lf_utf8_v1,
)
from .gate import Check, GateReport, check_generation, render_prompt

__version__ = "0.1.0"

__all__ = [
    "GEN_RE",
    "artifact_name",
    "generation_id",
    "lf_utf8_v1",
    "sha256_lf_utf8_v1",
    "Check",
    "GateReport",
    "check_generation",
    "render_prompt",
    "__version__",
]
