import { execFile } from "child_process";
import fs from "fs/promises";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

const EXECUTION_TRACKER_PATH = "docs/EXECUTION_TRACKER.md";
const MAX_BUFFER_BYTES = 1024 * 1024 * 20;

type StopReason =
  | { kind: "completed_max_steps" }
  | { kind: "stopped_human_decision"; nextTask: string }
  | { kind: "stopped_preflight_git_gate"; message: string }
  | { kind: "stopped_local_verify"; exitCode: number }
  | { kind: "stopped_local_shell"; exitCode: number }
  | { kind: "stopped_commit_push_gate"; message: string }
  | { kind: "step_failed"; exitCode: number }
  | { kind: "tracker_gate"; message: string }
  | { kind: "no_progress"; detail: string };

type TaskType =
  | "human_decision"
  | "local_shell"
  | "verify"
  | "commit_push"
  | "tracker_update"
  | "docs_edit"
  | "code_edit"
  | "audit"
  | "unknown";

function parseMaxStepsFromEnv(): number {
  const raw = process.env.MAX_AGENT_STEPS;
  const allowLarge = process.env.AGENT_ALLOW_LARGE_LOOP === "1";

  if (!raw) {
    return 3;
  }

  const n = Number(raw);
  if (!Number.isFinite(n) || !Number.isInteger(n)) {
    throw new Error(`MAX_AGENT_STEPS must be an integer; got: ${raw}`);
  }
  if (n < 1) {
    throw new Error(`MAX_AGENT_STEPS must be >= 1; got: ${n}`);
  }
  if (!allowLarge && n > 10) {
    return 10;
  }
  return n;
}

async function readFileSafe(path: string): Promise<string> {
  try {
    return await fs.readFile(path, "utf8");
  } catch {
    return "";
  }
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

async function currentNextTaskIfAny(): Promise<string | undefined> {
  const text = await readFileSafe(EXECUTION_TRACKER_PATH);
  if (!text.trim()) {
    return undefined;
  }
  return extractCurrentNextTask(text);
}

async function runCommand(
  command: string,
  args: string[]
): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  try {
    const res = await execFileAsync(command, args, {
      maxBuffer: MAX_BUFFER_BYTES,
      env: process.env,
    });
    return { stdout: res.stdout ?? "", stderr: res.stderr ?? "", exitCode: 0 };
  } catch (error: any) {
    const stdout = error?.stdout ?? "";
    const stderr = error?.stderr ?? "";
    const exitCode = Number.isInteger(error?.code) ? error.code : 1;
    return { stdout, stderr, exitCode };
  }
}

async function gitHeadShort(): Promise<string> {
  const r = await runCommand("git", ["rev-parse", "--short", "HEAD"]);
  return (r.stdout || "").trim();
}

async function gitStatusSb(): Promise<string> {
  const r = await runCommand("git", ["status", "-sb"]);
  return (r.stdout || r.stderr || "").trim();
}

async function gitTrackedDirtyFiles(): Promise<string[]> {
  const [unstaged, staged] = await Promise.all([
    runCommand("git", ["diff", "--name-only"]),
    runCommand("git", ["diff", "--name-only", "--cached"]),
  ]);

  const files = new Set<string>();
  for (const line of (unstaged.stdout || "").split("\n")) {
    const f = line.trim();
    if (f) files.add(f);
  }
  for (const line of (staged.stdout || "").split("\n")) {
    const f = line.trim();
    if (f) files.add(f);
  }
  return [...files].sort();
}

async function gitUntrackedFiles(): Promise<string[]> {
  const r = await runCommand("git", ["status", "--porcelain"]);
  const lines = (r.stdout || "").split("\n");
  const out: string[] = [];
  for (const line of lines) {
    if (line.startsWith("?? ")) {
      out.push(line.slice(3).trim());
    }
  }
  return out.filter(Boolean).sort();
}

