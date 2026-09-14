# How HANDBOOK Runs a Model

## Architecture

Harbor gives each trial an isolated Linux Docker container. It is conceptually
a small virtual computer, although it shares the host's Linux kernel. The model
API is remote; an OpenHands agent loop runs inside the container and mediates
between the model and the container's tools.

```text
Harbor
  └─ task container
       ├─ /workdir       task files and policy documents
       ├─ /data          mutable mock-service state
       ├─ /initial_data  original mock-service state
       ├─ /app           OpenHands runner, MCP proxy, and mock services
       └─ /logs          agent and verifier outputs
            │
            └─ OpenHands → remote model API
                    │
                    └─ MCP tools → files, Gmail, Slack, Jira, Calendar, Shopify
```

## Trial lifecycle

1. `harbor run -p tasks/<task>` finds `<task>/task.toml`.
2. Harbor builds the task's `environment/Dockerfile`. It extends
   `handbook_base`, copies task files into `/workdir`, and copies initial mock
   service data into `/data` and `/initial_data`.
3. Harbor imports `agent_harness.openhands_agent:OpenHandsAgent`. The
   `module:class` path resolves through the editable Python package installed
   from `./agent_harness`.
4. `OpenHandsAgent.setup()` starts the in-container MCP proxy at
   `http://localhost:8000/mcp`.
5. The proxy starts the mock Gmail, Slack, Jira, Calendar, and Shopify services
   and exposes their selected tools together with Syntara's filesystem,
   Bash, and Python tools.
6. `OpenHandsAgent.run()` reads `system_prompt.md`, receives `instruction.md`
   from Harbor, and uploads a run configuration containing the model name,
   prompts, MCP URL, protocol controls, and 200-tool-call limit. For TRAPI, the
   host stages a short-lived token file instead of placing the bearer value in
   Docker Compose arguments; the container reads and deletes it before launch.
7. The in-container OpenHands runner creates a LiteLLM client, verifies the
   expected API mode and reasoning transport, records the non-secret effective
   request settings, and creates an OpenHands `Agent`. A protocol-aware adapter
   keeps condenser calls on the same API mode as the main loop. OpenHands
   discovers the available tools using MCP `tools/list` and includes their
   schemas in the model request.
8. The agent loop repeatedly calls the remote model. The model either returns a
   final message or requests a tool call. OpenHands sends tool calls to the MCP
   proxy and puts the structured results back into the next model request.
9. File changes remain in `/workdir`. Mock-service mutations are persisted
   under `/data/<service>/final.json`.
10. OpenHands writes its trajectory and usage metadata under `/logs/agent`.
11. Harbor runs `/tests/test.sh`. The verifier evaluates every programmatic
    rubric against the final workspace and mock-service state.

## Tool surface

Every current HANDBOOK task exposes 82 tools:

| Category | Count | Examples |
|---|---:|---|
| Filesystem and computation | 6 | `listFiles`, `readFile`, `readPDF`, `writeFile`, `executeBash`, `executePython` |
| Google Mail | 29 | search, read, send, reply, forward, move, and mark email |
| Slack | 12 | search messages, read channels, post, reply, and send DMs |
| Jira | 19 | search, create, update, transition, and comment on issues |
| Google Calendar | 6 | search, list, create, update, and delete events |
| Shopify | 10 | search products, inspect carts/orders, create orders, and update carts |

These are local mock services, not real enterprise APIs. For example:

```text
model requests google_mail__send_email(...)
  → OpenHands sends an MCP request
  → MCP proxy routes it to mock Google Mail
  → the service updates /data/google_mail/final.json
  → the result returns to the model
```

MCP provides one typed interface for both system operations and business
services. The model sees public tool names, descriptions, and argument schemas,
but cannot read their protected implementation source.

## Policy-document handling

Policy documents are files in `/workdir`; their contents are not inserted into
the initial prompt. The model must discover and read them:

- PDF: `syntara__readPDF`, `pdftotext`, or Python PDF libraries.
- Text/HTML: paginated `syntara__readFile`.
- DOCX: Python with `python-docx`.
- XLSX: Python with `openpyxl` or `pandas`.

There is no built-in RAG, semantic-search, or summary tool. The model can create
lightweight retrieval during the run:

```bash
pdftotext policy.pdf policy.txt
grep -in -C 5 "approval threshold" policy.txt
```

The extracted file stays in `/workdir`; only the matching output enters model
context. Calling `readPDF` directly instead returns the extracted PDF text as a
tool observation. OpenHands raises the observation limit to one million
characters and can summarize older conversation events if the context becomes
too large.

## Grading

Each task has deterministic rubrics in `tests/rubrics.json`. The verifier checks
both required actions and prohibited behavior, then writes:

- `results.json`: task and rubric results;
- `verifier/reward.txt`: the mean fractional rubric score.

