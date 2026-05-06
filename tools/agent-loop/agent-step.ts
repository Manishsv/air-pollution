import OpenAI from "openai";
import fs from "fs/promises";
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

const STATE_PATH = ".agent-loop/state.json";
const NEXT_INSTRUCTION_PATH = ".agent-loop/next-cursor-instruction.md";
const LAST_CURSOR_RESULT_PATH = ".agent-loop/last-cursor-result.md";
const RAW_OPENAI_RESPONSE_PATH = ".agent-loop/raw-openai-response.json";
const EXECUTION_TRACKER_PATH = "docs/EXECUTION_TRACKER.md";

const DEFAULT_MODEL = process.env.OPENAI_MODEL || "gpt-4.1";
const MAX_BUFFER_BYTES = 1024 * 1024 * 20;

type State = {
  previousResponseId?: string;
  iteration: number;
};

type RepoSnapshot = {
  status: string;
  diffStat: string;
};

type AgentTaskMode = "implementation" | "docs" | "audit" | "question";

type GitChangeSummary = {
  changedFiles: string[];
  trackerChanged: boolean;
  hasRepoChanges: boolean;
};

type TrackerValidationOptions = {
  beforeChangedFiles?: string[];
};

type PlanGateResult = {
  ok: boolean;
  reason?: string;
  currentNextTask?: string;
};

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set`);
  }
  return value;
}

async function readFileSafe(path: string): Promise<string> {
  try {
    return await fs.readFile(path, "utf8");
  } catch {
    return "";
  }
}

async function writeFileEnsuringDir(path: string, content: string): Promise<void> {
  await fs.mkdir(".agent-loop", { recursive: true });
  await fs.writeFile(path, content);
}

async function loadState(): Promise<State> {
  try {
    return JSON.parse(await fs.readFile(STATE_PATH, "utf8"));
  } catch {
    return { iteration: 0 };
  }
}

async function saveState(state: State): Promise<void> {
  await fs.mkdir(".agent-loop", { recursive: true });
  await fs.writeFile(STATE_PATH, JSON.stringify(state, null, 2));
}

async function runCommand(command: string, args: string[]): Promise<string> {
  try {
    const result = await execFileAsync(command, args, {
      maxBuffer: MAX_BUFFER_BYTES,
    });
    return result.stdout.trim();
  } catch (error: any) {
    const output = [error?.stdout, error?.stderr, error?.message]
      .filter(Boolean)
      .join("\n")
      .trim();
    return output || String(error);
  }
}

async function fileExists(path: string): Promise<boolean> {
  try {
    await fs.access(path);
    return true;
  } catch {
    return false;
  }
}

async function getRepoSnapshot(): Promise<RepoSnapshot> {
  const [status, diffStat] = await Promise.all([
    runCommand("git", ["status", "--short", "--branch"]),
    runCommand("git", ["diff", "--stat"]),
  ]);

  return { status, diffStat };
}

function extractCurrentNextTask(trackerText: string): string | undefined {
  const lines = trackerText.split("\n");

  for (const line of lines) {
    const match = line.match(
      /^\s*(?:[-*]\s*)?(?:\*\*)?Current next task(?:\*\*)?\s*:\s*(.*)$/i
    );
    if (match) {
      return match[1].trim().replace(/^`|`$/g, "");
    }
  }

  return undefined;
}

function evaluateExecutionTracker(trackerText: string): PlanGateResult {
  const trimmed = trackerText.trim();

  if (!trimmed) {
    return { ok: true };
  }

  const currentNextTask = extractCurrentNextTask(trackerText);

  if (trackerText.match(/Requires human decision\s*:\s*yes/i)) {
    return {
      ok: false,
      reason:
        "Execution tracker says the current plan requires a human decision.",
      currentNextTask,
    };
  }

  if (trackerText.match(/Plan change required\s*:\s*yes/i)) {
    return {
      ok: false,
      reason: "Execution tracker says the plan requires a human-approved change.",
      currentNextTask,
    };
  }

  if (currentNextTask === undefined) {
    return {
      ok: false,
      reason:
        "Execution tracker exists but does not declare a Current next task.",
    };
  }

  if (
    !currentNextTask ||
    /^(none|n\/a|na|not set|done|complete|completed|stop|no current task)$/i.test(
      currentNextTask
    )
  ) {
    return {
      ok: false,
      reason: "Execution tracker has no remaining current next task.",
      currentNextTask,
    };
  }

  if (
    /(blocked|deferred|design-only|needs human decision|human decision required|choose between|decide whether|needs decision)/i.test(
      currentNextTask
    )
  ) {
    return {
      ok: false,
      reason:
        "Execution tracker current next task is blocked, deferred, design-only, or requires a human choice.",
      currentNextTask,
    };
  }

  return { ok: true, currentNextTask };
}

function inferTaskModeFromText(text: string): AgentTaskMode {
  const lower = text.toLowerCase();
  const explicitMode = process.env.AGENT_TASK_MODE?.toLowerCase();

  if (
    explicitMode === "implementation" ||
    explicitMode === "docs" ||
    explicitMode === "audit" ||
    explicitMode === "question"
  ) {
    return explicitMode;
  }

  if (
    lower.includes("audit-only") ||
    lower.includes("audit / stabilization") ||
    lower.includes("verification-only") ||
    lower.includes("verification + push") ||
    lower.includes("verify and push") ||
    lower.includes("do not edit files") ||
    lower.includes("do not make changes") ||
    lower.includes("only report")
  ) {
    return "audit";
  }

  if (
    lower.includes("documentation-only") ||
    lower.includes("docs-only") ||
    lower.includes("update docs") ||
    lower.includes("documentation rationalization")
  ) {
    return "docs";
  }

  if (
    lower.includes("question-only") ||
    lower.includes("answer only") ||
    lower.includes("explain")
  ) {
    return "question";
  }

  return "implementation";
}

function shouldRequireTrackerUpdate(mode: AgentTaskMode): boolean {
  return mode === "implementation" || mode === "docs";
}

function isGeneratedOnly(files: string[]): boolean {
  return files.every(
    (file) =>
      file.startsWith("data/") ||
      file.startsWith(".agent-loop/") ||
      file.startsWith(".airos/") ||
      file.startsWith("dist/") ||
      file.startsWith("backups/") ||
      file.endsWith(".zip") ||
      file.endsWith(".redacted.zip") ||
      file.includes("__pycache__")
  );
}

function parseGitStatusPath(line: string): string | undefined {
  const trimmed = line.trim();
  if (!trimmed) {
    return undefined;
  }

  const path = trimmed.slice(3).trim();
  if (!path) {
    return undefined;
  }

  const renameArrow = " -> ";
  if (path.includes(renameArrow)) {
    return path.split(renameArrow).pop()?.trim();
  }

  return path;
}

function changedFilesIntroducedAfter(
  beforeChangedFiles: string[] | undefined,
  afterChangedFiles: string[]
): string[] {
  if (!beforeChangedFiles) {
    return afterChangedFiles;
  }

  const before = new Set(beforeChangedFiles);
  return afterChangedFiles.filter((file) => !before.has(file));
}

async function getGitChangeSummary(): Promise<GitChangeSummary> {
  const output = await runCommand("git", ["status", "--porcelain"]);
  const changedFiles = output
    .split("\n")
    .map(parseGitStatusPath)
    .filter((file): file is string => Boolean(file));

  return {
    changedFiles,
    trackerChanged: changedFiles.includes(EXECUTION_TRACKER_PATH),
    hasRepoChanges: changedFiles.length > 0,
  };
}

async function validateTrackerRule(
  mode: AgentTaskMode,
  options: TrackerValidationOptions = {}
): Promise<{ ok: boolean; message?: string }> {
  if (!shouldRequireTrackerUpdate(mode)) {
    return { ok: true };
  }

  if (!(await fileExists(EXECUTION_TRACKER_PATH))) {
    return {
      ok: false,
      message: `${EXECUTION_TRACKER_PATH} does not exist. Create it before enforcing tracker updates.`,
    };
  }

  const summary = await getGitChangeSummary();
  const relevantChangedFiles = changedFilesIntroducedAfter(
    options.beforeChangedFiles,
    summary.changedFiles
  );

  if (
    !summary.hasRepoChanges ||
    relevantChangedFiles.length === 0 ||
    isGeneratedOnly(relevantChangedFiles)
  ) {
    return { ok: true };
  }

  if (!summary.trackerChanged) {
    return {
      ok: false,
      message: `Repository files changed, but ${EXECUTION_TRACKER_PATH} was not updated. Relevant changed files: ${relevantChangedFiles.join(", ")}`,
    };
  }

  return { ok: true };
}

function buildTrackerRepairPrompt(originalTask: string, cursorResult: string): string {
  return `