function classifyTaskType(nextTask: string | undefined): TaskType {
  const raw = (nextTask ?? "").trim();
  if (!raw) {
    return "unknown";
  }

  const t = raw.toLowerCase();

  if (t.includes("needs human decision") || t.includes("requires human decision")) {
    return "human_decision";
  }

  if (t.includes("tracker") || t.includes("execution tracker")) {
    return "tracker_update";
  }

  if (
    t.includes("run full verification") ||
    t.includes("verification trio") ||
    t.includes("pytest") ||
    t.includes("conformance") ||
    t.includes("run_review.py") ||
    t.includes("supervisor conformance")
  ) {
    return "verify";
  }

  if (t.includes("push") || t.includes("commit")) {
    return "commit_push";
  }

  if (t.includes("run the sdk example") || t.includes("manually")) {
    return "local_shell";
  }

  if (t.includes("docs-only") || t.includes("walkthrough") || t.includes("documentation")) {
    return "docs_edit";
  }

  if (t.includes("audit")) {
    return "audit";
  }

  return "unknown";
}

function outputIndicatesTrackerStop(out: string): string | undefined {
  if (out.includes("Agent loop stopped by execution tracker")) {
    return "Agent loop stopped by execution tracker";
  }
  return undefined;
}

function renderRecommendedGitCommands(changedTrackedFiles: string[]): string {
  const fileList = changedTrackedFiles.length
    ? changedTrackedFiles.map((f) => `- ${f}`).join("\n")
    : "(none)";

  return [
    "Tracked files are dirty. Recommended next commands:",
    "",
    "git status -sb",
    "git diff --stat",
    "git diff",
    "",
    "Changed tracked files:",
    fileList,
  ].join("\n");
}

async function runLocalVerify(): Promise<{ exitCode: number }> {
  const commands: Array<{ cmd: string; args: string[] }> = [
    { cmd: "python", args: ["-m", "pytest", "-q"] },
    { cmd: "python", args: ["main.py", "--step", "conformance"] },
    { cmd: "python", args: ["tools/ai_dev_supervisor/run_review.py", "--run-conformance"] },
  ];

  console.log("\nLocal verify mode: will NOT call Cursor.");
  for (const c of commands) {
    console.log(`\n$ ${c.cmd} ${c.args.join(" ")}`);
    const r = await runCommand(c.cmd, c.args);
    const combined = [r.stdout, r.stderr].filter(Boolean).join("\n").trim();
    if (combined) {
      console.log(combined);
    }
    if (r.exitCode !== 0) {
      console.log(`\nLocal verify failed (exit ${r.exitCode}). Stopping.`);
      return { exitCode: r.exitCode };
    }
  }

  console.log("\nLocal verify succeeded. Stopping (tracker update still required).");
  return { exitCode: 0 };
}

async function runLocalShell(nextTask: string): Promise<{ exitCode: number }> {
  console.log("\nLocal shell mode: will NOT call Cursor.");

  const lower = nextTask.toLowerCase();
  if (lower.includes("sdk example")) {
    const scriptPath = "examples/sdk/program_reporting_walkthrough.py";
    console.log(`\n$ python ${scriptPath}`);
    const r = await runCommand("python", [scriptPath]);
    const combined = [r.stdout, r.stderr].filter(Boolean).join("\n").trim();
    if (combined) {
      console.log(combined);
    }
    if (r.exitCode !== 0) {
      console.log(`\nLocal shell task failed (exit ${r.exitCode}). Stopping.`);
      return { exitCode: r.exitCode };
    }

    const summaryLines = (r.stdout || "")
      .trim()
      .split("\n")
      .filter(Boolean)
      .slice(0, 60);
    console.log("\nOutput summary (first ~60 non-empty lines):");
    console.log(summaryLines.join("\n") || "(no stdout)");
    console.log("\nStopping. Next: update `docs/EXECUTION_TRACKER.md` with the run summary.");
    return { exitCode: 0 };
  }

  console.log(
    "\nLocal shell task detected, but no deterministic runner was selected for this task text."
  );
  console.log("Stopping. Update the loop to add a runner or run the command manually.");
  return { exitCode: 1 };
}

