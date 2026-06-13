# agent-friendly-md Runbook

This is the operator entrypoint for running the full workflow. Design history
lives in `docs/design/`; day-to-day runs should start here.

## When To Use This Workflow

Use this workflow when the user needs an Agent-friendly Markdown package with
provenance, QA, visual validation, unresolved-issue tracking, and reproducible
outputs.

Good trigger phrases include:

- "convert this PDF/DOCX into agent-friendly markdown"
- "make a package with provenance"
- "preserve tables/formulas/images"
- "run visual validation"
- "I need QA/report/unresolved artifacts"

When the agent is already operating inside this repository and the user attaches
or references a supported document, treat a plain "convert to md" / "转成 md"
request as a full workflow trigger. Outside that repo-and-document context, ask
whether the user wants quick extraction or the full package workflow.

## When Not To Use This Workflow

Do not use the full Phase 0-7 workflow for quick summaries, rough text previews,
one-off OCR inspection, or cases where the user explicitly asks for only a fast
draft. In those cases, use the smallest appropriate extraction path and tell the
user what validation was skipped.

## Quick Extraction Or Full Package

Choose quick extraction when speed matters more than traceability and the output
will not be used as a durable source of truth.

Choose the full package when the document has tables, formulas, images,
technical diagrams, scanned pages, regulated/legal content, or the user expects
the result to be reviewed, cited, or reused by other agents.

Full package means:

- Document IR is the single content carrier.
- Block-level source anchors are preserved.
- Tables, figures, formulas, and assets are validated.
- Failed gates and open blockers stop the run.
- Phase 6 produces QA, visual acceptance, unresolved, and source evidence.
- Phase 7 packages outputs with relative, portable paths.

## Environment Readiness Check

Run this from the repository root:

```bash
python3 scripts/run_python.py tools/doctor.py --strict
```

`--strict` requires `core`, `extract`, and `visual` readiness. If it exits
non-zero, stop before starting a full package run and fix the missing
dependencies.

For a lower-level diagnostic that only blocks on core runtime readiness:

```bash
python3 scripts/run_python.py tools/doctor.py
```

## Standard Phase 0-7 Command Sequence

All commands run from the repository root. Replace `python3` with the
interpreter reported by doctor if needed.

```bash
python3 scripts/run_python.py tools/init_document_job.py --source "<file>"
python3 scripts/run_python.py tools/run_validators.py --job "<job-dir>"

python3 scripts/run_python.py tools/run_extraction.py --job "<job-dir>"
python3 scripts/run_python.py tools/run_validators.py --job "<job-dir>"

python3 scripts/run_python.py tools/build_ir.py --job "<job-dir>"
python3 scripts/run_python.py tools/link_assets.py --job "<job-dir>"
python3 scripts/run_python.py tools/run_validators.py --job "<job-dir>"

python3 scripts/run_python.py tools/compile_structure.py --job "<job-dir>"
python3 scripts/run_python.py tools/normalize_tables.py --job "<job-dir>"
python3 scripts/run_python.py tools/normalize_formulas.py --job "<job-dir>"
python3 scripts/run_python.py tools/semanticize_figures.py --job "<job-dir>"
python3 scripts/run_python.py tools/run_validators.py --job "<job-dir>"

python3 scripts/run_python.py tools/run_audits.py --job "<job-dir>"
python3 scripts/run_python.py tools/run_validators.py --job "<job-dir>"

python3 scripts/run_python.py tools/assemble_agent_md.py --job "<job-dir>"
python3 scripts/run_python.py tools/run_validators.py --job "<job-dir>"

python3 scripts/run_python.py tools/build_visual_review_packet.py --job "<job-dir>"
python3 scripts/run_python.py tools/run_validators.py --job "<job-dir>"

python3 scripts/run_python.py tools/package_output.py --job "<job-dir>" --out "<package-dir>"
```

Phase 7 默认包名和外发主文档名都来自源文档文件名，而不是内部 ASCII slug：

```text
<source-document-stem>-agent-md/
├── <source-document-stem>.md
├── assets/
├── parts/                  # only when split output is enabled
└── _agent-md/
    ├── index.md
    ├── index.json
    ├── manifest.json
    ├── provenance.json
    ├── qa_report.md
    ├── visual_acceptance.md
    ├── unresolved.md
    └── package_metadata.json
```

Only the reader-facing Markdown, its `assets/`, and split `parts/` needed by
that Markdown stay at package root. For split output, the reader-facing Markdown
is an entry index with summary, part links, source ranges, and content counts;
agents should read it before opening any `parts/` file. QA, provenance,
unresolved tracking, manifest, package metadata, machine-readable
`index.json`, companion `index.md`, and optional `--include-work` reproducer
material live under `_agent-md/`.

## Agent-Authored Required Steps

Some phases cannot be fully automated.

Phase 3 visual descriptions are agent-authored. Inspect every image in
`extracted/images/`, then write `review/vision_cache.json` as JSONL:

```jsonl
{"file":"fig_p006_example.png","text":"A concise, source-grounded visual description."}
```

Use "approximate" language for estimated chart values and preserve the
"basis" note required by `docs/quality-standards.md`.
For repeated logo/seal/watermark/decorative images, describe them as document
artifacts or decoration rather than substantive figures; Phase 3 will mark
them as likely noise so Phase 5 keeps them out of reader-facing Markdown.

Phase 6 review is also agent-authored. Inspect rendered screenshots,
`contact_sheet.png`, source comparisons or source-evidence files, QA output, and
open issues before reporting completion.

## Stop Conditions

Stop the run when any of these occur:

- A command exits non-zero.
- A gate writes `status: fail`.
- `tools/doctor.py --strict` reports missing full-workflow dependencies.
- A high-risk job lacks visual screenshots or source evidence.
- `review/issues.jsonl` has an open blocker.
- `output/unresolved.md` disagrees with the issue ledger.
- Path-leak checks report local-only paths in shipped outputs.
- Required agent-authored visual descriptions are missing.

Do not package by bypassing gates. Fix the cause, rerun the producing phase, and
let `tools/run_validators.py` record a fresh hash snapshot.

## Failure Recovery And Rerun Rules

If an upstream phase is rerun, downstream hash snapshots may become stale. Rerun
the downstream producer and gate. Use `--refresh-stale` only after confirming
the downstream artifacts were regenerated from current inputs.

If a job directory already exists, choose a new `--date` or `--slug`, or use
`--force` only when deliberately reusing that bundle.

If visual rendering is unavailable, low-risk jobs may continue with notes.
Medium and high-risk jobs must stop until real screenshots can be produced.

## Final Report Format

Report back with:

```text
Implemented:
- ...

Verified:
- ...

Smoke packages:
- source:
  job:
  package:
  QA overall:
  unresolved/blockers:
  visual artifacts:
  path leak scan:

Remaining risks:
- ...

Files changed:
- ...
```

## Example User Prompts

PDF:

```text
Run the full agent-friendly-md workflow on this PDF. Preserve tables, formulas,
figures, provenance, QA, visual validation, and package the final output.
```

DOCX:

```text
Run the full agent-friendly-md workflow on this DOCX. Treat tables and comments
as high-risk, produce source evidence for Word anchors, and package the result.
```
