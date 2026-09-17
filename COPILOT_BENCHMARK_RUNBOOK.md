# HANDBOOK VS Code Copilot Benchmark Runbook

This runbook covers the HANDBOOK Harbor/OpenHands harness when model calls are
routed through the local `GH Copilot Server` VS Code extension. Read
[`BENCHMARK_RUNBOOK.md`](BENCHMARK_RUNBOOK.md) as well: its rules for immutable
task inputs, storage, retries, monitoring, final acceptance, and scoring still
apply. Replace its TRAPI-only authentication and endpoint checks with the
Copilot-specific procedures below.

## 1. Lock the protocol before making model calls

Confirm all of these values with the operator for every new result set:

1. The loopback OpenAI-compatible base URL, normally
   `http://127.0.0.1:3141/v1`.
2. The exact model ID returned by `GET /v1/models`. A display name is not
   sufficient.
3. The reasoning effort.
4. API mode `chat_completions`.
5. The number of tasks and attempts. A leaderboard run is 65 tasks with four
   valid attempts each, or 260 valid trials.
6. Trial and agent concurrency.

Use the `copilot/` Harbor prefix:

```bash
export COPILOT_PROXY_BASE_URL=http://127.0.0.1:<PORT>/v1
export MODEL="copilot/<EXACT_MODEL_ID>"
export REASONING_EFFORT=<EFFORT>
export API_MODE=chat_completions
```

Do not add temperature, `top_p`, seed, token-limit, or other generation
parameters unless the intended protocol explicitly requires them. The current
extension implements reasoning effort; the harness records the effective
request shape in `agent/request_protocol.json`.

## 2. Start and verify the local extension server

In the VS Code window connected to the benchmark host:

1. Open Command Palette.
2. Run `GH Copilot Server: Start Server`.
3. Open the `GH Copilot Server` Output channel.
4. Confirm it reports a loopback URL.

The remote `code` CLI does not expose a command-execution option, so a terminal
process cannot invoke this Command Palette action directly.

Verify the listener and model catalog:

```bash
ss -ltn '( sport = :<PORT> )'
curl --fail --show-error --max-time 20 \
  "$COPILOT_PROXY_BASE_URL/models"
```

The extension must listen only on `127.0.0.1`. Never expose the unauthenticated
extension directly on `0.0.0.0`, a Docker bridge, or a network interface. The
harness creates a separate authenticated, short-lived Docker-bridge relay for
each trial.

### Shared-host port conflicts

Before stopping any listener, identify its owner. On a shared host, do not use
or terminate another user's listener or bridge.

```bash
ss -ltnp '( sport = :3141 )'
```

If process details are hidden, `/proc/net/tcp` exposes the listener UID. Port
`3141` is hexadecimal `0C45`:

```bash
python - <<'PY'
from pathlib import Path

for path in Path("/proc/net").glob("tcp*"):
    for line in path.read_text().splitlines()[1:]:
        columns = line.split()
        if columns[1].upper().endswith(":0C45") and columns[3] == "0A":
            print(path.name, columns[1], "uid=" + columns[7])
PY
```

If another user owns the port, choose an unused loopback port. Version 0.1.0 of
the extension hardcodes `const PORT = 3141` in `out/server.js`; changing the
installed extension to an alternate port requires a VS Code window reload
before running `GH Copilot Server: Start Server` again. Record the changed
extension file's SHA-256 in run metadata. Extension updates can overwrite this
local patch.

### Exact model and reasoning probe

Do not infer an ID such as `claude-opus-4.8` from a product name. Require it to
appear in `/v1/models`, then probe the exact request shape:

```bash
curl --fail --show-error --max-time 600 \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "<EXACT_MODEL_ID>",
    "messages": [{"role": "user", "content": "Reply with OK only."}],
    "reasoning": {"effort": "<EFFORT>"}
  }' \
  "$COPILOT_PROXY_BASE_URL/chat/completions"
```

For extension 0.1.0, the effective reasoning input is the nested
`reasoning.effort` field. A top-level `reasoning_effort` probe can receive a
successful response while the extension ignores that setting. The Copilot
harness deliberately configures LiteLLM with
`extra_body.reasoning.effort`, and its authenticated relay rejects requests
whose nested effort or exact model does not match.

