"""
Tests for examples/sdk/program_reporting_walkthrough.py.

Imports and runs the walkthrough in read-only mode; asserts stable output shape.
No Core API required. No state mutations.
"""

import sys
import os
import pytest

# Allow importing from examples/sdk without installing it as a package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "examples", "sdk"))

from program_reporting_walkthrough import main


@pytest.fixture(scope="module")
def result():
    return main()


class TestInventory:
    def test_inventory_present(self, result):
        assert "inventory" in result

    def test_inventory_has_expected_sections(self, result):
        inv = result["inventory"]
        assert "contracts" in inv
        assert "apps" in inv
        assert "adapters" in inv
        assert "catalogs" in inv
        assert "deployments" in inv

    def test_contract_count_nonzero(self, result):
        assert result["inventory"]["contracts"]["contract_count"] > 0

    def test_app_count_at_least_one(self, result):
        assert result["inventory"]["apps"]["app_count"] >= 1


class TestAppDescriptor:
    def test_app_descriptor_present(self, result):
        assert "app" in result
        assert result["app"], "program_reporting_review descriptor must not be empty"

    def test_app_id(self, result):
        assert result["app"]["app_id"] == "program_reporting_review"

    def test_app_type_is_review_support(self, result):
        assert result["app"]["app_type"] == "review_support"

    def test_input_contract_declared(self, result):
        assert "consumer_city_program_submission" in result["app"]["input_contracts"]

    def test_output_contracts_declared(self, result):
        outputs = result["app"]["output_contracts"]
        assert "consumer_fund_release_review_packet" in outputs
        assert "consumer_program_reporting_state_summary" in outputs

    def test_safety_gates_set(self, result):
        safety = result["app"]["safety"]
        assert safety["review_support_only"] is True
        assert safety["human_review_required"] is True

    def test_automatic_fund_release_is_blocked(self, result):
        blocked = result["app"]["safety"]["blocked_uses"]
        assert "automatic_fund_release" in blocked


class TestContracts:
    def test_contracts_present(self, result):
        assert "contracts" in result

    def test_fixture_validates_clean(self, result):
        assert result["contracts"]["valid"] is True
        assert result["contracts"]["error_count"] == 0


class TestDeployment:
    def test_deployment_present(self, result):
        assert "deployment" in result

    def test_deployment_id(self, result):
        assert result["deployment"]["deployment_id"] == "program_reporting_state_demo"

    def test_deployment_domain(self, result):
        assert "program_reporting" in result["deployment"]["enabled_domains"]

    def test_environment_is_local(self, result):
        raw = result["deployment"].get("deployment_profile", {})
        assert raw.get("environment") == "local"

    def test_application_count_nonzero(self, result):
        assert result["deployment"]["application_count"] >= 1
