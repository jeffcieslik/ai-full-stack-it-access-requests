# Verification evidence

Configuration: Python 3.12.3 on Linux/POSIX, dependencies in uv.lock, application source under src/it_access, fixture provider `mock` with model `mock`, fixtures under tests/mock_responses, independent oracle tests/expected.json. All recorded extraction examples are mocked. Provider adapter tests inject HTTP responses and a fake sentinel credential; no real model was called and tests do not read API_KEY. The request-evidence example is illustrative and was not transmitted.

## Commands and intended assertions

Run from the repository root after `uv sync --locked`:

```bash
env -u API_KEY .venv/bin/python -m unittest discover -s tests -v
env -u API_KEY .venv/bin/python -m it_access intake --input materials/requests --state .state/intake.db --provider mock --fixtures tests/mock_responses
.venv/bin/python -m it_access export --state .state/intake.db --output deliverables
.venv/bin/python -m it_access verify-exports --output deliverables
env -u API_KEY .venv/bin/python -m it_access accuracy --input materials/requests --input tests/inputs --expected tests/expected.json --provider mock --fixtures tests/mock_responses --output deliverables/accuracy.md
env -u API_KEY .venv/bin/python -m it_access request-evidence --input materials/requests/IT-001.json --model gpt-5.4-mini-2026-03-17 --output deliverables/request-evidence.json
```

| Check | Intended comparison / assertion | Evidence |
|---|---|---|
| Source/schema handling | Hash original bytes, preserve decoded messages and metadata; validate required keys/types/enums and exact decoded quotes; support 200-word input | tests/test_inputs.py |
| Complete/missing/conflicting requests | Expected facts come from plan/source review, not measured output; null/issue semantics and human routes agree with the office policy | tests/test_pipeline.py and tests/expected.json |
| Corrections and changes | IT-008 uses staging, IT-015 corrected dates, IT-007 new write, IT-019 new read | test_environment_correction, test_date_correction, test_change_permission |
| Injection and precedence | IT-006 retains read and preserves override evidence without approval; override wins over withdrawal; withdrawal precedes ordinary clarification | test_embedded_instructions, test_routing_precedence |
| Provider boundary | Request model/schema/options and source-data separation match production builder; credentials/network are guarded in tests | tests/test_response_handling.py |
| Failed responses | Provider errors, refusal, length/unsupported completion and malformed JSON never become usable extraction records | test_provider_failure, test_refusal_response, test_interrupted_response, test_malformed_output |
| Reuse and revisions | Identical source/settings reuse one current result without model call; changed bytes refresh with old hash/result retained | tests/test_state.py |
| Failed retry after success | Latest attempt is error with null extraction, actionable retry and separate attributable earlier success | test_failed_retry_after_success |
| Incremental batches | Absence from a later batch retains an earlier request | test_incremental_batches |
| Settings/policy refresh | Changed model fingerprint creates a fresh extraction; policy-only change reuses valid extraction with parent ID and reroutes into retained history | tests/test_refresh.py |
| Overlap and stale results | Two forked processes compete for one claim; only one owns it; an older completion cannot overwrite a newer byte revision | test_overlapping_operators_and_fencing |
| Interrupted worker | A forked child claims then exits with code 7; expired claim is recoverable and completed results survive | test_interruption_recovery |
| Partial availability and retry | Delay IT-001 while IT-008 completes; injected transient 429/503 errors retry independently, preserving completed work | test_slow_rate_limited_and_unavailable |
| Workload probe | 2000 independent mock documents with four workers complete with one current entry each; repeated message IDs do not merge documents | test_peak_mock_workload |
| CLI and handover | Enqueue, inspect pending/queue/history, resume, retry, export and compare through documented commands in temporary state | tests/test_cli.py and tests/test_handover.py |
| Linked exports | Twenty current unique IDs; matching source hashes/attempts in queue; interrupted marker or tampered bytes are rejected and exports can be rebuilt | tests/test_exports.py, deliverables/snapshot.json |
| Fixed denominator | Baseline 252/252; changed scalar 251/252; error document 240/252; missing outputs never shrink denominator | tests/test_accuracy.py |

## Observed results

The generated submission intake processed **20 documents**, leaving **0 pending**. Export validation observed **20 extraction records and 20 linked queue entries**. The separate 21-case mock accuracy run observed **252/252 scalar exact matches and 21/21 routing matches**, with zero schema, quote or missing-issue errors and no unexpected documents. These are mock pipeline observations, not live model accuracy measurements. Complete model/configuration snapshots and exact source expectations are in accuracy.md.

