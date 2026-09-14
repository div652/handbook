# HANDBOOK TRAPI Benchmark Runbook

This runbook is the operational source of truth for running HANDBOOK through
Microsoft TRAPI with the bundled Harbor/OpenHands harness. It is intended for a
human operator or a delegated coding agent.

Read this document completely before starting, resuming, or modifying a
benchmark job.

## 1. Non-negotiable rules

### Confirm the variable inputs

Never reuse a model or reasoning setting from an earlier job without explicit
confirmation. Before doing any setup or API call, ask the operator for:

1. The exact TRAPI instance/API path or full OpenAI-compatible base URL.
2. The exact TRAPI deployment name to pass as the Harbor model.
3. The requested reasoning effort.
4. The expected API mode (`responses` or `chat_completions`), to be verified
   against the pinned OpenHands SDK during the smoke test.
5. Whether this is a smoke test, a subset, or the full 65-task leaderboard run.
6. The number of attempts if it differs from the leaderboard's four attempts.

Use placeholders in notes and templates until these values are confirmed:

```text
<TRAPI_OPENAI_BASE_URL>
<TRAPI_MODEL_DEPLOYMENT>
<REASONING_EFFORT>
<API_MODE>
<JOB_NAME>
<JOBS_DIR>
```

The display name of a model is not necessarily its deployment name. Supported
reasoning values can also differ by deployment. Probe the selected deployment;
do not infer its identifier or capabilities from a previous run.

### Protect credentials

- Never store an Azure bearer token in `.env`, source code, job configuration,
  documentation, shell history, or logs.
- Never print a bearer token while testing authentication.
- Never commit `.env`.
- The model deployment name and reasoning effort are configuration, not
  credentials, but they must still be parameterized because they can change.
- Check logs for accidental secret exposure before sharing them.

### Protect the shared machine

- This machine is shared. Never run broad cleanup commands such as
  `docker system prune`, `docker image prune -a`, or recursive deletion outside
  a specifically identified job directory.
- Never delete containers, images, caches, or files whose ownership is
  uncertain.
- Ask for authorization before deleting system or shared data.
- Store benchmark results and temporary files on the large data drive, but
  remember that Docker may still use the root filesystem.

### Preserve benchmark validity

- Keep one model deployment, reasoning setting, and API mode for the entire
  job.
- Do not combine results from different models, reasoning efforts, harness
  versions, repository commits, or task revisions.
- Do not retry legitimate low scores.
- Exclude and rerun only infrastructure failures.
- Do not continue a failed trial from its partially modified environment for an
  official score. A valid retry starts from the task's clean initial state.

## 2. What the benchmark does

HANDBOOK contains 65 stateful tasks covering finance, HR, insurance, logistics,
and medical workflows. Each task supplies:

- `instruction.md`: the user request;
- `system_prompt.md`: the complete task-specific system prompt;
- `environment/`: the task container and initial service state;
- `task.toml`: resource and timeout settings;
- verifier code and rubric criteria.

The execution chain is:

```text
Harbor
  -> task Docker container
  -> OpenHands agent loop
  -> remote model through TRAPI
  -> MCP proxy
  -> filesystem/document and mock business-service tools
  -> deterministic verifier
```

The model does not directly read host paths. It works through the tools exposed
inside the isolated task container.

The released harness uses:

- `agent_harness.openhands_agent:OpenHandsAgent`;
- OpenHands SDK 1.28.1 in the current image;
- a maximum of 200 tool calls per trial;
- a 3,600-second agent timeout from each task;
- a 300-second MCP tool timeout;
- a 600-second model-request timeout;
- a 1,000,000-character tool-observation limit;
- the task's `system_prompt.md` as the full system prompt;
- the task's `instruction.md` as the user message.

## 3. Published protocol and comparison target

Primary sources:

- Paper: <https://arxiv.org/pdf/2607.25398>
- Leaderboard: <https://surgehq.ai/benchmarks/handbook>
- Repository: <https://github.com/surge-ai/handbook>

The leaderboard configuration is:

```text
65 tasks x 4 attempts per task = 260 valid trials
```

Strict success requires every rubric criterion to pass. In this verifier,
`reward == 1.0` is therefore a strict pass. A reward below 1.0 is useful partial
credit but is a strict failure.

Report at least:

- strict pass@1: strict-passing valid trials divided by valid trials;
- average score: mean fractional verifier reward over valid trials;
- valid-trial count;
- infrastructure-error count and retry count;
- per-task attempt counts;
- optionally, pass@4 and per-domain scores.

Because every task has exactly four valid attempts, the fraction of strict
passes over all 260 trials equals the average of each task's four-attempt strict
success fraction.

The paper and website do not disclose the exact API deployment identifier,
endpoint, concurrency, or every provider-side default. Record these limitations
instead of claiming an exact private-serving reproduction.

Match comparison rows by both model and reasoning effort. Recheck the primary
source and its date before citing a number; do not compare a run to a row with
a different reasoning setting.

## 4. Required repository and runtime state

Start from the repository root:

```bash
cd /home/agarwaldi/handbook
```

Require a committed, clean repository before the smoke test or full run:

```bash
git rev-parse HEAD
git ls-remote origin HEAD
if [ -n "$(git status --porcelain=v1 --untracked-files=all)" ]; then
  git status --short
  echo "Commit or remove every repository change before benchmarking." >&2
  exit 1
fi
```

This includes untracked files as well as tracked edits. Review
`git status --ignored --short`; only expected ignored runtime paths such as
`.env`, `.venv`, `jobs/`, and Python caches are permitted. The Docker context
and task snapshot below are exported from tracked files at `HEAD`, so ignored
files cannot enter those inputs. Do not benchmark from an editable dirty
worktree: a commit alone does not identify uncommitted changes to tasks,
prompts, tools, the harness, or the verifier. Do not silently update the
repository during an evaluation.

Count the tasks:

```bash
find tasks -mindepth 2 -maxdepth 2 -name task.toml | wc -l
```

For the current benchmark release, this must be `65`.

Create or verify the Python environment:

```bash
(cd agent_harness && uv lock --check)
UV_PROJECT_ENVIRONMENT="$PWD/.venv" \
  uv sync --project agent_harness --frozen --python 3.13
test "$(.venv/bin/harbor --version)" = "0.22.0"
.venv/bin/python --version
docker compose version
```

This runbook is audited against Harbor 0.22.0. Stop if the version assertion
fails. Do not assume another Harbor release has identical config, retry,
resume, lock, or result semantics. Harbor requires the `docker compose`
subcommand; legacy `docker-compose` alone is insufficient.

The two in-repository copies of the in-container runner must match:

```bash
sha256sum \
  agent_harness/src/agent_harness/openhands_runner.py \
  docker/openhands-runner/openhands_runner.py
```

These two checksums must match. Section 7 builds and verifies an immutable
job-specific base image. Do not use the shared mutable `handbook_base:latest`
tag for an official run.

## 5. TRAPI authentication and configuration

Authenticate interactively with the required Azure account:

```bash
az login --scope api://trapi/.default
```

Do not automate the interactive login or request credentials from the operator.
The operator should complete it.

Check login validity without printing the token:

```bash
az account get-access-token \
  --scope api://trapi/.default \
  --query expiresOn \
  --output tsv
```

