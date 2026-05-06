import { execFile } from "child_process";
import fs from "fs/promises";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

const EXECUTION_TRACKER_PATH = "docs/EXECUTION_TRACKER.md";
const MAX_BUFFER_BYTES = 1024 * 1024 * 20;

type StopReason =
  | { kind: "completed_max_steps" }
  | { kind: "step_failed"; exitCode: number }
  | { kind: "tracker_gate"; message: string }
  | { kind: "no_progress"; detail: string };

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

function outputIndicatesTrackerStop(out: string): string | undefined {
  if (out.includes("Agent loop stopped by execution tracker")) {
    return "Agent loop stopped by execution tracker";
  }
  return undefined;
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
    console.log(`HEAD before: ${headBefore}`);
    if (nextTaskBefore !== undefined) {
      console.log(`Tracker current next task (before): ${nextTaskBefore}`);
    }

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

