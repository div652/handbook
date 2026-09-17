# HANDBOOK.md Benchmark Tasks
HANDBOOK.md is a benchmark for long-context agentic instruction following, modeled on how enterprise employees follow company handbooks in their day-to-day work. Each task is a unique RL environment with internal tools and external MCP servers, spanning five enterprise domains: Finance, Medical Billing, Insurance, Logistics, and HR.

### What it tests

The prompts reflect the actual jobs enterprise workers perform every day. Each task drops an AI agent into a live company environment, requiring them to cross-reference an extensive, multi-section handbook against a cluttered inbox, a multi-channel Slack workspace, Jira queues, and a stack of files (spreadsheets, PDFs), and working out both what to do and what the handbook forbids.

### Why it's hard
These policies are written by experts adapting real industry guidelines and are explicitly designed to resist memorization. We created 10 unique base handbooks; every task then modifies its base into a distinct document by changing specific rules and thresholds. Because no two tasks share the same policy, models cannot pattern-match their way through the benchmark. Instead, they must actually read the complex instructions, hold them across a long multi-tool job, and apply them. No frontier model succeeds on more than 25% of tasks.

### Links
- [Blog post](https://surgehq.ai/blog/handbook-md)
- [Leaderboard](https://surgehq.ai/benchmarks/handbook)


Built by the [Surge AI](https://www.surgehq.ai) evals team. To evaluate your models on HANDBOOK.md or build expert-grade benchmarks in your own domains, contact benchmarks@surgehq.ai.


## Overview

- `agent_harness/` — Agent harness used to evaluate HANDBOOK.md. Built with [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk). 
- `docker/` — build context for the `handbook` base image. Contains mock services and the
  bundled agent harness.
- `tasks/` — one subdirectory per benchmark task.
- `.env.example` — template for required environment variables.
- [`BENCHMARK_RUNBOOK.md`](BENCHMARK_RUNBOOK.md) — operational instructions for
  reproducible TRAPI runs, including authentication, model selection,
  concurrency, retries, monitoring, recovery, and final scoring.
- [`COPILOT_BENCHMARK_RUNBOOK.md`](COPILOT_BENCHMARK_RUNBOOK.md) —
  operational instructions for VS Code Copilot proxy runs, including
  loopback-server setup, exact model/reasoning validation, immutable inputs,
  smoke testing, concurrency, monitoring, recovery, and scoring.

## Quick start

```bash
# 1. Build the base image (build context is self-contained)
docker build -t handbook_base docker/

# 2. Install the locked Harbor 0.22.0 environment and bundled agent harness
(cd agent_harness && uv lock --check)
UV_PROJECT_ENVIRONMENT="$PWD/.venv" \
  uv sync --project agent_harness --frozen --python 3.13
test "$(.venv/bin/harbor --version)" = "0.22.0"

# 3. Run a single task locally
.venv/bin/harbor run -p tasks/<task_name> \
    --agent agent_harness.openhands_agent:OpenHandsAgent \
    -m <PROVIDER>/<MODEL_DEPLOYMENT> -n 1 \
    --n-concurrent-agents 1 \
    --ak reasoning_effort=<CONFIRMED_REASONING_EFFORT> \
    --ak api_mode=<CONFIRMED_API_MODE> \
    --env-file .env
```

For TRAPI, follow [`BENCHMARK_RUNBOOK.md`](BENCHMARK_RUNBOOK.md) before running.
Confirm the endpoint, exact deployment, reasoning effort, and API mode rather
than reusing the example or a previous job's values.

### VS Code Copilot proxy

The harness can retain the OpenHands loop while routing its individual model
calls through the `GH Copilot Server` VS Code extension:

Follow [`COPILOT_BENCHMARK_RUNBOOK.md`](COPILOT_BENCHMARK_RUNBOOK.md) for a
reproducible smoke or full leaderboard run.

```bash
export COPILOT_PROXY_BASE_URL=http://127.0.0.1:3141/v1

.venv/bin/harbor run -p tasks/<task_name> \
    --agent agent_harness.openhands_agent:OpenHandsAgent \
    -m copilot/<EXACT_MODEL_ID> -n 1 \
    --n-concurrent-agents 1 \
    --ak reasoning_effort=<CONFIRMED_REASONING_EFFORT> \
    --ak api_mode=chat_completions
```

Start the extension server first and confirm the exact model ID with
`curl "$COPILOT_PROXY_BASE_URL/models"`. Each trial uses an authenticated,
short-lived relay to reach the host-only extension from Docker. The relay
checks the requested model against `/v1/models` before every completion and
rejects any response whose model differs.

The VS Code Language Model API has no system role. For Copilot proxy runs, the
harness wraps the task's system prompt in an explicit authoritative-instruction
block before the extension converts it to a user message. This is not
protocol-equivalent to a native system message and must be reported as a
benchmark limitation. The extension also reports zero token usage, which the
harness records as unavailable rather than as zero.

## Leaderboard Configuration

To match the configuration used in the leaderboard, run the complete task set
with four runs per task:

```bash
.venv/bin/harbor run \
    -p tasks/ \
    --agent agent_harness.openhands_agent:OpenHandsAgent \
    -m <PROVIDER>/<MODEL_DEPLOYMENT> \
    -k 4 \
    --ak reasoning_effort=<CONFIRMED_REASONING_EFFORT> \
    --ak api_mode=<CONFIRMED_API_MODE> \
    --env-file .env
```

The model, reasoning effort, and API mode must match the intended protocol. Do
not omit reasoning effort when using the current OpenHands runner: its SDK
default may differ from the provider default. Official full runs must follow
the runbook's immutable base-image, task-snapshot, and provenance procedure.

## License

Copyright 2026 Surge AI.

Licensed under the Apache License, Version 2.0. See [`LICENSE`](LICENSE) for the
full text.