The local `.env` should contain only non-secret routing configuration:

```dotenv
TRAPI_AZURE_SCOPE=api://trapi/.default
OPENAI_BASE_URL=<TRAPI_OPENAI_BASE_URL>
```

It must not contain `OPENAI_API_KEY`. Confirm `.env` is ignored:

```bash
git check-ignore .env
if grep -Eq '^(OPENAI_API_KEY|ANTHROPIC_API_KEY|OPENROUTER_API_KEY|GEMINI_API_KEY)=' .env; then
  echo "TRAPI .env must not contain provider credentials." >&2
  exit 1
fi
```

The current harness fails closed unless the TRAPI URL uses HTTPS, has host
`trapi.research.microsoft.com`, and has a path ending in `/openai/v1`. This
validation occurs before token acquisition, preventing a missing or public
OpenAI URL from receiving the Azure bearer. A future TRAPI hostname or API
shape requires a reviewed code change, not merely an `.env` edit.

`OpenHandsAgent` obtains a fresh Azure CLI token on the host for each trial. It
writes the token to a mode-`0600` temporary host file, uploads that file under a
randomized path in the task container, and deletes the host copy immediately.
The in-container shell reads and deletes the uploaded file before starting the
runner. The bearer value is never supplied to Docker Compose as an environment
argument and is not written into the job configuration or `.env`. In TRAPI
mode, the host wrapper forwards only the non-secret `OPENAI_BASE_URL`; unrelated
provider keys inherited by the shell are deliberately excluded.

This protects against token disclosure in ordinary process command lines, not
against a hostile administrator. Root and members of the Docker group can
inspect containers, process environments, files, and memory. Run only on a
trusted host whose privileged and Docker-capable users are authorized to access
TRAPI. If that condition is false, stop rather than relying on process masking.

### Important resume behavior

`harbor job resume` does not accept or reload the original `.env` automatically.
Every resumed process must explicitly source `.env` before invoking Harbor:

```bash
set -a
. ./.env
set +a
unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY
```

Failing to do this makes the OpenAI-compatible client fall back to the wrong
endpoint or an empty key. Symptoms include:

```text
Incorrect API key provided: None
```

Those are infrastructure failures, not model failures.

## 6. Model and reasoning preflight

The future operator or agent must not hardcode a previous run's values. Confirm:

```bash
MODEL="openai/<TRAPI_MODEL_DEPLOYMENT>"
REASONING_EFFORT="<REASONING_EFFORT>"
API_MODE="<API_MODE>"
```

Keep the Harbor provider prefix:

```text
openai/<TRAPI_MODEL_DEPLOYMENT>
```

Probe the chosen model with a minimal request before building a full job. This
uses only the already-required Azure CLI and the OpenAI package installed
through the harness dependencies. The token remains in Python memory and is
never printed or passed in process arguments:

```bash
export TRAPI_AZURE_SCOPE="api://trapi/.default"
export TRAPI_MODEL_DEPLOYMENT="<TRAPI_MODEL_DEPLOYMENT>"
export REASONING_EFFORT="<REASONING_EFFORT>"
export API_MODE="<API_MODE>"
set -a
. ./.env
set +a
unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY

.venv/bin/python - <<'PY'
import os
import subprocess
from urllib.parse import urlparse

from openai import OpenAI

base_url = os.environ["OPENAI_BASE_URL"]
parsed = urlparse(base_url)
assert parsed.scheme == "https"
assert parsed.hostname == "trapi.research.microsoft.com"
assert parsed.path.rstrip("/").endswith("/openai/v1")
assert not (parsed.username or parsed.password or parsed.query or parsed.fragment)

token = subprocess.run(
    [
        "az",
        "account",
        "get-access-token",
        "--scope",
        os.environ["TRAPI_AZURE_SCOPE"],
        "--query",
        "accessToken",
        "--output",
        "tsv",
    ],
    check=True,
    capture_output=True,
    text=True,
    timeout=30,
).stdout.strip()
assert token, "Azure CLI returned an empty token"

client = OpenAI(
    base_url=base_url,
    api_key=token,
)
if os.environ["API_MODE"] == "responses":
    response = client.responses.create(
        model=os.environ["TRAPI_MODEL_DEPLOYMENT"],
        input="Reply with OK only.",
        reasoning={"effort": os.environ["REASONING_EFFORT"]},
        store=False,
    )
    assert response.output_text
elif os.environ["API_MODE"] == "chat_completions":
    response = client.chat.completions.create(
        model=os.environ["TRAPI_MODEL_DEPLOYMENT"],
        messages=[{"role": "user", "content": "Reply with OK only."}],
        reasoning_effort=os.environ["REASONING_EFFORT"],
    )
    assert response.choices[0].message.content
else:
    raise ValueError(f"unsupported API_MODE: {os.environ['API_MODE']!r}")
print("TRAPI model probe succeeded")
PY
```

This is a connectivity and endpoint-capability probe. The one-task smoke test
is the authoritative end-to-end check of the OpenHands/LiteLLM request path.

Treat an unsupported reasoning value as a configuration error. Ask the operator
to choose from values accepted by that deployment.

Reasoning has a different wire shape in each API:

Responses API:

```json
{"reasoning": {"effort": "<REASONING_EFFORT>"}}
```

Chat Completions API:

```json
{"reasoning_effort": "<REASONING_EFFORT>"}
```

Do not test one API mode and assume the harness uses the other. The runbook
harness requires `api_mode` and fails before the first model call if the pinned
SDK selects a different path or omits the requested reasoning effort. The
selected path can change with the model; inspect and confirm it rather than
copying a previous job. The bundled adapter also routes summarization calls
through Responses when the main model uses Responses; otherwise the pinned
OpenHands condenser would silently use Chat Completions.

### Provider defaults are not automatically safe

OpenHands SDK 1.28.1 defaults its `reasoning_effort` field to `high`. Therefore,
omitting the job's reasoning setting does not reliably mean "use the provider
default." Always confirm and set the intended effort explicitly unless the
harness has been audited to preserve a true provider default.

Do not invent values for temperature, `top_p`, seed, or output limits when the
target protocol does not specify them. The harness writes the SDK-selected,
non-secret settings to each trial's `agent/request_protocol.json`. Review that
artifact during the smoke test and preserve it as provenance. Any sampling
value shown there is harness behavior unless the benchmark publisher disclosed
it. Re-audit the artifact after changing the model, OpenHands, or LiteLLM.

The runner forces LiteLLM to use the model capability/cost map bundled in the
pinned package instead of downloading the mutable map from GitHub. The bundled
map's SHA-256 and LiteLLM's reported source are recorded in
`request_protocol.json`; the run fails before the first model call unless the
source is local and explicitly forced.

## 7. Storage and Docker preflight

Check RAM and both filesystems:

```bash
free -h
df -h / /mnt/datadrive
docker info --format 'Docker root: {{.DockerRootDir}}'
docker system df
```

Job output on `/mnt/datadrive` does not move Docker storage. If Docker reports:

```text
Docker root: /var/lib/docker
```

then task images and writable container layers still consume the root
filesystem.

Operational guidance:

- Put `jobs_dir`, `TMPDIR`, and launcher logs on `/mnt/datadrive`.
- Prefer at least several GiB of root headroom before a 260-trial run; 5 GiB is
  a reasonable minimum operating target, not an official benchmark requirement.
- Stop and investigate if root approaches exhaustion.
- On a shared machine, do not prune Docker globally.
- Remove only specifically identified artifacts known to belong to the current
  job, and only with authorization.
- The preferred long-term fix is a dedicated Docker data root on the large data
  drive, configured by the system administrator.

Prepare directories:

```bash
mkdir -p \
  /mnt/datadrive/<USER>/handbook-jobs \
  /mnt/datadrive/<USER>/handbook-tmp
```

Materialize the Docker build context from files tracked at `HEAD`; ignored
bytecode, caches, local environments, and secrets must not affect the image.
Build a temporary base tag, then give the resulting image a tag derived from
its full image ID. This avoids the shared mutable `handbook_base:latest` tag:

```bash
set -euo pipefail
export JOB_NAME="<JOB_NAME>"
export JOBS_DIR="/mnt/datadrive/<USER>/handbook-jobs"
export MODEL="openai/<TRAPI_MODEL_DEPLOYMENT>"
export API_MODE="<API_MODE>"
export DOCKER_CONTEXT="$JOBS_DIR/$JOB_NAME.docker-context"
TEMP_BASE_TAG="handbook_base:build-$(date +%s)-$$"

.venv/bin/python scripts/materialize_git_tree.py \
  --repository . \
  --source docker \
  --destination "$DOCKER_CONTEXT"
DOCKER_BUILDKIT=1 docker build -t "$TEMP_BASE_TAG" "$DOCKER_CONTEXT"
BASE_IMAGE_ID="$(docker image inspect "$TEMP_BASE_TAG" --format '{{.Id}}')"
BASE_IMAGE_TAG="handbook_base:${BASE_IMAGE_ID#sha256:}"

if EXISTING_ID="$(docker image inspect "$BASE_IMAGE_TAG" \
    --format '{{.Id}}' 2>/dev/null)"; then
  test "$EXISTING_ID" = "$BASE_IMAGE_ID"
else
  docker tag "$TEMP_BASE_TAG" "$BASE_IMAGE_TAG"
fi
docker image rm "$TEMP_BASE_TAG"

SELECTED_API_MODE="$(
  docker run --rm \
    --entrypoint /app/openhands-runner/.venv/bin/python \
    -e OPENHANDS_SUPPRESS_BANNER=1 \
    "$BASE_IMAGE_TAG" \
    -c 'import sys; from openhands.sdk import LLM; llm = LLM(model=sys.argv[1], api_key="unused"); print("responses" if llm.uses_responses_api() else "chat_completions")' \
    "$MODEL"
)"
test "$SELECTED_API_MODE" = "$API_MODE"
```

Materialize an immutable task snapshot from files tracked at `HEAD`, outside
the repository. Ignored and untracked files are excluded. Its Dockerfiles refer
to the content-named base tag, so another checkout rebuilding
`handbook_base:latest` cannot change this job's parent image:

```bash
export TASKS_SNAPSHOT="$JOBS_DIR/$JOB_NAME.tasks"
.venv/bin/python scripts/materialize_tasks.py \
  --repository . \
  --source tasks \
  --destination "$TASKS_SNAPSHOT" \
  --base-image "$BASE_IMAGE_TAG" \
  --expected-count 65

docker run --rm "$BASE_IMAGE_TAG" \
  sha256sum /app/openhands-runner/openhands_runner.py
sha256sum agent_harness/src/agent_harness/openhands_runner.py
```

The two runner checksums must match. The materializer refuses to overwrite an
existing snapshot or accept a task Dockerfile with an unexpected parent. The
content-named tag prevents accidental cross-job replacement; the trusted-host
requirement still applies because a Docker administrator can deliberately
retag or remove any local image. Before each model loop, the host agent also
checks that a content-named parent still resolves to the image ID encoded in
its tag. A mismatch fails the trial as infrastructure rather than admitting a
mixed-image result.

### Create immutable run metadata

After the endpoint, model, reasoning effort, API mode, base image, and task
snapshot are confirmed, record them in a non-secret metadata file next to the
job. This is the canonical expected configuration for every launch, resume,
and final check:

```bash
export JOB_NAME="<JOB_NAME>"
export JOBS_DIR="/mnt/datadrive/<USER>/handbook-jobs"
export MODEL="openai/<TRAPI_MODEL_DEPLOYMENT>"
export REASONING_EFFORT="<REASONING_EFFORT>"
export API_MODE="<API_MODE>"
export TASKS_SNAPSHOT="$JOBS_DIR/$JOB_NAME.tasks"
export DOCKER_CONTEXT="$JOBS_DIR/$JOB_NAME.docker-context"

set -a
. ./.env
set +a
unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY

export BENCHMARK_METADATA="$JOBS_DIR/$JOB_NAME.metadata.json"
.venv/bin/python - <<'PY'
import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from dirhash import dirhash
from dotenv import dotenv_values

repository_status = subprocess.run(
    ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
assert not repository_status, (
    "repository is dirty; commit or remove all tracked and untracked changes"
)

required = {
    "job_name": os.environ["JOB_NAME"],
    "model": os.environ["MODEL"],
    "reasoning_effort": os.environ["REASONING_EFFORT"],
    "api_mode": os.environ["API_MODE"],
    "trapi_azure_scope": os.environ["TRAPI_AZURE_SCOPE"],
    "openai_base_url": os.environ["OPENAI_BASE_URL"],
}
secret_names = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
}
assert not (secret_names & dotenv_values(".env").keys()), (
    ".env contains a provider credential; TRAPI uses Azure CLI token staging"
)
assert not (secret_names & os.environ.keys()), (
    "remove inherited provider credentials before a TRAPI run"
)
assert required["api_mode"] in {"responses", "chat_completions"}
parsed_base_url = urlparse(required["openai_base_url"])
assert parsed_base_url.scheme == "https"
assert parsed_base_url.hostname == "trapi.research.microsoft.com"
assert parsed_base_url.path.rstrip("/").endswith("/openai/v1")
assert not (
    parsed_base_url.username
    or parsed_base_url.password
    or parsed_base_url.query
    or parsed_base_url.fragment
)

required["repository_commit"] = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
required["agent_harness_lock_sha256"] = hashlib.sha256(
    Path("agent_harness/uv.lock").read_bytes()
).hexdigest()
required["runner_source_sha256"] = hashlib.sha256(
    Path("agent_harness/src/agent_harness/openhands_runner.py").read_bytes()
).hexdigest()
required["host_agent_sha256"] = hashlib.sha256(
    Path("agent_harness/src/agent_harness/openhands_agent.py").read_bytes()
).hexdigest()
tasks_snapshot = Path(os.environ["TASKS_SNAPSHOT"]).resolve()
task_files = sorted(tasks_snapshot.glob("*/task.toml"))
dockerfiles = sorted(tasks_snapshot.glob("*/environment/Dockerfile"))
assert len(task_files) == len(dockerfiles) == 65
required["tasks_snapshot"] = str(tasks_snapshot)
required["tasks_snapshot_sha256"] = dirhash(tasks_snapshot, "sha256")
required["task_names"] = [path.parent.name for path in task_files]
docker_context = Path(os.environ["DOCKER_CONTEXT"]).resolve()
required["docker_context"] = str(docker_context)
required["docker_context_sha256"] = dirhash(docker_context, "sha256")
base_image_tags = {
    path.read_text().splitlines()[0].removeprefix("FROM ")
    for path in dockerfiles
}
assert len(base_image_tags) == 1, base_image_tags
required["handbook_base_image_tag"] = base_image_tags.pop()
required["harbor_version"] = subprocess.run(
    [".venv/bin/harbor", "--version"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
required["python_runtime"] = subprocess.run(
    [".venv/bin/python", "-c", "import sys; print(sys.version)"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
required["python_packages"] = subprocess.run(
    ["uv", "pip", "freeze", "--python", ".venv/bin/python"],
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()
required["docker_version"] = json.loads(
    subprocess.run(
        ["docker", "version", "--format", "{{json .}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
)
required["docker_compose_version"] = subprocess.run(
    ["docker", "compose", "version", "--short"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
required["handbook_base_image_id"] = subprocess.run(
    [
        "docker",
        "image",
        "inspect",
        required["handbook_base_image_tag"],
        "--format",
        "{{.Id}}",
    ],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
assert required["handbook_base_image_tag"].endswith(
    required["handbook_base_image_id"].removeprefix("sha256:")
)
required["runner_image_sha256"] = subprocess.run(
    [
        "docker",
        "run",
        "--rm",
        required["handbook_base_image_tag"],
        "sha256sum",
        "/app/openhands-runner/openhands_runner.py",
    ],
    check=True,
    capture_output=True,
    text=True,
).stdout.split()[0]
assert required["runner_image_sha256"] == required["runner_source_sha256"]
required["runner_packages"] = json.loads(
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            required["handbook_base_image_tag"],
            "/app/openhands-runner/.venv/bin/python",
            "-c",
            (
                "import importlib.metadata as m,json;"
                "print(json.dumps({p:m.version(p) for p in "
                "('openhands-sdk','litellm')}))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
)
required["job_config"] = {
    "job_name": required["job_name"],
    "jobs_dir": str(Path(os.environ["JOBS_DIR"]).resolve()),
    "n_attempts": 4,
    "n_concurrent_trials": 2,
    "retry": {
        "max_retries": 10,
        "include_exceptions": ["RuntimeError"],
        "wait_multiplier": 2.0,
        "min_wait_sec": 30.0,
        "max_wait_sec": 300.0,
    },
    "agents": [
        {
            "name": "agent_harness.openhands_agent:OpenHandsAgent",
            "model_name": required["model"],
            "n_concurrent": 1,
            "kwargs": {
                "reasoning_effort": required["reasoning_effort"],
                "api_mode": required["api_mode"],
            },
        }
    ],
    "datasets": [{"path": required["tasks_snapshot"]}],
}
required["created_at_utc"] = datetime.datetime.now(
    datetime.UTC
).isoformat(timespec="seconds")

path = Path(os.environ["BENCHMARK_METADATA"])
path.parent.mkdir(parents=True, exist_ok=True)
assert not path.exists(), f"refusing to overwrite existing metadata: {path}"
path.write_text(json.dumps(required, indent=2) + "\n")
path.chmod(0o444)
print(path)
PY
```

Do not overwrite this file for a resumed job. Before every launch or resume,
verify that the current non-secret environment and repository still match it:

```bash
.venv/bin/python - <<'PY'
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml
from dirhash import dirhash
from harbor.models.job.config import JobConfig

expected = json.loads(Path(os.environ["BENCHMARK_METADATA"]).read_text())
repository_status = subprocess.run(
    ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
assert not repository_status, (
    "repository is dirty; commit or remove all tracked and untracked changes"
)

tasks_snapshot = Path(expected["tasks_snapshot"])
docker_context = Path(expected["docker_context"])
task_files = sorted(tasks_snapshot.glob("*/task.toml"))
dockerfiles = sorted(tasks_snapshot.glob("*/environment/Dockerfile"))
base_image_tags = {
    path.read_text().splitlines()[0].removeprefix("FROM ")
    for path in dockerfiles
}
assert len(task_files) == len(dockerfiles) == 65
assert [path.parent.name for path in task_files] == expected["task_names"]
assert base_image_tags == {expected["handbook_base_image_tag"]}

observed = {
    "model": os.environ["MODEL"],
    "reasoning_effort": os.environ["REASONING_EFFORT"],
    "api_mode": os.environ["API_MODE"],
    "trapi_azure_scope": os.environ["TRAPI_AZURE_SCOPE"],
    "openai_base_url": os.environ["OPENAI_BASE_URL"],
    "repository_commit": subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip(),
    "agent_harness_lock_sha256": hashlib.sha256(
        Path("agent_harness/uv.lock").read_bytes()
    ).hexdigest(),
    "runner_source_sha256": hashlib.sha256(
        Path("agent_harness/src/agent_harness/openhands_runner.py").read_bytes()
    ).hexdigest(),
    "host_agent_sha256": hashlib.sha256(
        Path("agent_harness/src/agent_harness/openhands_agent.py").read_bytes()
    ).hexdigest(),
    "tasks_snapshot_sha256": dirhash(tasks_snapshot, "sha256"),
    "docker_context_sha256": dirhash(docker_context, "sha256"),
    "harbor_version": subprocess.run(
        [".venv/bin/harbor", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip(),
    "python_runtime": subprocess.run(
        [".venv/bin/python", "-c", "import sys; print(sys.version)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip(),
    "python_packages": subprocess.run(
        ["uv", "pip", "freeze", "--python", ".venv/bin/python"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines(),
    "docker_version": json.loads(
        subprocess.run(
            ["docker", "version", "--format", "{{json .}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    ),
    "docker_compose_version": subprocess.run(
        ["docker", "compose", "version", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip(),
    "handbook_base_image_id": subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            expected["handbook_base_image_tag"],
            "--format",
            "{{.Id}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip(),
    "runner_image_sha256": subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            expected["handbook_base_image_tag"],
            "sha256sum",
            "/app/openhands-runner/openhands_runner.py",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()[0],
    "runner_packages": json.loads(
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                expected["handbook_base_image_tag"],
                "/app/openhands-runner/.venv/bin/python",
                "-c",
                (
                    "import importlib.metadata as m,json;"
                    "print(json.dumps({p:m.version(p) for p in "
                    "('openhands-sdk','litellm')}))"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    ),
}
for key, value in observed.items():
    assert expected[key] == value, (
        f"{key} changed: expected {expected[key]!r}, observed {value!r}"
    )

if job_config_path := os.environ.get("JOB_CONFIG"):
    job_config = yaml.safe_load(Path(job_config_path).read_text())
    assert job_config == expected["job_config"], (
        "job config differs from the immutable protocol"
    )
if job_dir := os.environ.get("JOB_DIR"):
    effective_config_path = Path(job_dir) / "config.json"
    if effective_config_path.exists():
        intended_config = JobConfig.model_validate(expected["job_config"])
        effective_config = JobConfig.model_validate_json(
            effective_config_path.read_text()
        )
        assert effective_config.model_dump(
            mode="json"
        ) == intended_config.model_dump(mode="json"), (
            "Harbor effective config differs from the immutable protocol"
        )
if protocol_lock_path := os.environ.get("PROTOCOL_LOCK"):
    protocol_lock_file = Path(protocol_lock_path)
    protocol_lock = json.loads(protocol_lock_file.read_text())
    metadata_digest = hashlib.sha256(
        Path(os.environ["BENCHMARK_METADATA"]).read_bytes()
    ).hexdigest()
    assert protocol_lock["metadata_sha256"] == metadata_digest
    assert protocol_lock["job_config_sha256"] == hashlib.sha256(
        Path(os.environ["JOB_CONFIG"]).read_bytes()
    ).hexdigest()
    assert protocol_lock["request_protocol"]["api_mode"] == expected["api_mode"]
    assert (
        protocol_lock["request_protocol"]["reasoning_effort"]
        == expected["reasoning_effort"]
    )
print("Benchmark metadata matches")
PY
```