`reward = 1.0` means every rubric received full credit and therefore the trial
is also a strict task pass. A reward below `1.0` is partial rubric credit and a
strict failure.

For repeated runs, report both:

- **pass@1 / strict pass rate**: fraction of individual trials that pass every
  rubric;
- **pass@k**, if desired: probability or fraction of tasks with at least one
  strict success across `k` attempts.

## Inspecting a Harbor job

Open Harbor's interactive job viewer with:

```bash
cd /home/agarwaldi/handbook
.venv/bin/harbor view jobs
```

A job directory contains an aggregate result and one subdirectory per trial:

```text
jobs/2026-09-10__13-42-41/
├── result.json
└── finance_meridian_partners_19d575__e7v95DK/
    ├── result.json
    ├── trial.log
    ├── agent/
    │   ├── trajectory.json
    │   ├── run-openhands.log
    │   └── mcp-proxy.log
    └── verifier/
        ├── reward.txt
        └── test-stdout.txt
```

The important files are:

| File | What to check |
|---|---|
| Job `result.json` | Number of completed/errored trials, aggregate mean, token totals, and reward distribution |
| Trial `result.json` | Model and agent configuration, timing, token usage, stop reason, exception, and reward |
| `verifier/test-stdout.txt` | Each rubric's `PASS`/`FAIL` status and feedback |
| `verifier/reward.txt` | Mean fractional rubric score for this trial |
| `agent/trajectory.json` | Ordered model actions, tool arguments, observations, stopping status, and usage |
| `agent/request_protocol.json` | SDK-selected API mode, reasoning transport, and non-secret sampling settings |
| `agent/run-openhands.log` | Detailed OpenHands and model execution diagnostics |
| `agent/mcp-proxy.log` | MCP discovery, routing, and mock-service errors |

For the example trial, `test-stdout.txt` reports:

```text
[sop-verifier] 9/9 rubrics passed; score=1.00
```

Therefore its `reward = 1.0` is both:

- the average rubric score: all nine rubrics received full credit;
- a strict task pass: every rubric passed.

Because this was one attempt on one task, its observed pass@1 is `1/1 = 100%`.
It is not a benchmark-wide pass rate.

## Understanding `trajectory.json`

Consider:

```text
jobs/2026-09-10__13-42-41/
  finance_meridian_partners_19d575__e7v95DK/
  agent/trajectory.json
```

Its top-level fields summarize the run:

```json
{
  "agent_id": "openhands_sdk",
  "model": "<PROVIDER>/<MODEL_DEPLOYMENT>",
  "n_tool_calls": 16,
  "n_agent_errors": 0,
  "stopped_reason": "end_turn",
  "input_tokens": 317045,
  "cache_tokens": 276928,
  "output_tokens": 6025,
  "cost_usd": null
}
```

Interpretation:

- `n_tool_calls: 16`: the agent made 16 actions, including its final `finish`.
- `n_agent_errors: 0`: OpenHands recorded no agent-loop errors.
- `stopped_reason: end_turn`: the agent finished normally rather than reaching
  its limit, becoming stuck, or failing.
- token fields: cumulative model usage across the agent and condenser clients.
- `cost_usd: null`: LiteLLM had no pricing information for this TRAPI model;
  it does not mean the run had zero cost.

`steps` contains the chronological trace. This run has 17 steps: one user
instruction followed by 16 agent actions. Its tool sequence was:

```text
listFiles → readFile → executePython
→ search/read email
→ executePython
→ inspect Slack and contacts
→ send email
→ post Slack message
→ update and verify files with Python/readFile
→ finish
```

A typical action step contains:

```json
{
  "source": "agent",
  "tool_calls": [
    {
      "function_name": "syntara__listFiles",
      "arguments": {"directory": "/workdir"}
    }
  ],
  "observation": {
    "results": [
      {
        "content": "...SOP.html, ap_ledger.xlsx, match_log_2025_Q2.xlsx..."
      }
    ]
  }
}
```

Read it as:

```text
model chose a tool
→ OpenHands executed it through MCP
→ observation was returned to the model
→ the model chose the next action
```

Useful `jq` commands:

```bash
T=<path-to-trial>/agent/trajectory.json

# High-level outcome and usage
jq '{model,n_tool_calls,n_agent_errors,stopped_reason,error_message,
     input_tokens,cache_tokens,output_tokens,cost_usd}' "$T"

# Ordered tool sequence
jq -r '.steps[] | select(.source=="agent")
       | .tool_calls[]?.function_name' "$T"

# Tool calls with their arguments
jq '.steps[] | select(.source=="agent")
    | .tool_calls[]? | {function_name,arguments}' "$T"

# Final finish summary
jq '.steps[-1].tool_calls[0].arguments' "$T"
```

Check three things first: whether the agent stopped normally, whether its tool
sequence makes sense for the task, and whether observations support its later
actions. Then compare those actions with per-rubric verifier feedback.
