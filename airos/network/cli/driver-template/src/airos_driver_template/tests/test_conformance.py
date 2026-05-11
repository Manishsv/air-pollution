"""
Conformance test suite for AirOS drivers.

Copy this file into your driver's test directory and adjust the import.
Every driver package should ship this test — it is the minimum bar for
inclusion in the community driver catalogue.

Run with:
    pytest src/airos_driver_template/tests/test_conformance.py -v
"""
import pytest

from airos_driver_template.driver import TemplateDriver
from airos.os.sdk.driver_protocol import H3DataSourceDriver
from airos.os.sdk.driver_types import ConformanceResult


@pytest.fixture
def driver():
    return TemplateDriver()


class TestProtocol:
    """Verify the driver satisfies the H3DataSourceDriver Protocol."""

    def test_isinstance_protocol(self, driver):
        assert isinstance(driver, H3DataSourceDriver), (
            f"{type(driver).__name__} does not satisfy H3DataSourceDriver Protocol. "
            "Check that domain, cadence_hours, produces_assessments, fetch(), "
            "and conformance_check() are all defined."
        )

    def test_domain_is_nonempty_string(self, driver):
        assert isinstance(driver.domain, str) and driver.domain, \
            "domain must be a non-empty string"

    def test_domain_is_lowercase_no_spaces(self, driver):
        assert driver.domain == driver.domain.lower(), \
            f"domain {driver.domain!r} must be lowercase"
        assert " " not in driver.domain, \
            f"domain {driver.domain!r} must not contain spaces"

    def test_cadence_hours_positive(self, driver):
        assert isinstance(driver.cadence_hours, (int, float)), \
            "cadence_hours must be a number"
        assert driver.cadence_hours > 0, \
            "cadence_hours must be positive"

    def test_produces_assessments_is_bool(self, driver):
        assert isinstance(driver.produces_assessments, bool), \
            "produces_assessments must be a bool"

    def test_signal_names_includes_data_confidence(self, driver):
        assert "DATA_CONFIDENCE" in driver.signal_names, (
            "signal_names must include DATA_CONFIDENCE. "
            "Every driver must write DATA_CONFIDENCE for the conformance gate."
        )

    def test_data_sources_nonempty(self, driver):
        assert driver.data_sources, "data_sources must be a non-empty list"


class TestConformanceCheck:
    """Verify conformance_check() behaves correctly."""

    def test_conformance_check_returns_result(self, driver):
        result = driver.conformance_check()
        assert isinstance(result, ConformanceResult), \
            "conformance_check() must return a ConformanceResult"

    def test_conformance_check_is_fast(self, driver):
        """conformance_check must complete in under 2 seconds (no live API calls)."""
        import time
        start = time.monotonic()
        driver.conformance_check()
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, (
            f"conformance_check() took {elapsed:.2f}s — it must not make live API calls. "
            "Move any network calls to fetch()."
        )

    def test_conformance_check_returns_bool_ok(self, driver):
        result = driver.conformance_check()
        assert isinstance(result.ok, bool), "ConformanceResult.ok must be a bool"

    def test_conformance_failures_are_strings(self, driver):
        result = driver.conformance_check()
        assert all(isinstance(f, str) for f in result.failures), \
            "All ConformanceResult.failures must be strings"