## 8. Run a smoke test first

Use the same model, reasoning effort, endpoint, image, and agent that the full
job will use. Run one representative task with one attempt and one agent.

Example:

```bash
MODEL="openai/<TRAPI_MODEL_DEPLOYMENT>"
REASONING_EFFORT="<REASONING_EFFORT>"
API_MODE="<API_MODE>"
JOBS_DIR="/mnt/datadrive/<USER>/handbook-jobs"
TMPDIR="/mnt/datadrive/<USER>/handbook-tmp"
TASKS_SNAPSHOT="$JOBS_DIR/<JOB_NAME>.tasks"
unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY

TMPDIR="$TMPDIR" .venv/bin/harbor run \
  -p "$TASKS_SNAPSHOT/finance_meridian_partners_19d57538" \
  --agent agent_harness.openhands_agent:OpenHandsAgent \
  -m "$MODEL" \
  -k 1 \
  -n 1 \
  --n-concurrent-agents 1 \
  --ak reasoning_effort="$REASONING_EFFORT" \
  --ak api_mode="$API_MODE" \
  --ak log_completions=true \
  --env-file .env \
  --job-name "<JOB_NAME>-smoke" \
  -o "$JOBS_DIR"
```

Validate the smoke test:

1. `exception_info` is null.
2. `agent_result.metadata.stopped_reason` is not `error`.
3. The uploaded `agent/openhands_run_config.json` contains the exact deployment
   and reasoning effort.
4. `agent/run-openhands.log` reports the intended TRAPI base URL.
5. At least one substantive smoke trial invokes MCP tools.
6. The verifier produces a numeric reward in `[0, 1]`.
7. No authentication token appears in logs or completion payloads.
8. `agent/request_protocol.json` reports the confirmed main and condenser API
   modes, reasoning parameter and effort. Review every recorded sampling
   parameter.
9. Its `litellm_model_cost_map` reports `source=local`,
   `is_env_forced=true`, and a 64-character bundled-map SHA-256.
10. The logged request payload agrees with `request_protocol.json`.

While the smoke agent is actively running, sample readable host process
arguments and verify that the real Azure token is absent. This is a regression
check, not proof about every instant in the lifetime of every process. The
file-staging design above is the security control; this check prints only
counts and can detect accidental reintroduction of an argument-based secret:

```bash
.venv/bin/python - <<'PY'
import pathlib
import subprocess

token = subprocess.run(
    [
        "az",
        "account",
        "get-access-token",
        "--scope",
        "api://trapi/.default",
        "--query",
        "accessToken",
        "--output",
        "tsv",
    ],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip().encode()

real = masked = 0
for path in pathlib.Path("/proc").glob("[0-9]*/cmdline"):
    try:
        command = path.read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    real += bool(token and token in command)
    masked += b"OPENAI_API_KEY=******" in command

print(f"process_argv_with_real_token={real}")
print(f"process_argv_with_masked_placeholder={masked}")
assert real == 0, "real bearer token is visible in host process arguments"
PY
```

`process_argv_with_masked_placeholder` is informational and may be zero. If
`process_argv_with_real_token` is nonzero, stop the run and fix the transport.
Do not use a point-in-time scan to claim that an untrusted shared host is safe.

A smoke reward is not a benchmark score. A low reward can be legitimate model
behavior; an authentication, provider, MCP, or container error is not.

Remove `log_completions=true` from the full run unless full payload retention is
explicitly needed. It increases artifact size and stores task content.

## 9. Recommended full-job configuration

Generate the full-job YAML from the canonical object already recorded in the
immutable metadata. Do not hand-copy a second configuration:

```bash
export JOB_NAME="<JOB_NAME>"
export JOBS_DIR="/mnt/datadrive/<USER>/handbook-jobs"
export JOB_CONFIG="$JOBS_DIR/$JOB_NAME.config.yaml"
export BENCHMARK_METADATA="$JOBS_DIR/$JOB_NAME.metadata.json"

.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

import yaml

metadata = json.loads(Path(os.environ["BENCHMARK_METADATA"]).read_text())
path = Path(os.environ["JOB_CONFIG"])
assert not path.exists(), f"refusing to overwrite existing job config: {path}"
path.write_text(yaml.safe_dump(metadata["job_config"], sort_keys=False))
path.chmod(0o444)
print(path)
PY
```

Bind the reviewed smoke-test request settings and the exact metadata/config
bytes before launching the full job:

```bash
export JOB_NAME="<JOB_NAME>"
export JOBS_DIR="/mnt/datadrive/<USER>/handbook-jobs"
export BENCHMARK_METADATA="$JOBS_DIR/$JOB_NAME.metadata.json"
export JOB_CONFIG="$JOBS_DIR/$JOB_NAME.config.yaml"
export PROTOCOL_LOCK="$JOBS_DIR/$JOB_NAME.protocol.json"
export SMOKE_JOB_DIR="$JOBS_DIR/$JOB_NAME-smoke"

.venv/bin/python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

metadata_path = Path(os.environ["BENCHMARK_METADATA"])
job_config_path = Path(os.environ["JOB_CONFIG"])
protocol_files = list(
    Path(os.environ["SMOKE_JOB_DIR"]).glob("*/agent/request_protocol.json")
)
assert len(protocol_files) == 1, (
    f"expected one smoke request protocol, found {len(protocol_files)}"
)
request_protocol = json.loads(protocol_files[0].read_text())
metadata = json.loads(metadata_path.read_text())
assert request_protocol["model"] == metadata["model"]
assert request_protocol["base_url"] == metadata["openai_base_url"]
assert request_protocol["api_mode"] == metadata["api_mode"]
assert request_protocol["condenser_api_mode"] == metadata["api_mode"]
assert request_protocol["reasoning_effort"] == metadata["reasoning_effort"]
model_cost_map = request_protocol["litellm_model_cost_map"]
assert model_cost_map["source"] == "local"
assert model_cost_map["is_env_forced"] is True
assert len(model_cost_map["sha256"]) == 64

protocol_lock = {
    "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
    "job_config_sha256": hashlib.sha256(job_config_path.read_bytes()).hexdigest(),
    "request_protocol": request_protocol,
}
path = Path(os.environ["PROTOCOL_LOCK"])
assert not path.exists(), f"refusing to overwrite protocol lock: {path}"
path.write_text(json.dumps(protocol_lock, indent=2) + "\n")
path.chmod(0o444)
print(path)
PY
```

