# Phase 2 Status

This document summarizes the current state of the new `src/autodft/`
architecture after the phase-1 migration and the first phase-2 local-structure
work.

## Phase 1 Completed

- Introduced the new package layout under `src/autodft/` while leaving the
  legacy flat `src/` runtime path in place.
- Added shared core models and enums for workflows, tasks, structures,
  artifacts, execution records, and run summaries.
- Moved the rule-based planning layer behind planner/normalizer modules that
  produce `WorkflowSpec` and `TaskNode` objects.
- Added provider-based structure resolution with Materials Project support.
- Split ABACUS concerns into input generation, presets, resource lookup,
  structure I/O, and runner modules.
- Added a minimal workflow executor, artifact store, dependency graph, parser
  layer, JSON report writer, summary report writer, and new CLI entrypoint.

## Early Phase 2 Completed

- Added local CIF and local ABACUS STRU providers.
- Updated structure resolution so local files are checked before Materials
  Project lookup.
- Wired the new CLI path to accept local `.cif`, `STRU`, `.stru`, MP material
  IDs, and formulas through the same `--structure` argument.
- Improved CLI-facing errors for missing local files, unsupported local file
  formats, and unresolved MP inputs.
- Fixed ABACUS parser recognition for the real log wording:
  `charge density convergence is achieved`, `final etot is ... eV`, and
  `EFERMI = ... eV`.
- Removed the `python -m autodft.cli.main` RuntimeWarning by avoiding eager
  imports of `autodft.cli.main` from `autodft.cli.__init__`.
- Updated ABACUS INPUT defaults:
  - `ecutrho` is not emitted by default for PW or LCAO.
  - `ecutrho` is emitted only when explicitly provided by user/config.
  - LCAO defaults to `ks_solver genelpa`; PW still defaults to `ks_solver cg`.
- Added relaxation semantics in planning and input generation:
  - Query text `fully relax` maps the relax task to
    `calculation cell-relax`.
  - Query text `relax` without `fully` maps to `calculation relax`.
- Updated task normalization so dependency insertion preserves user-expressed
  task order where dependencies allow it.
- Updated relax/cell-relax INPUT behavior:
  - relax and cell-relax tasks emit `out_stru 1`.
  - relax and cell-relax tasks emit `out_chg 0`.
- Updated workflow handoff behavior:
  - `relax -> scf` uses the relax output structure from
    `OUT.<relax_task>/STRU.cif`, converted to
    `relaxed_structures/<relax_task>.STRU`.
  - `scf -> dos`, `scf -> bands`, and `scf -> elastic` use the upstream SCF
    task structure.
  - downstream DOS/BANDS/ELASTIC tasks stage SCF charge artifacts into local
    `READ_CHG/` directories when available.
  - downstream INPUT uses `init_chg file` and `read_file_dir READ_CHG` when
    SCF charge handoff is active.
- Kept dependency gating explicit:
  - failed upstream tasks block downstream tasks.
  - DOS/BANDS are skipped if required SCF charge artifacts are missing.
  - SCF after relax is skipped if a successful relax does not produce
    `OUT.<relax_task>/STRU.cif`.
  - no silent fallback to the original input structure occurs when a valid
    upstream result is required.
- Added `onsite.dm` propagation into downstream `READ_CHG/` staging when the
  upstream SCF output contains it. This path is covered by tests; it has not
  yet been validated by a dedicated real DFT+U run.

## Verified Capabilities

- New CLI path runs via `PYTHONPATH=src python3 -m autodft.cli.main`.
- Local CIF input resolves through `local_cif`, converts to STRU, runs SCF, and
  reports convergence and scalar outputs.
- Local `STRU` and `.stru` inputs resolve through `local_stru` and run through
  the same workflow executor.
- Non-file structure inputs still fall through to the Materials Project
  provider path.
- Real smoke outputs exist for:
  - `runs_smoke_local_cif/` with provider `local_cif`, status `success`, and
    `converged=True`.
  - `runs_smoke_local_stru/` and `runs_smoke_local_stru_check/` with provider
    `local_stru`, status `success`, and `converged=True`.
- Existing local-CIF logs now parse correctly without rerunning ABACUS.
- Real regression runs have passed for:
  - minimal LCAO SCF.
  - minimal PW SCF.
  - `relax -> scf` relaxed-structure handoff.
  - full LCAO workflow regression:
    `relax -> scf -> dos -> elastic -> bands`.
  - query-order regression where requested `dos / elastic / bands` order was
    preserved after dependency insertion.

## Validation

- Unit and integration tests cover planning, structure providers, ABACUS input
  generation, workflow execution, parsers, reports, CLI structure routing, and
  `python -m autodft.cli.main` module invocation.
- Current full-suite check:
  `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`
  passed with 66 tests and 1 expected skip.
- Real smoke-test reports were inspected under `runs_smoke_local_cif/`,
  `runs_smoke_local_stru/`, and `runs_smoke_local_stru_check/`.
- Real workflow regressions were validated for minimal PW/LCAO SCF,
  relaxed-structure handoff, full LCAO downstream handoff, and query-order
  preservation.

## Out Of Scope For Now

- POSCAR input support.
- Defect builders and slab builders.
- Retirement or deletion of the legacy flat `src/` runtime path.
- A stronger execution-status policy that distinguishes subprocess success,
  ABACUS scientific convergence, warnings, and parser confidence.
- Dedicated real DFT+U validation of `onsite.dm` handoff.