Reasoning requests can take several minutes even for a trivial prompt. A
120-second client timeout was too short for an observed
`claude-opus-4.8`/`high` probe; the harness model timeout is 600 seconds. Check
the extension Output channel before diagnosing a slow request as a failure.

## 3. Repository, runtime, and storage preflight

Run from the repository root and require a clean, committed checkout:

```bash
git rev-parse HEAD
test -z "$(git status --porcelain=v1 --untracked-files=all)"
test "$(find tasks -mindepth 2 -maxdepth 2 -name task.toml | wc -l)" = 65

(cd agent_harness && uv lock --check)
test "$(.venv/bin/harbor --version)" = "0.22.0"
.venv/bin/python --version
docker compose version

test "$(
  sha256sum \
    agent_harness/src/agent_harness/openhands_runner.py \
    docker/openhands-runner/openhands_runner.py |
  awk '{print $1}' | uniq | wc -l
)" = 1
```

Confirm `.env` is ignored and does not contain provider keys. Copilot runs do
not need an OpenAI, Anthropic, OpenRouter, or Gemini key:

```bash
git check-ignore .env
if grep -Eq \
  '^(OPENAI_API_KEY|ANTHROPIC_API_KEY|OPENROUTER_API_KEY|GEMINI_API_KEY)=' \
  .env; then
  echo "Remove provider credentials from .env" >&2
  exit 1
fi
```

Check both result storage and Docker's actual data root:

```bash
free -h
df -h / /mnt/datadrive
docker info --format 'Docker root: {{.DockerRootDir}}'
docker system df
```

Putting job output and `TMPDIR` on `/mnt/datadrive` does not move Docker images
or writable layers when Docker uses `/var/lib/docker`. Keep at least 5 GiB of
root headroom when possible. A cache-backed base-image rebuild can still add
about 1 GiB if a mutable base or package layer changed. On a shared machine,
never run broad Docker prune commands and never remove artifacts of uncertain
ownership.

Use one concurrent trial when root space is constrained. Observe the smoke
test's peak and final disk use before selecting higher full-run concurrency.

## 4. Materialize immutable inputs

Store runtime output on the data drive:

```bash
export JOB_NAME=<JOB_NAME>
export JOBS_DIR=/mnt/datadrive/<USER>/handbook-jobs
export TMPDIR=/mnt/datadrive/<USER>/handbook-tmp
export DOCKER_CONTEXT_DIR="$JOBS_DIR/$JOB_NAME.docker-context"
export TASKS_SNAPSHOT="$JOBS_DIR/$JOB_NAME.tasks"

mkdir -p "$JOBS_DIR" "$TMPDIR"
```

Do **not** export a variable named `DOCKER_CONTEXT` for the filesystem path.
Docker itself interprets `DOCKER_CONTEXT` as the name of a daemon context; an
exported path makes commands such as `docker image inspect` fail. Use
`DOCKER_CONTEXT_DIR`.

Materialize tracked files, build, tag by the full image ID, and snapshot all 65
tasks:

```bash
.venv/bin/python scripts/materialize_git_tree.py \
  --repository . \
  --source docker \
  --destination "$DOCKER_CONTEXT_DIR"

TEMP_BASE_TAG="handbook_base:build-$(date +%s)-$$"
DOCKER_BUILDKIT=1 docker build -t "$TEMP_BASE_TAG" "$DOCKER_CONTEXT_DIR"
BASE_IMAGE_ID="$(docker image inspect "$TEMP_BASE_TAG" --format '{{.Id}}')"
BASE_IMAGE_TAG="handbook_base:${BASE_IMAGE_ID#sha256:}"
docker tag "$TEMP_BASE_TAG" "$BASE_IMAGE_TAG"
docker image rm "$TEMP_BASE_TAG"

.venv/bin/python scripts/materialize_tasks.py \
  --repository . \
  --source tasks \
  --destination "$TASKS_SNAPSHOT" \
  --base-image "$BASE_IMAGE_TAG" \
  --expected-count 65
```