You changed repository files for the AirOS task but did not update ${EXECUTION_TRACKER_PATH}.

Original task:
${originalTask}

Cursor result from the task:
${cursorResult}

Repair task:
Update ${EXECUTION_TRACKER_PATH} only.

Include:
- task name
- status
- files changed
- documentation sync status
- verification result from the task report
- commit hash if committed, otherwise "not committed"
- push status if pushed, otherwise "not pushed"
- current next task before this task
- current next task after this task
- blockers or drift

Do not change runtime code.
Do not change schemas.
Do not change tests.
Do not modify any file except ${EXECUTION_TRACKER_PATH}.

After updating, run:
git status

Report the tracker section changed and final git status.
`;
}

function buildAirOSStandingInstructions(mode: AgentTaskMode): string {
  const trackerRule = shouldRequireTrackerUpdate(mode)
    ? `
Tracker rule:
- Because this task may change repository files, you must update ${EXECUTION_TRACKER_PATH} before reporting back.
- The tracker update must include:
  - task name
  - status
  - files changed
  - documentation sync status
  - verification result
  - commit hash if committed
  - push status if pushed
  - current next task
  - blockers or drift
- Do not mark a task Done unless pytest, conformance, and supervisor conformance pass.
- Include the tracker update in the same change set as the task.
`
    : `
