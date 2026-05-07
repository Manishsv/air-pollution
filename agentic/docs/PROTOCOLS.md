# Interaction Protocols — agentic framework

Three protocols govern all interactions between agents and between agents
and humans. Every agent must know all three. No agent proceeds past a
protocol boundary without satisfying its conditions.

---

## Protocol 1 — Task Handoff

**When:** Before any agent begins work.

**Purpose:** Ensure the task is well-formed, the working tree is clean,
and all preconditions are met before an agent consumes context or produces output.

**Steps:**

1. Loop reads `tasks.yaml` and finds the first task with `status: ready`.
2. Loop validates the task against `schemas/task.schema.yaml`. If invalid:
   - Write an escalation with `raised_by: loop`, `stop_condition: schema_invalid`.
   - Stop. Do not invoke any agent.
3. Loop checks `git status`. If dirty files exist:
   - Write an escalation with `raised_by: loop`, `stop_condition: dirty_tree`.
   - Stop.
4. Loop checks `depends_on` tasks are all `status: done`. If not:
   - Write an escalation with `raised_by: loop`, `stop_condition: dependency_not_done`.
   - Stop.
5. Loop sets task `status: in_progress`.
6. Loop builds the agent prompt from:
   - The agent role definition (`agents/roles/{owner_agent}.md`)
   - The task record (serialised YAML)
   - Context files (from `config.yaml` by task type + `context_hint`)
7. Loop invokes the agent.

**Agent contract during execution:**

- The agent may only modify files in `allowed_files`.
- The agent must not take any `forbidden_actions`.
- If the agent encounters an `escalation_condition`, it writes an escalation
  record and stops immediately. It does not attempt to resolve the condition.
- When done, the agent writes a task completion record including:
  `files_changed`, `verification_output`, `commit_hash` (if committed), `notes`.

---

## Protocol 2 — Review

**When:** After the implementation agent reports completion.

**Purpose:** Independent check that success criteria were met and no
out-of-scope changes occurred.

**Steps:**

1. Loop reads the task completion record.
2. Loop invokes the QA agent with:
   - The task definition
   - The git diff (HEAD before vs HEAD after)
   - The task completion record
   - The verification output
3. QA agent produces a review record (`schemas/review.schema.yaml`).
4. QA agent checks every success criterion. No criterion may be skipped
   without a note. If any criterion cannot be checked automatically,
   the outcome is `needs_human_decision`.
5. QA agent checks `diff_files_outside_allowed`. Any file in the diff
   not in `allowed_files` is an automatic `fail`.
6. Loop reads the review `outcome` and routes:

| Outcome | Loop action |
|---|---|
| `approved` | Advance task to `status: done`. Load next task. |
| `rejected` | Write escalation with review as context. Stop. |
| `needs_human_decision` | Write decision record. Stop. Dashboard presents to human. |

**What the QA agent must not do:**

- Suggest fixes or improvements to the implementation.
- Modify any file.
- Re-run tests independently (it reads the reported output).
- Override a `fail` result because the issue "seems minor."

---

## Protocol 3 — Escalation

**When:** Any agent hits a stop condition it cannot resolve, or the loop
hits a pre-flight failure.

**Purpose:** Surface the problem to the human with enough context to make
a decision, without the agent guessing or proceeding past uncertainty.

**Steps:**

1. Agent (or loop) writes an escalation record (`schemas/escalation.schema.yaml`).
   - `stop_condition`: the specific condition from the task, verbatim.
   - `context`: factual description of what was found. No recommendations here.
   - `options`: 2–4 concrete choices, each with a consequence.
   - `recommendation`: the agent's suggestion with one-sentence rationale.
   - `status: pending_human_decision`
2. Agent stops. It does not continue or attempt the next step.
3. Task `status` is set to `blocked`.
4. Dashboard presents the escalation to the human.
5. Human selects an option (or writes their own resolution).
6. Human sets escalation `status: resolved` with `resolution` text.
7. Loop resumes based on the resolution:
   - If the resolution is "proceed with modification": loop updates the task
     and re-invokes the implementation agent.
   - If the resolution is "defer this task": loop sets task `status: deferred`
     and loads the next ready task.
   - If the resolution is "new decision needed": loop writes a decision record.

**Escalation must not be used for:**

- Stylistic uncertainty ("I wasn't sure which approach looks better").
- Recoverable errors that the agent has already resolved.
- Asking the human to review output quality (that is the QA agent's job).

Escalation is for genuine stop conditions: ambiguous scope, missing
permissions, governance uncertainty, or irrecoverable failures.

---

## Protocol 4 — Human Decision

**When:** The task queue is empty, an escalation resolves to a strategic
choice, or the loop encounters a situation requiring human direction.

**Purpose:** Give the human a structured, low-friction way to steer the
loop without having to read the full tracker.

**Steps:**

1. Loop (or escalation resolution) writes a decision record
   (`schemas/decision.schema.yaml`) with `status: pending`.
2. Dashboard presents the decision: question, options, recommendation,
   consequence of each option, urgency signals.
3. Human selects an option.
4. Dashboard writes back:
   - `status: resolved`
   - `chosen_option`: the selected label
   - `resolved_at`: timestamp
5. Loop reads the resolved decision and acts:
   - Creates or activates the appropriate task in `tasks.yaml`.
   - Sets task `status: ready`.
   - Runs the next loop iteration.

**Multiple open decisions:**

If more than one decision is pending, the dashboard presents them in order
of `impact_if_delayed`. The human resolves them one at a time. The loop
does not resume until all blocking decisions are resolved.

---

## Protocol interactions

```
Loop preflight
  → Task Handoff Protocol
      → Implementation Agent
          → Escalation Protocol (if stop condition)
          → Task Completion Record
      → Review Protocol
          → QA Agent
              → Escalation Protocol (if cannot determine)
              → Review Record (approved / rejected / needs_human_decision)
      → Human Decision Protocol (if needs_human_decision or queue empty)
          → Dashboard
          → Decision resolved
      → Next task
```

---

## Invariants

These hold across all protocols and all agents:

1. **No agent proceeds past a stop condition.** If an escalation condition
   is hit, the agent writes the escalation and stops. Always.

2. **No state lives only in agent memory.** Every decision, review, and
   escalation is a file in the repo. The loop can be restarted from any
   point using the state files alone.

3. **The QA agent does not implement.** It produces one record with one
   outcome. It does not modify files, suggest code, or negotiate with the
   implementation agent.

4. **Human decisions are written back structurally.** The human does not
   inject direction through free-text chat. They choose from options in the
   decision record and that choice propagates deterministically into the
   next task.

5. **The loop does not create momentum without governance.** If the queue
   is empty or all ready tasks are blocked, the loop stops and writes a
   decision record. It does not invent new tasks.