Read `request_protocol` before proceeding. Confirm that its API mode, reasoning
wire parameter, effort, sampling parameters, storage flag, and reasoning-content
retention are intended. The paper and leaderboard do not disclose all of these
serving details, so retain the artifact and describe that limitation with the
result.

The two concurrency controls have different purposes:

- `n_concurrent_trials: 2` allows environment setup, verification, and cleanup
  to overlap.
- `agents[].n_concurrent: 1` permits only one token-heavy model loop at a time.

This is the recommended starting point for a shared TRAPI token quota. Do not
start with four concurrent agents unless measured quota evidence supports it.

In one observed run, two simultaneous model loops required 95 full-trial
retries by the time only 123 valid results had completed. The valid-attempt
yield was about 56 percent. Serializing only the agent phase preserves useful
pipeline parallelism without creating the same synchronized token pressure.

### Why Harbor retries are a last resort

OpenHands first retries an individual model request inside the live
conversation. This preserves the conversation and task state.

If those request retries are exhausted, Harbor performs a full-trial retry.
Harbor 0.22.0 deletes the failed trial directory and creates a fresh trial:

```python
shutil.rmtree(trial.paths.trial_dir, ignore_errors=True)
trial = await Trial.create(trial_config)
```

The prior model tokens and tool work have already been consumed, but the new
attempt cannot reuse them. This reset is necessary for a clean official trial,
but it is expensive.

For future harness development, prefer:

- honoring TRAPI's reported retry delay;
- adding jitter so agents do not retry simultaneously;
- using more patient request-level retries;
- routing all model calls through a shared token-bucket limiter.

Those improvements should prevent a transient 429 from escalating into a full
trial restart. Do not change retry behavior halfway through a result set without
recording and reviewing the comparability impact.

## 10. Launch detached from SSH

Do not run the full job as a child of an interactive Copilot or SSH process.
Start it in `tmux` from the beginning.

Example:

```bash
REPO="/home/<USER>/handbook"
JOB_NAME="<JOB_NAME>"
JOBS_DIR="/mnt/datadrive/<USER>/handbook-jobs"
JOB_CONFIG="$JOBS_DIR/$JOB_NAME.config.yaml"
TMP_DIR="/mnt/datadrive/<USER>/handbook-tmp"
LAUNCH_LOG="$JOBS_DIR/$JOB_NAME.launch.log"
MODEL="openai/<TRAPI_MODEL_DEPLOYMENT>"
REASONING_EFFORT="<REASONING_EFFORT>"
API_MODE="<API_MODE>"

export BENCHMARK_METADATA="$JOBS_DIR/$JOB_NAME.metadata.json"
export PROTOCOL_LOCK="$JOBS_DIR/$JOB_NAME.protocol.json"
export JOB_CONFIG MODEL REASONING_EFFORT API_MODE
set -a
. ./.env
set +a
unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY
# Run the immutable metadata verification from Section 7 now.

tmux new-session -d -s handbook-benchmark -c "$REPO" \
  "unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY && \
   set -a && . ./.env && set +a && \
   export TMPDIR='$TMP_DIR' && \
   exec .venv/bin/harbor job start \
     --config '$JOB_CONFIG' \
     --env-file .env \
     >> '$LAUNCH_LOG' 2>&1"
```

Check it:

```bash
tmux list-sessions
tmux list-panes -t handbook-benchmark \
  -F '#{pane_pid} #{pane_current_command} dead=#{pane_dead}'
```

Once Harbor has created `lock.json`, preserve a baseline before treating any
result as publishable:

```bash
set -euo pipefail
JOB_NAME="<JOB_NAME>"
JOBS_DIR="/mnt/datadrive/<USER>/handbook-jobs"
JOB_DIR="$JOBS_DIR/$JOB_NAME"
HARBOR_LOCK_BASELINE="$JOBS_DIR/$JOB_NAME.harbor-lock.json"
BENCHMARK_METADATA="$JOBS_DIR/$JOB_NAME.metadata.json"
export JOB_DIR HARBOR_LOCK_BASELINE BENCHMARK_METADATA
for _ in $(seq 1 60); do
  test -s "$JOB_DIR/lock.json" && break
  sleep 1
done
test -s "$JOB_DIR/lock.json"

.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

from harbor.models.job.config import JobConfig
from harbor.models.job.lock import JobLock

current_path = Path(os.environ["JOB_DIR"]) / "lock.json"
effective_config_path = Path(os.environ["JOB_DIR"]) / "config.json"
baseline_path = Path(os.environ["HARBOR_LOCK_BASELINE"])
metadata = json.loads(Path(os.environ["BENCHMARK_METADATA"]).read_text())
intended_config = JobConfig.model_validate(metadata["job_config"])
effective_config = JobConfig.model_validate_json(
    effective_config_path.read_text()
)
assert effective_config.model_dump(
    mode="json"
) == intended_config.model_dump(mode="json"), (
    "Harbor effective config differs from the immutable protocol"
)
current = JobLock.model_validate_json(current_path.read_text())
assert len(current.trials) == 260, "Harbor lock is not complete"
assert not baseline_path.exists(), (
    f"refusing to overwrite Harbor lock baseline: {baseline_path}"
)
baseline_path.write_text(current_path.read_text())
baseline_path.chmod(0o444)
print(baseline_path)
PY
```

The effective `config.json` comparison is mandatory because Harbor applies CLI
overrides after loading the YAML. Do not append launch-time overrides. Harbor
0.22.0 rewrites `lock.json` during a normal resume and may serialize set-valued
fields in a different order. Therefore, compare parsed `JobLock` objects rather
than raw file hashes. Never overwrite the baseline to accommodate a semantic
mid-run configuration change. If trials ran but the baseline was never
recorded, do not manufacture one retrospectively and call the run fully
reproducible.

Attach when needed:

```bash
tmux attach -t handbook-benchmark
```

Detach without stopping it by pressing `Ctrl+B`, then `D`.

## 11. Live progress report

Start the repository's report generator in a second detached session:

```bash
tmux new-session -d -s handbook-report \
  -c /home/<USER>/handbook \
  ".venv/bin/python scripts/benchmark_progress.py \
     /mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME> \
     --watch 30 \
     >> /mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>.progress.log 2>&1"
```

View the report:

```bash
watch -n 30 \
  cat /mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>/PROGRESS.md
```

The report distinguishes:

- completed logical trials;
- valid scored trials;
- outstanding errors;
- infrastructure retries;
- strict passes;
- tasks solved at least once;
- mean fractional score;
- root-disk headroom.

The report is informative during execution, but final acceptance requires the
checks in Section 15.

## 12. Monitoring and alert thresholds

Check at reasonable intervals:

```bash
JOB_DIR="/mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>"

jq '{
  updated_at,
  finished_at,
  n_total_trials,
  stats: (.stats | {
    n_completed_trials,
    n_errored_trials,
    n_running_trials,
    n_pending_trials,
    n_cancelled_trials,
    n_retries
  })
}' "$JOB_DIR/result.json"

docker ps -s
df -h / /mnt/datadrive
```

