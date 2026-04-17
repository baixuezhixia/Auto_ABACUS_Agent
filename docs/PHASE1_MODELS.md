# Phase 1 Core Models

The `src/autodft/core` package defines the first shared vocabulary for the
phase-1 architecture. These models are intentionally small: they describe the
workflow shape without migrating the current runtime logic yet.

## Enums

- `TaskType`: the supported calculation stages: `relax`, `scf`, `bands`,
  `dos`, and `elastic`.
- `TaskStatus`: task and run lifecycle states such as `pending`, `running`,
  `success`, `failed`, and `skipped`.
- `BasisType`: supported ABACUS basis modes, currently `pw` and `lcao`.
- `ArtifactType`: common file and directory categories exchanged between
  stages, including CIF, STRU, INPUT, KPT, output directories, logs, restart
  files, and reports.

## Models

- `StructureSource`: records the original structure request before resolution.
  For the current prototype this is usually a Materials Project ID or formula.
- `ResolvedStructure`: records the selected structure identity, formula,
  lattice type, candidate metadata, and concrete artifacts such as CIF and STRU
  files.
- `TaskNode`: represents one planned workflow task with a stable ID, task type,
  dependency IDs, parameters, optional basis type, and current status.
- `WorkflowSpec`: groups the query, planned task nodes, optional resolved
  structure, and workflow metadata.
- `ArtifactRef`: identifies a workflow artifact by type, path, optional owning
  task, label, and metadata.
- `TaskExecutionRecord`: records the outcome of one task execution, including
  status, return code, work directory, artifacts, metrics, and output tails.
- `RunSummary`: top-level reporting model that connects the workflow plan,
  execution records, notices, final status, and report path.

## Migration Role

These models are not wired into the old codepath yet. They are the target shape
for future migrations from `schema.py`, `pipeline.py`, `input_builder.py`,
`abacus_runner.py`, `result_parser.py`, and `report.py`.
