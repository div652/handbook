#!/usr/bin/env python3

import argparse
import json
import math
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def task_name(result: dict) -> str:
    task = result.get("task_name") or result.get("task_id", {}).get("path", "unknown")
    return task.rsplit("/", 1)[-1]


def reward(result: dict) -> float | None:
    value = result.get("verifier_result", {}).get("rewards", {}).get("reward")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    return score if math.isfinite(score) and 0.0 <= score <= 1.0 else None


def render(job_dir: Path) -> tuple[str, bool]:
    aggregate = load_json(job_dir / "result.json")
    stats = aggregate["stats"]
    results = []

    for path in job_dir.glob("*/result.json"):
        try:
            results.append(load_json(path))
        except (OSError, json.JSONDecodeError):
            continue

    valid = [
        result
        for result in results
        if result.get("exception_info") is None and reward(result) is not None
    ]
    errors = [result for result in results if result.get("exception_info") is not None]
    invalid_rewards = [
        result
        for result in results
        if result.get("exception_info") is None and reward(result) is None
    ]
    strict = [result for result in valid if reward(result) == 1.0]
    completed_tasks = {task_name(result) for result in valid}
    solved_tasks = {task_name(result) for result in strict}
    scores = [reward(result) for result in valid]
    average = sum(scores) / len(scores) if scores else 0.0
    strict_rate = len(strict) / len(valid) if valid else 0.0
    root_free_gib = shutil.disk_usage("/").free / (1024**3)

    by_task: dict[str, list[float]] = {}
    for result in valid:
        by_task.setdefault(task_name(result), []).append(reward(result))
    fully_attempted = sum(len(task_scores) >= 4 for task_scores in by_task.values())

    latest = sorted(
        valid,
        key=lambda result: result.get("finished_at") or "",
        reverse=True,
    )[:10]

    lines = [
        "# HANDBOOK benchmark progress",
        "",
        f"Updated: `{datetime.now(UTC).isoformat(timespec='seconds')}`",
        "",
        "| Metric | Current |",
        "|---|---:|",
        f"| Trials completed | {stats['n_completed_trials']} / {aggregate['n_total_trials']} |",
        f"| Trials running | {stats['n_running_trials']} |",
        f"| Trials pending | {stats['n_pending_trials']} |",
        f"| Trials errored | {max(stats['n_errored_trials'], len(errors))} |",
        f"| Infrastructure retries | {stats.get('n_retries') or 0} |",
        f"| Invalid or missing rewards | {len(invalid_rewards)} |",
        f"| Valid scored trials | {len(valid)} |",
        f"| Unique tasks with a completed attempt | {len(completed_tasks)} / 65 |",
        f"| Tasks with all 4 attempts completed | {fully_attempted} / 65 |",
        f"| Tasks solved at least once (reward = 1) | "
        f"{len(solved_tasks)} / {len(completed_tasks)} attempted (65 total) |",
        f"| Strict-passing trials | {len(strict)} / {len(valid)} |",
        f"| Running strict pass@1 estimate | {strict_rate:.4f} ({strict_rate:.2%}) |",
        f"| Running average score | {average:.4f} ({average:.2%}) |",
        f"| Input tokens | {stats.get('n_input_tokens') or 0:,} |",
        f"| Output tokens | {stats.get('n_output_tokens') or 0:,} |",
        f"| Root disk available | {root_free_gib:.2f} GiB |",
        "",
        "The two score estimates use only valid trials completed so far and can change "
        "substantially before all 260 trials finish.",
        "",
        "## Latest completed trials",
        "",
        "| Finished (UTC) | Task | Reward | Strict |",
        "|---|---|---:|:---:|",
    ]

    for result in latest:
        finished = (result.get("finished_at") or "")[:19].replace("T", " ")
        score = reward(result)
        lines.append(
            f"| {finished} | `{task_name(result)}` | {score:.4f} | "
            f"{'yes' if score == 1.0 else 'no'} |"
        )

    return "\n".join(lines) + "\n", aggregate.get("finished_at") is not None


def write_report(job_dir: Path, output: Path) -> bool:
    report, finished = render(job_dir)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(report, encoding="utf-8")
    os.replace(temporary, output)
    return finished


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--watch", type=int, metavar="SECONDS")
    args = parser.parse_args()
    output = args.output or args.job_dir / "PROGRESS.md"

    while True:
        try:
            finished = write_report(args.job_dir, output)
        except (OSError, KeyError, json.JSONDecodeError) as error:
            print(f"Could not update report: {error}", flush=True)
            finished = False
        if not args.watch or finished:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
