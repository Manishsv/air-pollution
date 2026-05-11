## AirOS AI Dev Supervisor — Local Review

- **timestamp**: `2026-05-07T01:00:21.561217+00:00`

### Specs-first policy status
- **policy_file**: `specifications/spec_policy.yaml`
- **specs_first**: **PASS**

### Expected folders status
- **specifications/provider_contracts**: PASS
- **specifications/platform_objects**: PASS
- **specifications/domain_specs**: PASS
- **specifications/consumer_contracts**: PASS
- **specifications/network_contracts**: PASS
- **specifications/registry_contracts**: PASS

### README/AGENTS governance status
- **README.md exists**: PASS
- **README mentions specs-first/docs**: **PASS**
- **AGENTS.md exists**: PASS
- **AGENTS mentions specs-first rules**: **PASS**

### Conformance status (if available)
- **attempted**: `True`
- **exit_code**: `0`
- **duration_s**: `2.757`
- **report_path**: `data/outputs/conformance_report.json`
- **report_loaded**: `True`

### Registry hygiene
- **provider_count**: `6`
- **application_count**: `3`
- **adapter_count**: `3`
- **missing_manifest_references**: `0`
- **missing_example_references**: `0`
- **recommended_next_task**:
  - Keep registries aligned with manifest artifacts and examples; add registry validation to CI if needed.

### Deployment examples
- **examples_dir_exists**: `True`
- **example_count**: `2`
- **deployment**: `flood_local_demo` (`deployments/examples/flood_local_demo`)
  - **deployment_id**: `flood_local_demo`
  - **files**: profile=True provider_registry=True application_registry=True readme=True
  - **provider_count**: `3`
  - **application_count**: `3`
  - **recommended_next_task**: Keep deployment examples aligned with manifest contracts and fixture paths.
- **deployment**: `program_reporting_state_demo` (`deployments/examples/program_reporting_state_demo`)
  - **deployment_id**: `program_reporting_state_demo`
  - **files**: profile=True provider_registry=True application_registry=True readme=True
  - **provider_count**: `0`
  - **application_count**: `1`
  - **recommended_next_task**: Keep deployment examples aligned with manifest contracts and fixture paths.
- **recommended_next_task**: Add another deployment example or extend checks (still read-only).

### Risks
- No material risks detected by lightweight checks.

### Recommended next task
- Add new provider/domain/consumer work only via specs-first sequence (update specs, then run conformance).