Verify the runner in the image matches the host source:

```bash
docker run --rm "$BASE_IMAGE_TAG" \
  sha256sum /app/openhands-runner/openhands_runner.py
sha256sum agent_harness/src/agent_harness/openhands_runner.py
```

Record immutable metadata before the smoke test. In addition to the fields in
the main runbook, a Copilot run should record:

- `COPILOT_PROXY_BASE_URL`;
- exact advertised model ID and `copilot/<id>` Harbor model;
- extension ID/version and SHA-256 hashes of `package.json`,
  `out/server.js`, and `out/extension.js`;
- any local port patch;
- `agent_harness/copilot_proxy.py` SHA-256;
- `provider_transport=github_copilot_vscode_extension`;
- the system-message and token-usage limitations;
- the selected trial and agent concurrency;
- root free space at setup.

## 5. Run and validate one smoke trial

Use the same model, effort, endpoint, image, task snapshot, and agent as the
full job. The representative task used by the main runbook is:

```bash
export COPILOT_PROXY_BASE_URL=http://127.0.0.1:<PORT>/v1
export TMPDIR=/mnt/datadrive/<USER>/handbook-tmp
unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY

.venv/bin/harbor run \
  -p "$TASKS_SNAPSHOT/finance_meridian_partners_19d57538" \
  --agent agent_harness.openhands_agent:OpenHandsAgent \
  -m "copilot/<EXACT_MODEL_ID>" \
  -k 1 \
  -n 1 \
  --n-concurrent-agents 1 \
  --ak reasoning_effort="<EFFORT>" \
  --ak api_mode=chat_completions \
  --ak log_completions=true \
  --job-name "$JOB_NAME-smoke" \
  -o "$JOBS_DIR"
```

Do not launch the full run until all smoke checks pass:

1. `exception_info` is null.
2. `agent_result.metadata.stopped_reason` is not `error`.
3. The verifier reward is numeric and in `[0, 1]`.
4. At least one substantive MCP tool was invoked.
5. `openhands_run_config.json` contains the exact `copilot/<id>`, effort, and
   `chat_completions`.
6. `request_protocol.json` reports:
   - `model=openai/<id>`;
   - `api_mode=chat_completions`;
   - `reasoning_parameter=extra_body.reasoning.effort`;
   - the confirmed effort;
   - `provider_transport=github_copilot_vscode_extension`;
   - exact request/advertised/response model validation;
   - `system_message_transport=handbook-system-instructions-v1`;
   - `token_usage_reporting=unavailable_from_proxy`;
   - no unapproved generation parameters.
7. The run log uses an ephemeral authenticated relay URL, not the direct
   loopback extension URL from inside Docker.
8. The extension Output channel shows the exact requested model and nested
   reasoning object.
9. Root storage remains adequate for the chosen concurrency.

`n_input_tokens`, `n_output_tokens`, and cost are expected to be null because
the extension reports zero usage and the harness converts that to unavailable.
A smoke score measures only that one attempt; it is not a benchmark score.

### Observed Opus 4.8 high-effort failure signature

On 2026-09-17, a smoke using `copilot/claude-opus-4.8`,
`reasoning_effort=high`, extension 0.1.0, and the representative finance task
passed model discovery, the trivial reasoning probe, MCP startup, relay
authentication, and request-protocol validation. The first substantive request
contained the wrapped system instructions, user request, and 84 tools. It did
not produce a response or tool call.

LiteLLM logged an `APITimeoutError` after about 30 minutes and started a
request-level retry. The retry also did not return before Harbor enforced the
3,600-second agent timeout. Harbor recorded:

```text
exception_type: AgentTimeoutError
exception_message: Agent execution timed out after 3600.0 seconds
agent_result.metadata: null
reward: 0.3333
```

This is an infrastructure-error smoke, not a valid partial benchmark score.
Do not start the full 260-trial job from this state, and do not assume more
parallel containers will fix it. Parallelism would multiply stuck requests
until the extension/model path can complete at least one substantive smoke
within the published task timeout.

