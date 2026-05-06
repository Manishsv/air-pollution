from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from urban_platform.specifications.conformance import SPEC_ROOT, load_manifest, validator_for_schema_file


def _load_yaml(path: Path) -> dict:
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(obj, dict)
    return obj


def test_provider_adapter_descriptor_schema_is_valid_json_schema() -> None:
    p = SPEC_ROOT / "platform_objects" / "provider_adapter_descriptor.v1.schema.json"
    schema = json.loads(p.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_provider_adapter_descriptors_validate_against_schema() -> None:
    m = load_manifest()
    assert "platform_provider_adapter_descriptor" in (m.get("artifacts") or {})

    schema_path = (SPEC_ROOT / m["artifacts"]["platform_provider_adapter_descriptor"]["schema_path"]).resolve()
    v = validator_for_schema_file(str(schema_path))

    adapter_paths = [
        SPEC_ROOT / "provider_adapters" / "openaq_air_quality_adapter.v1.yaml",
        SPEC_ROOT / "provider_adapters" / "open_meteo_weather_adapter.v1.yaml",
        SPEC_ROOT / "provider_adapters" / "osm_geospatial_adapter.v1.yaml",
    ]
    for p in adapter_paths:
        d = _load_yaml(p)
        v.validate(d)


def test_provider_adapter_descriptor_invariants() -> None:
    m = load_manifest()
    arts = m.get("artifacts") or {}

    adapter_paths = [
        SPEC_ROOT / "provider_adapters" / "openaq_air_quality_adapter.v1.yaml",
        SPEC_ROOT / "provider_adapters" / "open_meteo_weather_adapter.v1.yaml",
        SPEC_ROOT / "provider_adapters" / "osm_geospatial_adapter.v1.yaml",
    ]
    for p in adapter_paths:
        d = _load_yaml(p)
        adapter_id = str(d.get("adapter_id") or "")
        assert adapter_id and adapter_id.islower()
        assert "__" not in adapter_id

        runtime = d.get("runtime") if isinstance(d.get("runtime"), dict) else {}
        if isinstance(runtime, dict):
            cm = runtime.get("current_module")
            if isinstance(cm, str):
                # Metadata only: should not look like an executable snippet.
                assert "import " not in cm
                assert "exec(" not in cm

        safety = d.get("safety") if isinstance(d.get("safety"), dict) else {}
        assert isinstance(safety, dict)
        assert safety.get("produces_final_decisions") is False

        out_contracts = d.get("output_contracts") or []
        assert isinstance(out_contracts, list)
        # Must exist in manifest, unless explicitly empty.
        if out_contracts:
            for ck in out_contracts:
                assert isinstance(ck, str)
                assert ck in arts
        else:
            notes = (d.get("configuration") or {}).get("notes") if isinstance(d.get("configuration"), dict) else []
            assert isinstance(notes, list)
            assert notes, "empty output_contracts must be accompanied by notes explaining draft status"

        # Ensure no secret values are embedded (only setting names).
        txt = p.read_text(encoding="utf-8").lower()
        assert "-----begin" not in txt
        assert "ghp_" not in txt
        assert "bearer " not in txt