The final complete test rerun observed **48 passing tests in 54.456 seconds**, recorded in planning/test-run.txt with mock/configuration metadata. This is total suite duration on this machine, not a workload or provider SLA. Additional boundary checks cover shared request-start quotas, maximum retry attempts and HTTP retryable/terminal classes with unread/redacted error bodies. Earlier implementation checkpoints also passed the complete suites available at those stages: 8 (input validation), 25 (routing), 30 (response handling), 34 (persistence), 36 (refresh), 40 (operations), 41 (CLI), 42 (exports) and 43 (accuracy). New step tests were first observed failing because their modules/behavior were absent; the user explicitly authorized completing the remaining build without separate commit pauses. No claim is made that this task created separate failing/passing commits for those later steps.

Observed setup repair: moving from the repository-root package to src/ required reinstalling the editable package with `uv sync --locked --offline --cache-dir /tmp/it-access-uv-cache --no-python-downloads --reinstall-package it-access-requests`; installation succeeded. Initial dependency access in the earlier S01 task required approved network access because sandbox DNS was unavailable. No extraction expectations were changed to match a measured output. The S01 historical test log has been replaced by the current final-run log, with explicit mock/configuration metadata.

Observed handover repairs: an acceptance assertion found that generated retry commands used bare `python`, which could select an interpreter outside the installed environment. The implementation now emits the actual `sys.executable`, and the CLI test executes the generated command. An intentionally malformed external accuracy record exposed a comparator crash on non-object extractions/invalid quote arrays; comparison now preserves the fixed denominator, reports schema/evidence failures and does not crash on those inputs. The final complete run includes both regression checks.

Additional observed packaging/artifact checks: `uv lock --check --offline --cache-dir /tmp/it-access-uv-cache --no-python-downloads` passed. `uv build --wheel --offline --cache-dir /tmp/it-access-uv-cache --out-dir /tmp/it-access-wheel` built the wheel, whose entrypoint, prompt, schema and policy resources were inspected. An independent audit recomputed every submitted source hash, validated every extraction/quote against its original message, and compared all 20 records' facts/routes to tests/expected.json. An unchanged CLI intake then reported zero completed attempts, zero pending and 20 current documents, demonstrating reuse in the actual documented workspace.

## Operating assumptions and verification limits

- Supported shared operation is multiple same-host processes against one local SQLite WAL database; this is not active multi-host or network-filesystem storage. Shared quota/claim checks use short SQLite transactions; calls happen outside write transactions.
- Four workers and the rate/retry limits are configuration choices, not inferred company requirements. The 2000-document probe uses zero-delay fixtures and disables rate limiting. It does not establish live throughput, service-level timing, cost or variable-provider capacity; the plan's 200/400 sizes were not separately benchmarked.
- Crash verification covers a process exit after claiming, lease recovery and stale-result fencing. It is not a hardware/power-loss or filesystem-corruption study. Export verification injects an interrupted marker and tampering; it does not simulate every possible rename/power-loss boundary or every concurrent exporter interleaving.
- Lease recovery can take 120 seconds. Provider calls can repeat after a process dies; current publication is fenced but external charging is not exactly-once. Source/configuration generations follow registration order; out-of-order export timestamps are not a trustworthy source chronology.
- Extraction validation verifies structure, completion, date syntax/calendar validity and provided quote substrings. It does not prove every scalar fact is entailed by every possible message. Live factual quality is unmeasured; canonical purpose excerpts can score differently from a faithful model paraphrase.
- The prompt identifies unknown/missing/conflicting facts, corrections and relative dates. A literal SYSTEM OVERRIDE marker is additionally flagged by code; comprehensive detection of novel, obfuscated or benign quoted attack text was not established. Undefined mixed-intent/partial-date cases still require policy clarification. Invalid calendar/date-format output is an explicit extraction failure, not silently repaired.
- Policy is implemented in route code. A prose policy edit alone is not a generated routing algorithm: update the code/version and packaged policy snapshot together. Policy-only refresh and extraction refresh are distinguished and retain their parent source/configuration provenance.
- No notification, access provisioning, reviewer authentication or automated approval is implemented or required by this queue-only brief. A manager is a contact; humans make approval/withdrawal decisions.
- Errors never substitute a historical success as the latest extraction. Old terminal results can be shown while newer work is pending, with an explicit older-source notice and pending attempt identity. History and input snapshots have no automatic retention pruning in this implementation.
- Tests cover the local mock boundary and a recording HTTP transport; credentials are replaced, sockets are blocked, and no API key/live provider is needed. Actual account access/model availability is unverified. OpenAI example configuration was checked against primary API/model documentation, linked from README.md.

## Coding-session capture and final submission

`entire status --json` reported enabled Codex capture, session `01a1d581-fb9c-79f2-83ae-dac253b34b0f`, and automatic checkpoint push policy. `entire checkpoint list --pending --json` showed a next-checkpoint preview containing this task's changes. See session-capture.json for the inspected status summary. This demonstrates configured capture and pending session state, not a verified future submission pairing.

The final submission commit/push and Classroom submission remain user actions. After committing, inspect the automatically paired capture using the facilitator's instructions and current Entire read-only commands, then push the repository's actual default branch and submit only its root URL. No manual checkpoint, commit or push was performed in this task.
