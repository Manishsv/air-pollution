from __future__ import annotations

from urban_platform.sdk import (
    get_provider_adapter_descriptor,
    list_provider_adapter_descriptors,
    list_provider_adapter_ids,
)


def test_sdk_adapter_list_includes_openaq() -> None:
    ids = list_provider_adapter_ids()
    assert "openaq_air_quality_adapter" in ids


def test_sdk_adapter_get_returns_descriptor() -> None:
    d = get_provider_adapter_descriptor("openaq_air_quality_adapter")
    assert isinstance(d, dict)
    assert d.get("adapter_id") == "openaq_air_quality_adapter"
    assert d.get("source_system_type") == "air_quality_feed"


def test_sdk_unknown_adapter_returns_none() -> None:
    assert get_provider_adapter_descriptor("does_not_exist") is None


def test_sdk_adapters_do_not_expose_absolute_paths() -> None:
    desc = list_provider_adapter_descriptors()
    for d in desc:
        # descriptors should not contain absolute paths
        txt = str(d)
        assert "/Users/" not in txt
        assert "C:\\" not in txt

