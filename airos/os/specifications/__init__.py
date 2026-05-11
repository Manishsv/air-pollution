"""Load JSON Schema specifications and validate artifacts (conformance)."""

from airos.os.specifications.conformance import (
    assert_conforms,
    iter_manifest_schema_paths,
    load_manifest,
    schema_dir,
    validator_for_schema_file,
)
from airos.os.specifications.engine import run_conformance
from airos.os.specifications.runtime_validation import validate_artifact, validate_output_artifacts

__all__ = [
    "assert_conforms",
    "iter_manifest_schema_paths",
    "load_manifest",
    "schema_dir",
    "validator_for_schema_file",
    "validate_artifact",
    "validate_output_artifacts",
    "run_conformance",
]
