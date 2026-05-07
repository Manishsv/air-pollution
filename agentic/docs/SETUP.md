# Setup Guide — agentic framework

How to wire the agentic framework into a new project.

---

## Prerequisites

- Python 3.9+
- Claude Code CLI installed (`claude --version`)
- `pyyaml` and `jsonschema` available (`pip install pyyaml jsonschema`)
- A git repository

---

## Step 1 — Add the framework

Copy or submodule this folder into your repo root:

```bash
# Copy
cp -r /path/to/agentic ./agentic

# Or submodule (once extracted to its own repo)
git submodule add https://github.com/you/agentic agentic
```

---

## Step 2 — Create the state directory

```bash
mkdir -p .agent-loop/state
```

Add to `.gitignore` (runtime state only, not schemas or config):
```
# Keep config and schemas; ignore runtime state
.agent-loop/state/
```

Or commit state if you want a full audit trail of agent decisions.
For most projects, committing `tasks.yaml` and ignoring the others
is a reasonable default.

---

## Step 3 — Write your project config

Create `.agent-loop/config.yaml`:

```yaml
project_name: YourProject
project_root: .
agents_dir: agents/roles
state_dir: .agent-loop/state

context:
  always_include:
    - RULES.md              # Your project's agent rules
    - TRACKER.md            # Your execution tracker
  by_task_type:
    docs_edit: []
    code_edit:
      - YOUR_SPEC_FILE.md
    spec_edit:
      - YOUR_SPEC_FILE.md

verification:
  commands:
    - pytest -q
    - your-conformance-check
  baseline:
    pytest_passed: 0        # Update after first green run

claude:
  timeout_seconds: 600
  max_retries: 2
```

---

## Step 4 — Write role definitions

Create `agents/roles/` and write two files using the templates in
`agentic/roles/templates/`:

```bash
cp agentic/roles/templates/implementation_agent.md agents/roles/implementation_agent.md
cp agentic/roles/templates/qa_agent.md agents/roles/qa_agent.md
```

Edit each file to replace the `{{placeholders}}` with your project's:
- Rules (the equivalent of your `RULES.md`)
- Verification commands
- Forbidden actions specific to your domain
- Success criteria checklist items specific to your project

---

## Step 5 — Write your first task

Create `.agent-loop/state/tasks.yaml`:

```yaml
tasks:
  - task_id: my-first-task
    type: docs_edit
    scope_description: "Add a README section explaining the project structure."
    allowed_files:
      - README.md
      - TRACKER.md
    forbidden_actions:
      - modify runtime code
      - commit without verification
    success_criteria:
      - README.md has a new section titled 'Project structure'
      - TRACKER.md updated with this task as done
    escalation_conditions:
      - success criteria are ambiguous
      - allowed files are insufficient
    status: ready
```

Validate it:

```bash
python agentic/core/validate.py
# → Task my-first-task: valid
```

---

## Step 6 — Run the loop (Phase 2, once core/ is implemented)

```bash
python agentic/core/loop.py
```

The loop will:
1. Validate the current task
2. Invoke the implementation agent (Claude Code)
3. Invoke the QA agent
4. Write a review record
5. Advance the queue or write an escalation

---

## Step 7 — Use the dashboard for human decisions

```bash
python agentic/core/dashboard.py
```

The dashboard shows open escalations and decisions. You type a choice
and it writes back to `decisions.yaml`. The next loop iteration picks it up.

---

## File ownership summary

| File | Owner | Notes |
|---|---|---|
| `agentic/` | Framework | Do not edit project-specific content here |
| `.agent-loop/config.yaml` | Project | One per project |
| `.agent-loop/state/tasks.yaml` | Project | Commit this |
| `.agent-loop/state/reviews.yaml` | Loop (written) | Optional commit |
| `.agent-loop/state/escalations.yaml` | Loop (written) | Commit for audit trail |
| `.agent-loop/state/decisions.yaml` | Human + Loop | Commit this |
| `agents/roles/` | Project | Project-specific role definitions |

---

## Validation reference

```bash
# Validate all tasks against schema
python agentic/core/validate.py

# Validate a single task
python agentic/core/validate.py --task my-first-task

# Validate a review record
python agentic/core/validate.py --review review-my-first-task-20260507

# Check project config
python agentic/core/validate.py --config
```

---

## Troubleshooting

**Loop stops with `schema_invalid`**
Run `python agentic/core/validate.py` and fix the reported fields.

**Loop stops with `dirty_tree`**
Commit or stash uncommitted changes before running the loop.

**QA agent returns `needs_human_decision`**
Run `python agentic/core/dashboard.py` and resolve the pending decision.

**Claude Code times out**
Increase `claude.timeout_seconds` in `config.yaml` or narrow the task scope.