Inspect active agent health without printing credentials:

```bash
docker ps --format '{{.ID}} {{.Names}}'
```

For a task container:

```bash
docker exec <CONTAINER_ID> sh -c \
  'grep -n -E "Tool:|RateLimitError|AuthenticationError|Conversation run failed" \
   /logs/agent/run-openhands.log | tail -30'
```

Interpretation:

- A few request-level 429s followed by more tool calls mean recovery succeeded.
- A trial result with a provider `RuntimeError` is an infrastructure failure.
- `Incorrect API key provided: None` means the TRAPI environment was not loaded.
- Repeated MCP startup failures indicate an image or container problem.
- A numeric reward below 1.0 with no exception is a valid model result.
- A normal zero-tool `end_turn` can be a legitimate model failure, not
  necessarily infrastructure. Inspect its prompt, tool discovery log, and final
  message before classifying it.

Recommended interventions:

- Any authentication error: stop, repair login/environment loading, and requeue
  invalid trials.
- Sustained full-trial retry rate above roughly 5-10 percent: lower agent-phase
  concurrency or improve request pacing.
- No result progress for 30 minutes: inspect active logs and provider errors.
- Critically low root space: stop safely and resolve storage before continuing.

## 13. Safe resume and recovery

Resume from the existing job directory; do not start a second job with the same
intended result set.

```bash
REPO="/home/<USER>/handbook"
JOB_DIR="/mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>"
TMP_DIR="/mnt/datadrive/<USER>/handbook-tmp"
export JOB_DIR

export BENCHMARK_METADATA="/mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>.metadata.json"
export PROTOCOL_LOCK="/mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>.protocol.json"
export JOB_CONFIG="/mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>.config.yaml"
export MODEL="$(jq -r .model "$BENCHMARK_METADATA")"
export REASONING_EFFORT="$(jq -r .reasoning_effort "$BENCHMARK_METADATA")"
export API_MODE="$(jq -r .api_mode "$BENCHMARK_METADATA")"
set -a
. ./.env
set +a
unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY
# Run the immutable metadata verification from Section 7 now.

.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

from harbor.models.job.config import JobConfig
from harbor.models.job.lock import JobLock

job_dir = Path(os.environ["JOB_DIR"])
metadata = json.loads(Path(os.environ["BENCHMARK_METADATA"]).read_text())
intended_config = JobConfig.model_validate(metadata["job_config"])
effective_config = JobConfig.model_validate_json(
    (job_dir / "config.json").read_text()
)
assert effective_config.model_dump(
    mode="json"
) == intended_config.model_dump(mode="json"), (
    "Harbor effective config differs from the immutable protocol"
)
baseline_path = (
    Path("/mnt/datadrive/<USER>/handbook-jobs")
    / "<JOB_NAME>.harbor-lock.json"
)
current = JobLock.model_validate_json((job_dir / "lock.json").read_text())
baseline = JobLock.model_validate_json(baseline_path.read_text())
assert current == baseline, "Harbor lock changed semantically"
PY

tmux new-session -d -s handbook-benchmark -c "$REPO" \
  "unset OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY && \
   set -a && . ./.env && set +a && \
   export TMPDIR='$TMP_DIR' && \
   exec .venv/bin/harbor job resume \
     -p '$JOB_DIR' \
     -f RuntimeError \
     -f CancelledError \
     >> '$JOB_DIR.resume.log' 2>&1"
```

The filters delete those invalid result records and put their logical trials
back into the queue. Valid completed trials remain intact.

Important:

- Confirm the error really is infrastructure-related before filtering it.
- Do not filter or retry a valid low reward.
- If Azure login expired, complete `az login` before resuming.
- Restart the progress reporter after a completed/failed job is resumed; it
  exits when Harbor sets `finished_at`.
- Harbor protects `lock.json`. Avoid changing job settings after trials exist.
  If an orchestration-only change is unavoidable, it must be represented
  consistently in the job config, job lock, and existing trial metadata.
  Prefer choosing the correct scheduling before launch.

## 14. Retry policy details

The recommended Harbor policy retries `RuntimeError` because the current
OpenHands wrapper surfaces provider/transport loop failures as `RuntimeError`.
This is broader than an ideal typed provider exception.

Consequences:

- A 429 that escapes OpenHands is retried.
- A transient transport or loop failure is retried.
- A persistent harness programming bug can also be retried repeatedly.

Therefore:

- keep a finite retry limit;
- inspect final exhausted errors;
- count and report retries;
- never treat repeated retries as proof of model failure;
- consider adding more precise exception types in future harness work.

The 30-300 second Harbor backoff reduces immediate restart storms. It does not
preserve a failed trajectory. Better request-level backoff should be developed
separately and applied consistently to a new result set.

## 15. Final acceptance and scoring

Do not publish or compare the result until all conditions hold:

1. Exactly 260 valid trial results exist.
2. Exactly 65 unique tasks exist.
3. Every task has exactly four valid attempts.
4. No result has `exception_info`.
5. Every valid result has a numeric reward in `[0, 1]`.
6. Harbor reports zero running, pending, cancelled, and errored trials.
7. The model deployment, reasoning effort, and TRAPI base URL match the
   operator-confirmed metadata in every trial.
8. The repository worktree is clean, and its commit, lockfile, installed
   packages, Python runtime, Docker client/server, image, harness, and
   dependency versions match the immutable metadata/provenance record.
9. Harbor's parsed effective `config.json` exactly matches the canonical
   metadata job configuration, including fields populated from defaults.

Run the Section 7 metadata verification and compare the current Harbor lock
with its parsed semantic baseline immediately before this independent final
calculation:

```python
import hashlib
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

from harbor.models.job.config import JobConfig
from harbor.models.job.lock import JobLock

repository_status = subprocess.run(
    ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
assert not repository_status, "repository is dirty at final scoring"

job_dir = Path("/mnt/datadrive/<USER>/handbook-jobs/<JOB_NAME>")
jobs_dir = job_dir.parent
metadata_path = jobs_dir / "<JOB_NAME>.metadata.json"
job_config_path = jobs_dir / "<JOB_NAME>.config.yaml"
protocol_lock_path = jobs_dir / "<JOB_NAME>.protocol.json"
harbor_lock_path = job_dir / "lock.json"
harbor_lock_baseline_path = jobs_dir / "<JOB_NAME>.harbor-lock.json"

metadata = json.loads(metadata_path.read_text())
protocol_lock = json.loads(protocol_lock_path.read_text())
assert protocol_lock["metadata_sha256"] == hashlib.sha256(
    metadata_path.read_bytes()
).hexdigest()
assert protocol_lock["job_config_sha256"] == hashlib.sha256(
    job_config_path.read_bytes()
).hexdigest()

intended_job_config = JobConfig.model_validate(metadata["job_config"])
effective_job_config = JobConfig.model_validate_json(
    (job_dir / "config.json").read_text()
)
assert effective_job_config.model_dump(
    mode="json"
) == intended_job_config.model_dump(mode="json"), (
    "Harbor effective config differs from the immutable protocol"
)
current_harbor_lock = JobLock.model_validate_json(harbor_lock_path.read_text())
baseline_harbor_lock = JobLock.model_validate_json(
    harbor_lock_baseline_path.read_text()
)
assert current_harbor_lock == baseline_harbor_lock, (
    "Harbor lock changed semantically after launch"
)
harbor_lock = json.loads(harbor_lock_path.read_text())

repository_commit = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
assert repository_commit == metadata["repository_commit"], (
    f"repository commit changed: {repository_commit}"
)
aggregate = json.loads((job_dir / "result.json").read_text())
assert aggregate["n_total_trials"] == 260
assert aggregate.get("finished_at"), "Harbor has not marked the job finished"
stats = aggregate["stats"]
assert stats["n_completed_trials"] == 260, stats
assert stats["n_running_trials"] == 0, stats
assert stats["n_pending_trials"] == 0, stats
assert stats["n_cancelled_trials"] == 0, stats
assert stats["n_errored_trials"] == 0, stats

locked_trials = harbor_lock["trials"]
assert len(locked_trials) == 260
locked_task_counts = Counter(
    trial["task"]["name"] for trial in locked_trials
)
assert set(locked_task_counts) == set(metadata["task_names"])
assert set(locked_task_counts.values()) == {4}
locked_task_digests = {}
for trial in locked_trials:
    task = trial["task"]
    locked_task_digests.setdefault(task["name"], set()).add(task["digest"])
    assert Path(task["path"]).resolve().parent == Path(
        metadata["tasks_snapshot"]
    ).resolve()
    agent = trial["agent"]
    assert agent["name"] == metadata["job_config"]["agents"][0]["name"]
    assert agent["model_name"] == metadata["model"]
    assert agent["n_concurrent"] == 1
    assert agent["kwargs"] == {
        "reasoning_effort": metadata["reasoning_effort"],
        "api_mode": metadata["api_mode"],
    }
assert all(len(digests) == 1 for digests in locked_task_digests.values())
assert harbor_lock["n_concurrent_trials"] == 2
for key, value in metadata["job_config"]["retry"].items():
    assert harbor_lock["retry"][key] == value

all_results = [
    json.loads(path.read_text())
    for path in job_dir.glob("*/result.json")
]
assert len(all_results) == 260, (
    f"expected exactly 260 result files, found {len(all_results)}"
)
assert not [result for result in all_results if result.get("exception_info")], (
    "infrastructure-error results remain"
)
results = []

for result in all_results:
    reward = (
        result.get("verifier_result", {})
        .get("rewards", {})
        .get("reward")
    )
    trial = result.get("trial_uri") or result.get("task_name") or "<unknown>"
    assert not isinstance(reward, bool) and isinstance(reward, (int, float)), (
        f"non-numeric reward for {trial}: {reward!r}"
    )
    score = float(reward)
    assert math.isfinite(score), f"non-finite reward for {trial}: {score!r}"
    assert 0.0 <= score <= 1.0, (
        f"reward outside [0, 1] for {trial}: {score!r}"
    )
    results.append((result, score))

assert len(results) == 260, f"expected 260 valid results, found {len(results)}"

task_counts = Counter(
    (result.get("task_name") or result["task_id"]["path"]).rsplit("/", 1)[-1]
    for result, _ in results
)
assert len(task_counts) == 65, f"expected 65 tasks, found {len(task_counts)}"
assert set(task_counts.values()) == {4}, task_counts
assert set(task_counts) == set(metadata["task_names"])

for result, _ in results:
    assert result["agent_result"]["metadata"]["stopped_reason"] != "error"
    trial_dir = Path(result["trial_uri"].removeprefix("file://"))
    run_config = json.loads(
        (trial_dir / "agent" / "openhands_run_config.json").read_text()
    )
    assert run_config["model"] == metadata["model"]
    assert (
        run_config.get("llmKwargs", {}).get("reasoning_effort")
        == metadata["reasoning_effort"]
    )
    assert (
        run_config.get("llmKwargs", {}).get("api_mode")
        == metadata["api_mode"]
    )
    request_protocol = json.loads(
        (trial_dir / "agent" / "request_protocol.json").read_text()
    )
    assert request_protocol == protocol_lock["request_protocol"]
    assert (
        result["agent_result"]["metadata"]["request_protocol"]
        == request_protocol
    )
    runner_log = (trial_dir / "agent" / "run-openhands.log").read_text(
        errors="replace"
    )
    assert f"base_url={metadata['openai_base_url']}" in runner_log

strict_passes = sum(reward == 1.0 for _, reward in results)
strict_pass_at_1 = strict_passes / len(results)
average_score = sum(reward for _, reward in results) / len(results)

strict_by_task = Counter(
    (result.get("task_name") or result["task_id"]["path"]).rsplit("/", 1)[-1]
    for result, reward in results
    if reward == 1.0
)
pass_at_4 = sum(strict_by_task[task] > 0 for task in task_counts) / len(task_counts)

print(f"valid trials: {len(results)}")
print(f"strict passes: {strict_passes}")
print(f"strict pass@1: {strict_pass_at_1:.4%}")
print(f"average score: {average_score:.4%}")
print(f"pass@4: {pass_at_4:.4%}")
```

Compare this output with Harbor's aggregate and the progress report. Investigate
any discrepancy before reporting results.

## 16. Record provenance

Save the following with the final result:

- repository URL and commit, plus confirmation that
  `git status --porcelain=v1 --untracked-files=all` was empty;
- `agent_harness/uv.lock` checksum and the installed package snapshot;
- Docker image ID and runner checksum;
- content-named base-image tag and task-snapshot checksum;
- Harbor, OpenHands SDK, LiteLLM, Python, and Docker versions;
- TRAPI base URL/instance, without credentials;
- exact deployment name;
- exact reasoning effort;
- exact API mode, reviewed `request_protocol.json`, and the bundled LiteLLM
  model-map SHA-256;
- job config, protocol lock, current Harbor lock, and semantic lock baseline;
- task count and attempt count;
- concurrency settings;
- retry policy and final retry count;
- start/end timestamps;
- valid/error/excluded counts;
- final strict pass@1 and average score;
- known deviations from the published setup.

Never claim exact equivalence to a private leaderboard run when its deployment
identifier or serving configuration was not published.

## 17. Lessons learned

1. Starting a long process from an attached CLI/SSH session is unsafe. Use
   `tmux` from the beginning.
2. Harbor resume does not restore `.env`; explicitly source it.
3. A TRAPI 429 is a quota signal, not a benchmark failure.
4. Full-trial retries discard prior trajectory work and are expensive.
5. Trial concurrency and agent concurrency are different. Pipeline two trials
   while serializing the model phase when the token quota is shared.
6. More concurrency does not imply more throughput under a fixed token quota.
7. Do not assume sampling defaults. Inspect and lock the SDK-selected request
   protocol; do not add or remove temperature or `top_p` speculatively.
8. An omitted reasoning setting may inherit an SDK default rather than the
   provider default. Set and record it explicitly.
9. Redirecting job artifacts to a large drive does not move Docker's data root.
10. Infrastructure errors must be rerun; legitimate partial rewards must remain.
11. A one-task smoke score says nothing about the full benchmark score.
12. Final acceptance requires four valid attempts for every task, not merely
    `n_completed_trials == 260`.
13. A shared mutable base-image tag can silently mix environments. Use a
    content-named base tag and a per-job task snapshot.