async function runCommitPushGate(nextTask: string): Promise<StopReason> {
  const allowCommit = process.env.AGENT_ALLOW_COMMIT === "1";
  const allowPush = process.env.AGENT_ALLOW_PUSH === "1";

  console.log("\nCommit/push mode: will NOT call Cursor.");
  console.log(`AGENT_ALLOW_COMMIT=${allowCommit ? "1" : "0"}; AGENT_ALLOW_PUSH=${allowPush ? "1" : "0"}`);

  const status = await gitStatusSb();
  console.log("\nLatest git status -sb:");
  console.log(status || "(no output)");

  if (!allowCommit && !allowPush) {
    return {
      kind: "stopped_commit_push_gate",
      message: [
        "Auto-commit and auto-push are disabled.",
        "",
        "Recommended commands (edit commit message as appropriate):",
        "git status -sb",
        "git diff --stat",
        "git diff",
        "git add -u",
        "git commit -m \"chore: checkpoint\"",
        "git push",
      ].join("\n"),
    };
  }

  const untracked = await gitUntrackedFiles();
  if (untracked.length > 0) {
    return {
      kind: "stopped_commit_push_gate",
      message: [
        "Untracked files present; agent-loop will not guess what to commit.",
        "Either add them explicitly or clean them up, then retry.",
        "",
        "Untracked:",
        untracked.map((f) => `- ${f}`).join("\n"),
      ].join("\n"),
    };
  }

  if (allowCommit) {
    console.log("\n$ git add -u");
    const add = await runCommand("git", ["add", "-u"]);
    const addOut = [add.stdout, add.stderr].filter(Boolean).join("\n").trim();
    if (addOut) console.log(addOut);
    if (add.exitCode !== 0) {
      return {
        kind: "stopped_commit_push_gate",
        message: `git add -u failed (exit ${add.exitCode}).`,
      };
    }

    const msg = process.env.AGENT_COMMIT_MESSAGE || "chore: agent-loop checkpoint";
    console.log(`\n$ git commit -m "${msg.replace(/"/g, '\\"')}"`);
    const commit = await runCommand("git", ["commit", "-m", msg]);
    const commitOut = [commit.stdout, commit.stderr].filter(Boolean).join("\n").trim();
    if (commitOut) console.log(commitOut);
    if (commit.exitCode !== 0) {
      return {
        kind: "stopped_commit_push_gate",
        message: `git commit failed (exit ${commit.exitCode}).`,
      };
    }
  } else {
    console.log("\nCommit step skipped (AGENT_ALLOW_COMMIT!=1).");
  }

  if (allowPush) {
    console.log("\n$ git push");
    const push = await runCommand("git", ["push"]);
    const pushOut = [push.stdout, push.stderr].filter(Boolean).join("\n").trim();
    if (pushOut) console.log(pushOut);
    if (push.exitCode !== 0) {
      return {
        kind: "stopped_commit_push_gate",
        message: `git push failed (exit ${push.exitCode}).`,
      };
    }
  } else {
    console.log("\nPush step skipped (AGENT_ALLOW_PUSH!=1).");
    return {
      kind: "stopped_commit_push_gate",
      message:
        "Commit completed (if enabled), but push is disabled. Run `git push` manually if desired.",
    };
  }

  return {
    kind: "stopped_commit_push_gate",
    message: `Commit/push handling completed for task: ${nextTask}`,
  };
}

