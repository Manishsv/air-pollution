"""Backward-compatibility shim — urban_platform/ has moved to airos/.

Old code using ``from urban_platform.X import Y`` will continue to work via
the individual subpackage shims.  Prefer ``from airos.X import Y`` in new code.

This top-level shim ensures any ``import urban_platform`` doesn't crash.
"""
# airos.__init__ handles dotenv loading; nothing else needed here.
import airos as _airos  # noqa: F401 — triggers .env auto-load
