"""skytale: fail-closed session handoff for LLM agents.

Public API:
    skytale.core      - hashing, naming, generation ids
    skytale.gate      - offline verification of a handoff generation
    skytale.cli       - command line interface
"""

from .core import (
    GEN_RE,
    artifact_name,
    generation_id,
    lf_utf8_v1,
    sha256_lf_utf8_v1,
)
from .gate import Check, GateReport, check_generation, render_prompt

__version__ = "0.2.0"

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