The extension's Output channel showed the substantive request beginning with
the exact model and nested high effort, but never logged a corresponding
response. The Copilot Chat log likewise had no completion record for that
request. Preserve all three artifacts when investigating:

- the trial `result.json`;
- `agent/run-openhands.log`;
- the `GH Copilot Server` and GitHub Copilot Chat output logs.

## 6. Configure and launch the full job

A conservative full-job configuration is:

```yaml
job_name: <JOB_NAME>
jobs_dir: /mnt/datadrive/<USER>/handbook-jobs
n_attempts: 4
n_concurrent_trials: 1
retry:
  max_retries: 10
  include_exceptions:
    - RuntimeError
  wait_multiplier: 2.0
  min_wait_sec: 30.0
  max_wait_sec: 300.0
agents:
  - name: agent_harness.openhands_agent:OpenHandsAgent
    model_name: copilot/<EXACT_MODEL_ID>
    n_concurrent: 1
    kwargs:
      reasoning_effort: <EFFORT>
      api_mode: chat_completions
datasets:
  - path: /mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>.tasks
```

Concurrency controls are distinct:

- `n_concurrent_trials` controls simultaneous Harbor task pipelines.
- `agents[].n_concurrent` controls simultaneous model-driven agent phases.

With `2` trials and `1` agent, Harbor can overlap environment setup and
verification but only one trial sends model requests. To run two model loops
in parallel, both limits must permit two. Parallel model loops can reduce wall
time, but they also increase Copilot quota pressure, extension load, live
containers, and root-disk use. Validate parallel load separately and start a
new immutable result set if concurrency or request behavior changes.

Do not include `log_completions=true` in the full configuration unless full
payload retention is explicitly required.

Launch Harbor in `tmux`, exporting the Copilot URL inside the session:

```bash
tmux new-session -d -s handbook-copilot \
  -c /home/<USER>/handbook \
  "unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY && \
   export COPILOT_PROXY_BASE_URL='http://127.0.0.1:<PORT>/v1' && \
   export TMPDIR='/mnt/datadrive/<USER>/handbook-tmp' && \
   exec .venv/bin/harbor job start \
     --config '/mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>.config.yaml' \
     >> '/mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>.launch.log' 2>&1"
```

`tmux` protects Harbor from an SSH disconnect, but it does not host the model
server. Keep the remote VS Code extension host alive and do not reload its
window during the run. If the extension stops, the per-trial relays fail
closed and affected trials are infrastructure failures.

After Harbor creates `lock.json`, preserve and validate the semantic lock
baseline as described in the main runbook.

## 7. Monitor, recover, and score

Run the progress reporter in a second `tmux` session:

```bash
tmux new-session -d -s handbook-copilot-report \
  -c /home/<USER>/handbook \
  ".venv/bin/python scripts/benchmark_progress.py \
     /mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME> \
     --watch 30 \
     >> /mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>.progress.log 2>&1"
```

Monitor:

- Harbor's completed/running/pending/error/retry counts;
- the extension Output channel for exact model selection and responses;
- agent logs for MCP activity, proxy failures, and model timeouts;
- `df -h / /mnt/datadrive`;
- active container count and writable-layer growth.

Resume only infrastructure failures. Export `COPILOT_PROXY_BASE_URL` again in
every resume process. Never retry a valid low or zero reward.

Final acceptance is the main runbook's 260-result check with these
Copilot-specific substitutions:

- compare `copilot_proxy_base_url`, not a TRAPI URL;
- require `copilot/<exact-id>` in Harbor/run configs and
  `openai/<exact-id>` in the in-container request protocol;
- require the Copilot transport, model-validation, system-message-transport,
  and unavailable-token-usage fields;
- allow null token and cost totals;
- compare every request protocol against the reviewed smoke protocol;
- require exactly four valid attempts for every one of the 65 tasks.

Report strict pass@1, mean fractional score, pass@4, valid trials,
infrastructure errors/retries, concurrency, exact model/effort/API mode, and
all known protocol limitations. Do not claim exact equivalence to a native
system-message API or to an unpublished private serving configuration.
