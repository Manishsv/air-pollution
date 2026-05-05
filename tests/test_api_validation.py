from __future__ import annotations

import json
from pathlib import Path

from urban_platform.api.validation import collect_validation_errors

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_collect_validation_errors_empty_for_valid_submission() -> None:
    doc = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json").read_text(
            encoding="utf-8"
        )
    )
    assert collect_validation_errors(doc, schema_name="consumer_city_program_submission") == []


def test_collect_validation_errors_non_empty_for_invalid() -> None:
    errs = collect_validation_errors({}, schema_name="consumer_city_program_submission")
    assert errs