Tracker rule:
- This is audit-only/question-only unless explicitly stated otherwise.
- Do not update ${EXECUTION_TRACKER_PATH} unless asked, or unless this task completes or advances the tracker current next task.
- If this task completes the tracker current next task through verification, commit, push, or a human-decision answer, make a tracker-only update to record that progress and set the next task.
`;

  return `
AirOS standing rules:
- One task at a time.
- Do not add broad new features.
- Do not weaken safety/governance warnings.
- Do not introduce dynamic plugin loading.
- Do not execute untrusted app/adapter code from descriptors or packages.
- Do not commit generated runtime artifacts.
- Do not create or use a top-level src/ directory.
- Follow the repository's current structure, especially urban_platform/.
- Keep code, tests, docs, and tracker synchronized.
- If runtime behavior, API behavior, CLI behavior, SDK behavior, dashboard behavior, schemas, descriptors, or repo structure changes, update the relevant docs in the same task.
- If docs describe behavior that is not implemented, clearly mark it as pilot, design-only, future, or deferred.
- Do not leave implemented code undocumented when it affects users, developers, operators, or reviewers.
- Do not leave docs claiming features that are not implemented.
- Do not commit unless the Cursor task explicitly asks for a commit.
- Do not push unless the Cursor task explicitly asks for a push.
- If committing is requested, commit only after pytest, conformance, and supervisor conformance pass.
- If pushing is requested, push only after the working tree is clean and the local commit has been verified.
- Always report whether the branch is clean, ahead, behind, or synchronized with origin.
- Run verification when files change:
  python -m pytest -q
  python main.py --step conformance
  python tools/ai_dev_supervisor/run_review.py --run-conformance

