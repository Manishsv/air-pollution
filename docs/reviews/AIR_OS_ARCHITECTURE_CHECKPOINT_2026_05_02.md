# AirOS architecture checkpoint — 2026-05-02

Institutional-memory review note (checkpoint after federation, CI, conformance, supervisor, and governance documentation evolution). Generated from the architecture checkpoint review.

After substantive repository changes, run `python -m pytest -q`, `python main.py --step conformance`, and `python tools/ai_dev_supervisor/run_review.py --run-conformance` before merge considerations.

---

## Key findings

- **Federation** is **documented** but **not yet implemented** (no runnable AirOS Network Layer; named future schemas are forward-looking).
- The **AirOS Network Layer** is **domain-agnostic**, **contract-aware**, and **policy-enforcing** (coordination semantics, not domain reasoning).
- **Email** is a plausible **Phase 1 transport adapter**, **not** the Network Layer itself; the **same logical message envelope** should port across transports later.
- **Air quality** still carries **`src/` → `urban_platform/` migration debt** (reference pipeline delegates to legacy modules while new domains align with platform layout).
- **Flood** and **property/buildings** have **stronger vertical-slice patterns** relative to maturity checklists and `urban_platform` alignment.

**Recommended next actions (preserve order):**

1. `message_envelope.v1` schema + example + manifest  
2. `agency_node` and `network_participant` templates  
3. `air_quality` domain checklist YAML + tests  

---

## 1. Current baseline — what is reasonably complete?

**Specs-first governance** — Spec families, manifests, conformance step, supervisor review, CI running tests + conformance; agent rules and playbook discipline are explicit.

**Urban context / AI CoE** — Institutional fragmentation, open-data-first, progressive municipal integration, forward deployment vs core, and tooling expectations are coherent across governance docs.

**Federated deployment docs** — Node-first posture is clear; separation of AirOS Core, agency nodes, and the contract-aware Network Layer is defined; envelope-level concerns vs forbidden domain semantics are documented; Phase 1 email-as-transport is scoped without equating transport with the Network Layer.

**Air quality reference** — Operational path exists (`urban_platform` entry → `src/` delegation documented); pipelines, models, dashboards, CI/test stability apply where exercised.

**Flood read-only slice** — Specs, examples, `urban_platform` stack, dashboard panel, and tests align; maturity YAML drives the supervisor.

**Property/buildings (open-data-first)** — Specs, open-data pathway, payloads, panels, tests, and maturity YAML are in place per the vertical slice.

**AI supervisor** — Conformance probing uses the active interpreter (`sys.executable`); domain maturity is YAML-driven (`domain_checklists/*.yaml`) with sane unknown-domain behavior.

**CI / conformance** — Install path uses `python -m pip` for toolchain alignment with test interpreter; refreshed Actions majors; conformance check count reflects current manifest/policy.

**Dashboard** — Review-oriented Streamlit structure exists; domains follow documented SDK/application payload patterns (exact UX not exhaustively audited in this checkpoint).

**Code layout** — `urban_platform/` vs `src/` roles and AQ migration sequencing are documented (`specifications/ARCHITECTURE_NOTE.md`, playbook).

---

## 2. Remaining architectural gaps — before scaling domains / deployments

- **Federation is narrative-focused:** no wired manifest artifacts for envelopes, receipts, participants, or jurisdiction catalogs—risk of ad hoc cross-agency code or endpoints ahead of specs.
- **Profile depth vs docs:** city profile templating exists; agency / jurisdiction / network participant profiles are mainly described textually—not yet symmetric copy-and-use template trees everywhere for forward deployment.
- **AQ/strategic debt:** AQ reference remains thick in `src/` while strategic direction favors `urban_platform/`—scaling without repeated migration spikes needs a persisted, bounded migration backlog.
- **Semantic vs structural conformance:** manifest/conformance attest structure strongly; richer blocked uses / gates remain partially “spec intent + selective tests”—acceptable if tracked as residual risk during multi-domain rollout.
- **Supervisory parity:** flood and property have maturity YAML; air quality does not mirror that pattern unless/until a checklist is added (onboarding asymmetry).

