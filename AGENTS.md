# Agent instructions

For any task that starts, resumes, evaluates, debugs, or modifies a HANDBOOK
benchmark run, read and follow [`BENCHMARK_RUNBOOK.md`](BENCHMARK_RUNBOOK.md)
first.

Before running a model, explicitly confirm the provider endpoint/instance,
exact model deployment, reasoning effort, and expected API mode with the
operator. Do not reuse values from an earlier job. Copilot proxy runs require
an exact `copilot/<model-id>`, `chat_completions`, and a running loopback-only
GH Copilot Server extension.

Never persist or print Azure bearer tokens. TRAPI runs require a trusted host:
root and Docker-capable users must be authorized to access the credential. This
is a shared machine, so do not prune Docker or delete system/shared data without
explicit authorization.

Never expose the unauthenticated VS Code Copilot extension directly on a
non-loopback address. Use the harness's authenticated per-trial relay, and
never use a bridge listener owned by another machine user.