async function main(): Promise<void> {
  const maxSteps = parseMaxStepsFromEnv();
  console.log(`Starting bounded agent loop (MAX_AGENT_STEPS=${maxSteps})`);

  let stepsAttempted = 0;
  let stop: StopReason = { kind: "completed_max_steps" };

  let unchangedStreak = 0;
  let lastHead: string | undefined;
  let lastNextTask: string | undefined;

  for (let i = 1; i <= maxSteps; i += 1) {
    console.log(`\n=== Agent loop iteration ${i}/${maxSteps} ===\n`);

    const headBefore = await gitHeadShort();
    const nextTaskBefore = await currentNextTaskIfAny();
    const taskType = classifyTaskType(nextTaskBefore);
    console.log(`HEAD before: ${headBefore}`);
    if (nextTaskBefore !== undefined) {
      console.log(`Tracker current next task (before): ${nextTaskBefore}`);
    }
    console.log(`Classified task type: ${taskType}`);

    // Hard stop: human decision tasks should not invoke Cursor.
    if (taskType === "human_decision" && nextTaskBefore) {
      console.log("\nStop reason: human decision required. Not calling Cursor.");
      stop = { kind: "stopped_human_decision", nextTask: nextTaskBefore };
      break;
    }

    // Deterministic local handlers (avoid Cursor for shell-reliant tasks).
    if (taskType === "verify") {
      console.log("\nWill call Cursor: no (local verify).");
      const r = await runLocalVerify();
      stop = { kind: "stopped_local_verify", exitCode: r.exitCode };
      break;
    }

    if (taskType === "local_shell" && nextTaskBefore) {
      console.log("\nWill call Cursor: no (local shell).");
      const r = await runLocalShell(nextTaskBefore);
      stop = { kind: "stopped_local_shell", exitCode: r.exitCode };
      break;
    }

    if (taskType === "commit_push" && nextTaskBefore) {
      console.log("\nWill call Cursor: no (local commit/push gate).");
      stop = await runCommitPushGate(nextTaskBefore);
      break;
    }

    // Preflight git gate (tracked-dirty) before invoking Cursor.
    const changedTrackedFiles = await gitTrackedDirtyFiles();
    if (
      changedTrackedFiles.length > 0 &&
      taskType !== "tracker_update" &&
      taskType !== "commit_push"
    ) {
      console.log("\nWill call Cursor: no (preflight git gate).");
      const msg = renderRecommendedGitCommands(changedTrackedFiles);
      console.log(`\n${msg}`);
      stop = { kind: "stopped_preflight_git_gate", message: msg };
      break;
    }

    console.log("\nWill call Cursor: yes (agent:step).");
    const step = await runCommand("npm", ["run", "agent:step"]);
    stepsAttempted += 1;

    const combined = [step.stdout, step.stderr].filter(Boolean).join("\n");

    if (step.exitCode !== 0) {
      console.log("\n=== agent:step failed ===\n");
      if (combined.trim()) {
        console.log(combined.trim());
      }
      stop = { kind: "step_failed", exitCode: step.exitCode };
      break;
    }

    const trackerStop = outputIndicatesTrackerStop(combined);
    if (trackerStop) {
      console.log("\n=== agent:step stopped by tracker gate ===\n");
      stop = { kind: "tracker_gate", message: trackerStop };
      break;
    }

    const headAfter = await gitHeadShort();
    const nextTaskAfter = await currentNextTaskIfAny();
    console.log(`HEAD after: ${headAfter}`);
    if (nextTaskAfter !== undefined) {
      console.log(`Tracker current next task (after): ${nextTaskAfter}`);
    }

    const unchangedThisIter =
      headAfter === headBefore &&
      String(nextTaskAfter ?? "") === String(nextTaskBefore ?? "");

    if (
      lastHead !== undefined &&
      lastNextTask !== undefined &&
      headAfter === lastHead &&
      String(nextTaskAfter ?? "") === String(lastNextTask ?? "")
    ) {
      unchangedStreak += 1;
    } else if (unchangedThisIter) {
      unchangedStreak = Math.max(unchangedStreak, 1);
    } else {
      unchangedStreak = 0;
    }

    lastHead = headAfter;
    lastNextTask = nextTaskAfter ?? "";

    if (unchangedStreak >= 2) {
      stop = {
        kind: "no_progress",
        detail:
          "HEAD and tracker Current next task unchanged for two consecutive iterations.",
      };
      break;
    }
  }

  console.log("\n=== Agent loop summary ===\n");
  console.log(`Steps attempted: ${stepsAttempted}`);
  console.log(`Stop reason: ${stop.kind}${"exitCode" in stop ? ` (${stop.exitCode})` : ""}`);

  if (stop.kind === "tracker_gate") {
    console.log(`Tracker gate: ${stop.message}`);
  }
  if (stop.kind === "no_progress") {
    console.log(`No progress detail: ${stop.detail}`);
  }

  const status = await gitStatusSb();
  const head = await gitHeadShort();
  const nextTask = await currentNextTaskIfAny();

  console.log("\nLatest git status -sb:");
  console.log(status || "(no output)");
  console.log(`\nLatest commit: ${head || "(unknown)"}`);
  if (nextTask !== undefined) {
    console.log(`Current next task: ${nextTask}`);
  } else {
    console.log("Current next task: (not available)");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

