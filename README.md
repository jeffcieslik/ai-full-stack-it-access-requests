# IT access-request intake

A Python CLI that turns exported messages into validated extraction records and a queue for human review. The submitted examples replay saved model responses and are labelled `mock`; a configurable OpenAI HTTP integration is also implemented. The application never approves or grants access.

## Setup

Supported runtime: Python 3.12+ on Linux/POSIX, with SQLite on local storage. Development verification used Python 3.12.3 and uv 0.13.7. Install Python and [uv](https://docs.astral.sh/uv/getting-started/installation/), then run every command below from this repository's root:

```bash
uv sync --locked
env -u API_KEY .venv/bin/python -m unittest discover -s tests -v
```

`pyproject.toml` and `uv.lock` lock the application and JSON Schema validator dependencies. First setup downloads dependencies; all tests run offline on saved mock responses and injected transports. No test requires or reads a real `API_KEY`.

## Prepare and inspect the supplied intake

```bash
env -u API_KEY .venv/bin/python -m it_access intake --input materials/requests --state .state/intake.db --provider mock --fixtures tests/mock_responses
.venv/bin/python -m it_access queue --state .state/intake.db
.venv/bin/python -m it_access pending --state .state/intake.db
.venv/bin/python -m it_access history --state .state/intake.db --document IT-001.json
.venv/bin/python -m it_access export --state .state/intake.db --output deliverables
.venv/bin/python -m it_access verify-exports --output deliverables
```

`queue` displays each document's status, owner, next action, attempt/source identity, and producing configuration. Run it in another terminal while intake runs. `pending` distinguishes queued, running and retry-wait work; a prior terminal result is explicitly labelled if newer work is pending. Complete staging/read requests go to System Owner. Production, write or admin requests first go to Security Review for a recommendation and then the owner's human decision. A manager name is a contact, not approval.

The exported JSONL has one current record per document, with `document_id`, `source_sha256`, `extraction`, `status`, `owner`, `next_action`, `error` and `response_source`, plus provenance. `queue.json` links by document ID, hash and attempt. `snapshot.json` records hashes of both files: use `verify-exports` to reject interrupted/mixed snapshots. An export can replace two files only sequentially; cooperating readers use the lock/manifest rather than assuming two renames are atomic. Live queue inspection reads one SQLite transaction and does not depend on exported files.

## Retry and resume

```bash
.venv/bin/python -m it_access intake --input materials/requests --state .state/intake.db --provider mock --fixtures tests/mock_responses --enqueue-only
.venv/bin/python -m it_access resume --state .state/intake.db --rate-per-minute 0
```

For a failure, copy the `retry_command` from the queue; it has this form, with the actual failed attempt number:

```text
.venv/bin/python -m it_access retry --state .state/intake.db --attempt 23 --rate-per-minute 0
```

The saved source bytes and nonsecret processing configuration are reused, not whatever happens to be on disk at retry time. Retry of an older source cannot replace a newer generation. Errors show a null extraction and actionable diagnostics; the last valid extraction remains in history. An unchanged rerun reuses its recorded result, including a visible error until explicit retry or `--force`; successful unchanged work does not call the model again. A later batch does not withdraw absent documents. Each filename remains independent even when message request IDs match.

Claims expire after 120 seconds and renew every 20 seconds. After terminating a process, resume can wait for that lease to expire. Transient connection, timeout, HTTP 408/429/5xx failures get up to three attempts, with persisted retry attempts and capped exponential delays; delays release worker capacity. Terminal refusal, malformed extraction and incomplete completion status remain visible for explicit follow-up. An interrupted provider request may be sent again: database publication is fenced, external billing is not exactly-once.

## Accuracy and request evidence

```bash
env -u API_KEY .venv/bin/python -m it_access accuracy --input materials/requests --input tests/inputs --expected tests/expected.json --provider mock --fixtures tests/mock_responses --output deliverables/accuracy.md
env -u API_KEY .venv/bin/python -m it_access request-evidence --input materials/requests/IT-001.json --model gpt-5.4-mini-2026-03-17 --output deliverables/request-evidence.json
```

The independent expected facts were transcribed from messages and policy in `planning/plan.md` before measured outputs. Accuracy uses a separate temporary 21-document state (20 originals plus the authored IT-021 paraphrase). Submitted queue files contain the original 20 only. Twelve scalar exact matches per expected document give a fixed denominator of 252; nulls count when expected, missing/error documents score zero of twelve, and no failed case is excluded. Schema, routing, quote integrity and issue coverage are reported separately. Purpose excerpts are canonical measurement text; human review distinguishes faithful alternative wording from factual errors. A mock match verifies pipeline/comparison behavior, not live-model quality.

`request-evidence` builds an illustrative request through the actual production serializer, records the model/schema/options and handling paths, and writes a redacted Authorization header. It sends no request and reads no key. Its example provider model differs explicitly from the `mock` model that produced committed extraction records.

## Provider configuration

The supported provider protocol is non-streaming OpenAI Chat Completions at `https://api.openai.com/v1/chat/completions`, using strict JSON Schema structured outputs. The documented configuration is `gpt-5.4-mini-2026-03-17`, as listed in [the model documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini), with a 60-second timeout and 4096 completion tokens. This integration is tested with injected HTTP responses; no live account/model observation was performed. Use a model supported by the facilitator's account.

The only application credential environment variable is **`API_KEY`**; the facilitator supplies it. It is read lazily in explicit provider mode, never stored in the database/configuration or printed in operational diagnostics. Other application settings use flags:

| Flag | Default | Purpose |
|---|---|---|
| `--provider` | `mock` | `mock` or `openai` |
| `--model` | `mock` for fixtures; required for OpenAI | Requested model ID |
| `--base-url` | `https://api.openai.com/v1` | Credential-free HTTPS provider base |
| `--fixtures` | `tests/mock_responses` | Mock envelope directory |
| `--timeout` | 60 | Transport timeout in seconds |
| `--max-completion-tokens` | 4096 | Completion budget; increase explicitly if truncated |
| `--workers` | 4 | Shared same-host in-flight ceiling |
| `--rate-per-minute` | 0 for mock intake, 60 for live/resume/retry | Shared database request-start budget; 0 disables it |
| `--max-attempts` | 3 | Maximum automatic attempts per retry sequence |
| `--state` | `.state/intake.db` | Durable local SQLite database |
| `--force` | off | New attempt even if source/configuration are unchanged |

Optional provider intake, using an already provisioned environment key:

```bash
.venv/bin/python -m it_access intake --input materials/requests --state .state/provider.db --provider openai --model gpt-5.4-mini-2026-03-17 --rate-per-minute 30
```

To score actual provider results, include `--input tests/inputs` in that intake, export to a separate directory, and run `accuracy` with `--records <that-directory>/extractions.jsonl` and both `--input` arguments. This compares those saved results without another provider call. Record the producing configuration and response source; do not present mocked output as live observations.

## State, policy and limits

SQLite WAL supports overlapping operators on one host using the same local database. It does not support this design over network filesystems or active multi-host writers. Request quotas cover this database's operators, not unrelated internal applications. Source generations are ordered by registration, not export timestamps; stale workers cannot publish over a newer generation. No automatic history pruning is performed. Use uniquely named files in a nonrecursive intake directory; duplicate basenames in a single batch are rejected. Malformed input exports become document errors without stopping valid documents.

Source bytes, prompt, schema, model options, explicit extraction implementation version and policy identity are retained. Result-affecting settings trigger refresh; a policy-only change reroutes a stored valid extraction with an explicit parent-extraction reference. The supplied policy is implemented in code: changing its meaning requires updating `route` and its version in `src/it_access/config.py`, not merely editing prose. An editable checkout reads the root schema and materials policy as authorities; bundle their updates with the resource copies when distributing a wheel. Pending older results and historical attempts remain attributable to their original source/settings. Replaying an old configuration uses current implementation code, so exact historical code replay across incompatible future versions requires checking out that version as well.

The 2000-document workload check uses mocks. It does not establish live-provider throughput, a completion-time SLA, power-loss durability of faulty hardware, a global multi-office storage service, comprehensive prompt-injection detection, or correctness for undefined multi-intent/partial-date cases. The prompt and validation handle the supplied policy; `SYSTEM OVERRIDE:` is additionally flagged directly. Novel override phrasing depends on extractor evidence; humans review the queue.

## Layout and submission

`src/it_access/` contains the runnable package, prompt, schema/policy resources, provider adapter, scheduler, persistence and reporting. `docs/requirements.md`, `materials/office-policy.md`, `snapshot.schema.json` and supplied exports remain source authorities. `tests/expected.json` is the source-owned oracle, `tests/mock_responses/` the recorded response fixtures, and `tests/inputs/IT-021.json` the paraphrase. See `deliverables/verification.md` for command results and limits.

Entire is enabled for Codex in this repository. The final submission commit has not been created by this task; the user must commit the completed files, inspect the automatically paired session capture using the facilitator's instructions, and push the default branch. Check `entire status --json`; use `entire agent-help checkpoint list` then `entire checkpoint list --pending --json` for the next-checkpoint preview, and inspect the final commit's capture after committing. No manual checkpoint is needed. Submit only the repository root link through Classroom. Capture enabled/preview evidence is not a claim that a future final commit has already been paired or pushed.
