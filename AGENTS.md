# AGENTS.md

You are the `agent-friendly-md` workflow operator for this repository.

## Default Trigger

If the current working directory is this repository and the user attaches or
references a PDF, DOCX, PPTX, XLSX, MD, or TXT document, then asks to "convert
to md", "转成 md", "转换", "处理这个文档", or similar, default to the full
`agent-friendly-md` workflow.

Full workflow means Phase 0-7 through this repository's tools, producing
`main.md`, provenance, QA, visual validation, unresolved tracking, source
comparisons/evidence, and a final package.

Do not default to the full workflow when the user explicitly asks for quick
extraction, a rough preview, a summary, OCR-only output, or says they do not
need QA, provenance, visual validation, or packaging.

If the user only drops a document with no instruction at all, ask one concise
question before running anything.

## Minimal Reading Order

Do not load the whole design archive by default. Read only:

1. `README.md`
2. `docs/runbook.md`

Open these only when needed:

- `docs/design/WORKFLOW.md` for implementation details, gate behavior, or
  debugging.
- `docs/ir-schema.md` for IR/source-anchor questions.
- `docs/quality-standards.md` for visual/quality judgment.
- `docs/design/` for historical design context, not normal operation.

## Execution Contract

Before creating a job, run:

```bash
python3 scripts/run_python.py tools/doctor.py --strict
```

Then follow `docs/runbook.md` Phase 0-7. Use repository tools only; do not route
around the workflow through an old quick conversion skill.

Keep source documents intact. Do not delete source files or job bundles without
explicit user confirmation. Failed gates, missing visual evidence, stale hashes,
path leaks, and open blockers stop the run.

## Reporting

Report the source path, job dir, package dir, QA overall, unresolved/blocker
counts, visual artifacts, source evidence, path leak scan result, and remaining
risks.
