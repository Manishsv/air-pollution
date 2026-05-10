# AirOS Apps — Specification Index

The Apps component is the decision support layer. An App reads from the Knowledge Store, reasons across signals and assessments, and produces structured, human-reviewed outputs.

| Document | What it specifies |
|----------|------------------|
| [APP_CONTRACT.md](APP_CONTRACT.md) | Read contract, write contract, temporal context requirements, insight quality requirements, safety posture, App Descriptor requirement, outcome tracking |
| [INSIGHT_SCHEMA.md](INSIGHT_SCHEMA.md) | Insight row structure, `HypothesisItem`, `RecommendedAction`, `UncertaintyNote`, outcome lifecycle, agent identity |

**Reading order for a new App author:**
1. APP_CONTRACT.md — understand what you can read, what you can write, and what safety rules you must follow
2. INSIGHT_SCHEMA.md — understand the exact shape of the insights you must produce
3. [`../core/KNOWLEDGE_STORE.md`](../core/KNOWLEDGE_STORE.md) — understand the read interface you'll use

| [AGENT_INTERFACE.md](AGENT_INTERFACE.md) | Formal contract for LLM-backed agents: context assembly, tool set, system prompt requirements, output schema, conformance |

| [REVIEW_CONTRACT.md](REVIEW_CONTRACT.md) | Review interface requirements: inbox sort and filters, evidence panel completeness, close actions, reviewer identity, re-open prohibition |
