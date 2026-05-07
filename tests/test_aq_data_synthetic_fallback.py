"""Tests for the provider_failure audit event emitted when synthetic fallback fires."""

import logging
from unittest.mock import MagicMock, call

import pytest
from shapely.geometry import box

from urban_platform.applications.air_pollution.aq_data import generate_synthetic_station_pm25
from urban_platform.storage.models import AuditEvent

# Small bounding box around a corner of San Francisco
_POLY = box(-122.5, 37.7, -122.4, 37.8)


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_store():
    """Return a mock store that records appended audit events."""
    store = MagicMock()
    store.append_audit_event.return_value = None
    return store


def _run(store=None, connector_id="openaq", deployment_id="", **kwargs):
    return generate_synthetic_station_pm25(
        boundary_wgs84_polygon=_POLY,
        lookback_days=2,
        n_stations=3,
        connector_id=connector_id,
        deployment_id=deployment_id,
        store=store,
        **kwargs,
    )


# ── DataFrame output unchanged ─────────────────────────────────────────────

class TestSyntheticOutput:
    def test_returns_dataframe_with_expected_columns(self):
        df = _run()
        assert set(["station_id", "station_name", "latitude", "longitude",
                     "timestamp", "pm25", "data_source"]).issubset(df.columns)

    def test_data_source_is_synthetic(self):
        df = _run()
        assert (df["data_source"] == "synthetic").all()

    def test_row_count(self):
        df = _run()
        # 3 stations × (2 days × 24 hours + 1 hour endpoint) = 3 × 49
        assert len(df) == 3 * 49

    def test_deterministic_with_same_seed(self):
        df1 = _run(seed=7)
        df2 = _run(seed=7)
        assert df1["pm25"].tolist() == df2["pm25"].tolist()


# ── ERROR logging ──────────────────────────────────────────────────────────

class TestErrorLogging:
    def test_logs_at_error_level(self, caplog):
        with caplog.at_level(logging.ERROR, logger="urban_platform.applications.air_pollution.aq_data"):
            _run()
        assert any(r.levelno == logging.ERROR for r in caplog.records)

    def test_log_message_contains_connector_id(self, caplog):
        with caplog.at_level(logging.ERROR, logger="urban_platform.applications.air_pollution.aq_data"):
            _run(connector_id="custom_connector")
        assert any("custom_connector" in r.message for r in caplog.records)

    def test_log_message_mentions_provider_failure(self, caplog):
        with caplog.at_level(logging.ERROR, logger="urban_platform.applications.air_pollution.aq_data"):
            _run()
        assert any("PROVIDER FAILURE" in r.message or "provider_failure" in r.message.lower()
                   for r in caplog.records)

    def test_no_store_still_logs(self, caplog):
        with caplog.at_level(logging.ERROR, logger="urban_platform.applications.air_pollution.aq_data"):
            _run(store=None)
        assert len([r for r in caplog.records if r.levelno == logging.ERROR]) >= 1


# ── Audit event written to store ───────────────────────────────────────────

class TestAuditEvent:
    def test_store_append_called_once(self):
        store = _make_store()
        _run(store=store)
        store.append_audit_event.assert_called_once()

    def test_audit_event_is_AuditEvent_instance(self):
        store = _make_store()
        _run(store=store)
        event = store.append_audit_event.call_args[0][0]
        assert isinstance(event, AuditEvent)

    def test_audit_event_action_is_provider_failure(self):
        store = _make_store()
        _run(store=store)
        event = store.append_audit_event.call_args[0][0]
        assert event.action == "provider_failure"

    def test_audit_event_actor_is_aq_data(self):
        store = _make_store()
        _run(store=store)
        event = store.append_audit_event.call_args[0][0]
        assert event.actor == "aq_data"

    def test_audit_event_connector_id_in_metadata(self):
        store = _make_store()
        _run(store=store, connector_id="my_connector")
        event = store.append_audit_event.call_args[0][0]
        assert event.metadata["connector_id"] == "my_connector"
        assert event.resource_id == "my_connector"

    def test_audit_event_reason_in_metadata(self):
        store = _make_store()
        _run(store=store)
        event = store.append_audit_event.call_args[0][0]
        assert "reason" in event.metadata
        assert event.metadata["reason"]

    def test_audit_event_timestamp_in_metadata(self):
        store = _make_store()
        _run(store=store)
        event = store.append_audit_event.call_args[0][0]
        assert "timestamp" in event.metadata
        assert event.metadata["timestamp"]

    def test_audit_event_deployment_id_passed_through(self):
        store = _make_store()
        _run(store=store, deployment_id="dep_abc")
        event = store.append_audit_event.call_args[0][0]
        assert event.deployment_id == "dep_abc"

    def test_audit_event_has_unique_event_id(self):
        store = _make_store()
        _run(store=store)
        _run(store=store)
        ids = [c[0][0].event_id for c in store.append_audit_event.call_args_list]
        assert ids[0] != ids[1]

    def test_no_audit_event_when_store_is_none(self):
        # Baseline: no exception raised, no store interaction
        df = _run(store=None)
        assert not df.empty  # function still returns data

    def test_store_failure_does_not_raise(self):
        store = _make_store()
        store.append_audit_event.side_effect = RuntimeError("store down")
        # Should not propagate — pipeline must continue even if audit write fails
        df = _run(store=store)
        assert not df.empty
