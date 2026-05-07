# agentic

A lightweight, protocol-driven framework for multi-agent software development.
Coordinates AI agents (currently Claude Code) through explicit interaction
contracts rather than hidden chat state. Designed to be adopted by any project
with minimal coupling.

## Core idea

Agents are governed by three interaction protocols:

- **Task handoff** — a well-formed task definition the loop validates before
  any agent starts work
- **Review** — a structured QA record produced after implementation; the only
  valid outcomes are `approved`, `rejected`, `needs_human_decision`
- **Escalation** — a stop-condition record written when an agent cannot
  continue; it waits for a human decision before the loop resumes

All coordination goes through files in the repo. No agent state lives in
chat context alone.

## Adopting for a new project

1. Copy or submodule this folder into your repo root as `agentic/`
2. Create `.agent-loop/config.yaml` — point it at your project's files
3. Write role definitions in `agents/roles/` using the templates in
   `agentic/roles/templates/`
4. Write your first task in `.agent-loop/state/tasks.yaml` using the schema
   in `agentic/schemas/task.schema.yaml`
5. Run `python agentic/core/loop.py`

See `agentic/docs/SETUP.md` for a full walkthrough.

## Folder layout

```
agentic/
  schemas/          Canonical schemas for all interaction artifacts
  core/             Loop, QA agent, dashboard, validation (to be built in Phase 2)
  roles/templates/  Role definition templates with project-specific placeholders
  docs/             Protocol reference and setup guide
```

## What lives outside this folder (project-specific)

```
.agent-loop/
  config.yaml       Project configuration — points framework at your files
  state/
    tasks.yaml      Current task queue
    reviews.yaml    QA review records
    escalations.yaml  Open stop conditions
    decisions.yaml  Human decisions (pending and resolved)

agents/
  roles/            Project-specific role definitions (override templates)
```

## Status

Phase 0 — schemas and protocols defined.
Phase 1 — task validation script.
Phase 2 — loop, QA agent, dashboard.

See the project's `docs/EXECUTION_TRACKER.md` for current implementation status.
