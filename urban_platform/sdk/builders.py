from __future__ import annotations

"""
Metadata-only types for documentation and tests.

**Internal / pilot:** not part of ``urban_platform.sdk.__all__``; no stable
external import contract yet (see ``docs/SDK_SURFACE.md``).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BuilderSpec:
    """
    Metadata-only builder specification for documentation and tests.

    This type does not load or execute builder code.
    """

    builder_id: str
    input_contracts: list[str]
    output_contracts: list[str]
    description: str | None = None