Engineering behavior rules:
- Before changing files, restate the task as verifiable success criteria.
- State assumptions explicitly.
- If requirements are ambiguous, stop and ask or perform an audit-only step.
- Prefer the smallest change that satisfies the success criteria.
- Do not add abstractions, configuration, extensibility, or generalized frameworks unless explicitly requested.
- Do not refactor unrelated code.
- Do not improve nearby code opportunistically.
- If the change grows beyond expected scope, stop and report.
- Write or update tests for behavior changes.
- Verify before reporting completion.
${trackerRule}
`;
}

function buildPlannerPrompt(params: {
  handoff: string;
  cursorSummary: string;
  lastCursorResult: string;
  localVerification: string;
  executionTracker: string;
  repo: RepoSnapshot;
}): string {
  const {
    handoff,
    cursorSummary,
    lastCursorResult,
    localVerification,
    executionTracker,
    repo,
  } = params;

  return `
You are the planning and review agent for a coding workflow.

The repository may already have ongoing uncommitted work.

ChatGPT handoff context:
${handoff || "No handoff file found."}

Cursor current summary:
${cursorSummary || "No Cursor summary file found."}

Last Cursor result:
${lastCursorResult || "No previous orchestrated Cursor result."}

Local verification result:
${localVerification || "No local verification result found."}

Execution tracker:
${executionTracker || "No execution tracker found. If the task changes files, the next task should create or update docs/EXECUTION_TRACKER.md before feature work continues."}

Current git status:
${repo.status || "Clean working tree."}

Current git diff stat:
${repo.diffStat || "No diff."}

Generate the next Cursor instruction.

Rules:
- Give exactly one bounded task.
- Prefer inspection or stabilization if repo state is unclear.
- Preserve existing uncommitted work unless the task explicitly touches it.
- Treat docs/EXECUTION_TRACKER.md as the source of truth for the current plan and current next task.
- If the tracker has no current next task, says the plan is complete, is blocked, is deferred, or requires a human decision, do not generate implementation work.
- If there are two or more viable ways to do the task and the choice changes product direction, data model, safety posture, public API, repo structure, or migration plan, generate an audit/question task that asks the human to decide.
- Do not invent a new plan when the tracker says the plan is complete or needs human approval.
- If the working tree is dirty, prefer review, stabilization, or commit-preparation tasks before new feature work.
- If the branch is ahead of origin and the working tree is clean, prefer verification and push tasks before new feature work.
- If code changed without corresponding docs/status/tracker updates, ask Cursor to correct that synchronization gap.
- If docs changed without verification, ask Cursor to run verification before commit/push.
- Do not ask for broad refactors.
- Do not introduce new dependencies unless explicitly justified.
- Do not create or use a top-level src/ directory.
- Follow the repository's current structure, especially urban_platform/.
- Require tests, conformance, build, or typecheck where possible.
- If Cursor may not be able to run shell commands, instruct it to report rejected commands clearly.
- Require Cursor to return a structured execution summary.
- Require Cursor to report documentation synchronization: which docs were updated or why no docs were needed.
- Require Cursor to report GitHub synchronization: clean/dirty, ahead/behind, committed/uncommitted, pushed/not pushed.
- Require Cursor to state success criteria, assumptions, and scope-control decisions.
- Classify the task as implementation, docs, audit, or question.
- For implementation/docs tasks, require Cursor to update ${EXECUTION_TRACKER_PATH}.
- For audit/question tasks, require Cursor not to update ${EXECUTION_TRACKER_PATH} unless explicitly asked or unless the task completes/advances the tracker current next task.
- If the task verifies, commits, pushes, or otherwise completes the tracker current next task, allow a tracker-only update so the plan can advance.
- Do not generate instructions that both complete a tracker task and forbid updating the tracker.