---

## 3. Implementation gaps — documented but not yet implemented

- **Executable AirOS Network Layer** (routing, policy hooks, retries, receipts) — intentionally absent.
- **Named federation-oriented JSON Schemas** (message envelope, `agency_node`, `network_participant`, jurisdiction registry, data sharing policy, delivery receipts, cross-agency events, task handoff, packet exchange, agency response status) — listed as future-facing; not landed as schemas in this checkpoint’s scope description.
- **Concrete transports:** email/API/bus/queues as adapters carrying one logical envelope — not implemented beyond documentation.
- **Reference topology manifests** — no machine-readable federation demo topology in repo beyond prose.

---

## 4. Recommended next 10 bounded tasks

| # | Title | Why it matters | Likely surfaces | Acceptance criteria | Type |
|---|--------|----------------|-----------------|----------------------|------|
| 1 | `air_quality` domain checklist YAML | Supervisor parity across all shipped/reference domains | `tools/ai_dev_supervisor/domain_checklists/`, tests | `--domain air_quality` works; checklist matches agreed path ladder; tests cover load; unknown-domain behavior unchanged | Tooling (+ tests) |
| 2 | `deployments/templates/agency_node/` stubs | Forward deployment copies agency context without improvising filenames | YAML placeholders + README | Placeholders only; aligns with `docs/AGENCY_NODE_MODEL.md` | Docs + templates |
| 3 | `deployments/templates/network_participant/` stubs | Same for federation enrollment planning | placeholders + README | Cross-links federation docs | Docs + templates |
| 4 | `message_envelope.v1.schema.json` + manifest registration | First concrete cross-node contract spine | `specifications/`, manifest, minimal `examples/` | `python main.py --step conformance` passes; JSON Schema validity | Specs (+ examples) |
| 5 | `delivery_receipt.v1` minimal schema + example | Paired acknowledgement story for transports | specs + manifest + examples | Conformance passes | Specs |
| 6 | `deployments/templates/jurisdiction_refs/` README stub | Avoid free-text chaos in envelope jurisdiction fields later | README + placeholder fields | Describes ID strategy; no GIS dumps in public repos | Docs + templates |
| 7 | Conformance linkage for envelope/receipt once specs land | Prevents orphaned federation registrations | conformance Python/tests | Explicit pass/fail when manifest violates agreed registration rules | Tooling/conformance |
| 8 | Bounded AQ migration shim (one submodule) | Reduces dual-home confusion without big bang | `urban_platform/` re-export + thinning `src/` | Existing external behavior unchanged under tests | Application |
| 9 | Playbook or roadmap appendix: ordered first-wave federation schema rollout | Aligns stakeholders before implementations multiply | playbook or roadmap subsection | Canonical order documented (envelope→receipt→participant→…) | Docs-only |
| 10 | Warnings/process triage (pandas/jsonschema/RefResolver deprecation) — decision recorded | Reduces silent CI breakage | issue or narrow policy | Decision documented; regressions attributable | Tooling/process |

---

## 5. Top 3 next actions — execute first

1. **`message_envelope.v1` (+ minimal valid example + manifest + conformance)** — anchors transports without prematurely coding the Network Layer.  
2. **`agency_node` + `network_participant` template directories** — makes forward deployment scaffolding match federation docs immediately.  
3. **`domain_checklists/air_quality.yaml` + tests** — completes supervisor symmetry and reduces AQ-as-exception confusion during migration.

---

## Cross-references

- Federation: `docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`, `docs/AGENCY_NODE_MODEL.md`, `docs/CROSS_AGENCY_COORDINATION_LAYER.md`
- Earlier consolidated review (same era): `docs/reviews/AIR_OS_ARCHITECTURE_REVIEW_2026_05_02.md`
