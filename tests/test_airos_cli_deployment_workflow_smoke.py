from __future__ import annotations

import re
from pathlib import Path

import tools.airos_cli as cli


REPO_ROOT = Path(__file__).resolve().parents[1]

_SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._-]+\b|"
    r"\bAKIA[0-9A-Z]{12,}\b|"
    r"\bghp_[A-Za-z0-9]{20,}\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b|"
    r"\bAIza[0-9A-Za-z_-]{20,}\b"
    r")"
)


def test_cli_init_then_validate_smoke(tmp_path: Path) -> None:
    out = tmp_path / "ws_cli_smoke"
    rc = cli.main(
        [
            "deployment",
            "init",
            "--deployment-id",
            "cli_smoke_dep",
            "--deployment-name",
            "CLI Smoke",
            "--deployment-type",
            "single_agency",
            "--owner-organization",
            "Smoke Org",
            "--environment",
            "local",
            "--domains",
            "air_quality",
            "--providers",
            "__nonexistent_provider_for_placeholder__",
            "--output-dir",
            str(out),
        ]
    )
    assert rc == 0
    for name in (
        "deployment_profile.yaml",
        "provider_registry.yaml",
        "application_registry.yaml",
        "network_adapter_registry.yaml",
        "README.md",
    ):
        assert (out / name).is_file()

    combined = ""
    for p in out.rglob("*"):
        if p.is_file() and p.suffix in {".yaml", ".md"}:
            combined += p.read_text(encoding="utf-8") + "\n"
    assert _SECRET_VALUE_RE.search(combined) is None

    rc_val = cli.main(["deployment", "validate", str(out)])
    assert rc_val == 1