Return only the Cursor instruction.
`;
}

async function generateCursorInstruction(
  openai: OpenAI,
  state: State
): Promise<string> {
  const handoff = await readFileSafe(".agent-loop/chatgpt-handoff.md");
  const cursorSummary = await readFileSafe(".agent-loop/cursor-current-summary.md");
  const lastCursorResult = await readFileSafe(LAST_CURSOR_RESULT_PATH);
  const localVerification = await readFileSafe(
    ".agent-loop/local-verification-result.md"
  );
  const executionTracker = await readFileSafe(EXECUTION_TRACKER_PATH);
  const repo = await getRepoSnapshot();

  console.log(`Calling OpenAI planner with model: ${DEFAULT_MODEL}`);

  const response = await openai.responses.create({
    model: DEFAULT_MODEL,
    previous_response_id: state.previousResponseId,
    input: buildPlannerPrompt({
      handoff,
      cursorSummary,
      lastCursorResult,
      localVerification,
      executionTracker,
      repo,
    }),
  });

  const outputText = response.output_text?.trim();

  if (!outputText) {
    await writeFileEnsuringDir(
      RAW_OPENAI_RESPONSE_PATH,
      JSON.stringify(response, null, 2)
    );
    throw new Error(
      `OpenAI response did not contain output_text. Raw response saved to ${RAW_OPENAI_RESPONSE_PATH}`
    );
  }

  state.previousResponseId = response.id;
  await saveState(state);

  return outputText;
}

function buildCursorInstructionWithStandingRules(instruction: string): {
  instruction: string;
  mode: AgentTaskMode;
} {
  const mode = inferTaskModeFromText(instruction);
  const standingRules = buildAirOSStandingInstructions(mode);

  return {
    mode,
    instruction: `${standingRules}\n\nCursor task:\n${instruction}\n\nReport back using this format:\n\n# Task Report\n\n## Selected Task\n\n<one sentence>\n\n## Scope\n\n<docs-only / code / tests / schemas / CLI / API / dashboard / audit-only>\n\n## Success Criteria\n\n- <criterion>\n\n## Assumptions\n\n- <assumption>\n\n## Plan Alignment\n\n- Tracker current next task followed: yes/no\n- Plan changed: yes/no\n- Human decision needed: yes/no\n- If human decision is needed, ask the specific question and stop:\n\n## Scope Control\n\n- Smallest safe change used: yes/no\n- Drive-by refactors avoided: yes/no\n- Unexpected files changed: yes/no\n- If unexpected files changed, explain:\n\n## Files Changed\n\n- <path>: <short reason>\n\n## What Changed\n\n<concise summary>\n\n## What Did Not Change\n\n- No runtime behavior changes unless explicitly intended.\n- No schema changes unless explicitly intended.\n- No dynamic plugin loading.\n- No safety/governance warning weakening.\n- No generated runtime artifacts committed.\n\n## Documentation Sync\n\n- Docs updated: yes/no\n- Docs changed:\n- If no docs changed, why not:\n\n## Verification\n\n| Command | Result |\n|---|---|\n| python -m pytest -q | <pass/fail + count> |\n| python main.py --step conformance | <pass/fail + checks> |\n| python tools/ai_dev_supervisor/run_review.py --run-conformance | <pass/fail> |\n\n## Tracker\n\n- Updated: yes/no\n- Section changed:\n- Current next task before this task:\n- Current next task after this task:\n- If not updated, explain why the tracker did not need to change:\n\n## GitHub Sync\n\n- Committed: yes/no\n- Commit hash, if any:\n- Pushed: yes/no\n- Branch state: clean/dirty/ahead/behind/synchronized\n\n## Git Status\n\n<clean / modified files / ahead/behind>\n\n## Risks Or Follow-Ups\n\n- <risk>\n- <follow-up>\n\n## Recommended Commit Message\n\n<message>\n\n## Recommended Next Task\n\n<one task only>\n`,
  };
}

