from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
import json
import subprocess
import sys
import time


@dataclass(frozen=True)
class ConformanceProbeResult:
    attempted: bool
    command: list[str]
    exit_code: Optional[int]
    duration_s: Optional[float]
    stdout_tail: Optional[str]
    stderr_tail: Optional[str]
    conformance_report_path: str
    conformance_report_loaded: bool
    conformance_report: Optional[dict]
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _read_json(path: Path) -> tuple[Optional[dict], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return None, f"Failed to read JSON at {path}: {e}"
    try:
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        return None, f"Failed to parse JSON at {path}: {e}"
    if not isinstance(data, dict):
        return None, f"JSON root at {path} is not an object"
    return data, None


def _tail(text: str, max_chars: int = 8000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def probe_conformance(
    repo_root: Path,
    *,
    run: bool,
    report_path: Path | None = None,
) -> ConformanceProbeResult:
    """
    Optionally run conformance and then read the conformance report if available.
    """
    errors: list[str] = []
    conformance_report_path = report_path or (
        repo_root / "data" / "outputs" / "conformance_report.json"
    )

    cmd = [sys.executable, "main.py", "--step", "conformance"]
    attempted = False
    exit_code: Optional[int] = None
    duration_s: Optional[float] = None
    stdout_tail: Optional[str] = None
    stderr_tail: Optional[str] = None

    if run:
        attempted = True
        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            exit_code = proc.returncode
            stdout_tail = _tail(proc.stdout or "")
            stderr_tail = _tail(proc.stderr or "")
        except Exception as e:  # noqa: BLE001
            errors.append(f"Failed to run conformance command: {e}")
        finally:
            duration_s = round(time.time() - start, 3)

    conformance_report_loaded = False
    conformance_report: Optional[dict] = None
    if conformance_report_path.exists():
        data, err = _read_json(conformance_report_path)
        if err:
            errors.append(err)
        else:
            conformance_report_loaded = True
            conformance_report = data

    return ConformanceProbeResult(
        attempted=attempted,
        command=cmd,
        exit_code=exit_code,
        duration_s=duration_s,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        conformance_report_path=str(conformance_report_path.relative_to(repo_root)),
        conformance_report_loaded=conformance_report_loaded,
        conformance_report=conformance_report,
        errors=errors,
    )