async function runCursor(instruction: string, label = "Cursor"): Promise<string> {
  requireEnv("CURSOR_API_KEY");

  await writeFileEnsuringDir(NEXT_INSTRUCTION_PATH, instruction);

  const cursorArgs =
    process.env.AGENT_APPLY === "1"
      ? ["--trust", "--force", "-p", instruction, "--output-format", "text"]
      : ["--trust", "-p", instruction, "--output-format", "text"];

  console.log(
    process.env.AGENT_APPLY === "1"
      ? `Running ${label} in apply mode (--force enabled).`
      : `Running ${label} in proposal/report mode (--force disabled).`
  );

  try {
    const { stdout, stderr } = await execFileAsync("cursor-agent", cursorArgs, {
      env: {
        ...process.env,
        CURSOR_API_KEY: process.env.CURSOR_API_KEY,
      },
      maxBuffer: MAX_BUFFER_BYTES,
    });

    const result = ["# Cursor stdout", stdout, "# Cursor stderr", stderr].join(
      "\n\n"
    );

    await writeFileEnsuringDir(LAST_CURSOR_RESULT_PATH, result);
    return result;
  } catch (error: any) {
    const result = [
      "# Cursor execution failed",
      `message: ${error?.message || String(error)}`,
      "# Cursor stdout",
      error?.stdout || "",
      "# Cursor stderr",
      error?.stderr || "",
    ].join("\n\n");

    await writeFileEnsuringDir(LAST_CURSOR_RESULT_PATH, result);
    throw new Error(
      `Cursor execution failed. Details saved to ${LAST_CURSOR_RESULT_PATH}`
    );
  }
}

async function main(): Promise<void> {
  console.log("Starting agent step...");

  const openai = new OpenAI({
    apiKey: requireEnv("OPENAI_API_KEY"),
  });

  const state = await loadState();

  const executionTracker = await readFileSafe(EXECUTION_TRACKER_PATH);
  const planGate = evaluateExecutionTracker(executionTracker);

  if (!planGate.ok) {
    console.log("\n=== Agent loop stopped by execution tracker ===\n");
    console.log(`Reason: ${planGate.reason}`);
    if (planGate.currentNextTask !== undefined) {
      console.log(`Current next task: ${planGate.currentNextTask}`);
    }
    console.log(
      "Human review is required before the loop can safely continue."
    );
    return;
  }

  const plannedInstruction = await generateCursorInstruction(openai, state);
  const { instruction, mode } = buildCursorInstructionWithStandingRules(
    plannedInstruction
  );

  console.log("\n=== Instruction to Cursor ===\n");
  console.log(instruction);
  console.log(`\n=== Inferred task mode: ${mode} ===\n`);

  await writeFileEnsuringDir(NEXT_INSTRUCTION_PATH, instruction);

  const beforeCursorChanges = await getGitChangeSummary();
  const result = await runCursor(instruction);

  const trackerCheck = await validateTrackerRule(mode, {
    beforeChangedFiles: beforeCursorChanges.changedFiles,
  });
  let repairResult = "";

  if (!trackerCheck.ok) {
    console.log(`\n=== Tracker rule failed: ${trackerCheck.message} ===\n`);
    const beforeRepairChanges = await getGitChangeSummary();
    const repairPrompt = buildTrackerRepairPrompt(plannedInstruction, result);
    repairResult = await runCursor(repairPrompt, "Cursor tracker repair");

    const secondCheck = await validateTrackerRule(mode, {
      beforeChangedFiles: beforeRepairChanges.changedFiles,
    });
    if (!secondCheck.ok) {
      throw new Error(
        `Tracker rule failed after repair attempt: ${secondCheck.message}`
      );
    }
  }

  state.iteration += 1;
  await saveState(state);

  console.log("\n=== Cursor Result ===\n");
  console.log(result);

  if (repairResult) {
    console.log("\n=== Cursor Tracker Repair Result ===\n");
    console.log(repairResult);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});