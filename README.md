# Agent Rebuild

This repository contains an isolated Python prototype for running ABACUS DFT workflows from a natural-language request and either a local structure file or a Materials Project structure reference.

The current workflow can:

1. Decode a user query into an ordered calculation workflow for `relax`, `scf`, `bands`, `dos`, and `elastic`.
2. Resolve structures from local `.cif`, local `STRU`/`.stru`, Materials Project material IDs, or Materials Project formulas.
3. Generate ABACUS `INPUT`, `KPT`, and `STRU` files for PW and LCAO tasks.
4. Run ABACUS tasks in dependency order with explicit handoff between dependent tasks.
5. Parse basic run metrics and write `report.json` plus a concise summary.

All generated files are written under the selected `--work-dir`.

## Implemented Capabilities

### Task decoding

Supported task types:

- `scf`
- `relax`
- `bands`
- `dos`
- `elastic`

Task plans can come from either:

- The built-in rule decoder.
- An OpenAI-compatible chat-completions API.
- A manual `--tasks` override.

The workflow is normalized before execution. Missing dependencies are inserted, but the generated task and folder order preserves the order expressed by the query once dependencies are satisfied.

Dependency rules:

- `bands`, `dos`, and `elastic` add `scf` if missing.
- `elastic` adds `relax` if missing.
- `scf` depends on `relax` when both are present.
- `bands` and `dos` depend on `scf` when present.

The implemented basis modes are `pw` and `lcao`. If the query explicitly mentions either token, that basis hint is propagated into every decoded task. In ABACUS input generation, `lcao` enables the `NUMERICAL_ORBITAL` block and requires configured orbital files.

Relaxation wording is mapped to ABACUS calculation modes:

- `"fully relax"` generates `calculation cell-relax`.
- `"relax"` without the full-cell wording generates `calculation relax`.

### Structure resolution

`--structure` may be one of:

- A local CIF file, such as `examples/si_pw/OUT.si_test/STRU.cif`.
- A local ABACUS structure file named `STRU` or ending in `.stru`.
- A Materials Project material ID, such as `mp-149`.
- A formula, such as `Si` or `SiO2`.

Local files take precedence. Non-file inputs fall back to Materials Project resolution.

For material IDs, the agent fetches that exact entry. For formula searches, the agent ranks candidates with:

- Exact reduced-formula matching.
- Deprecated-entry filtering.
- Near-hull filtering using `energy_above_hull`.
- Rule sorting by stability, hull distance, theoretical flag, and material ID.
- Optional LLM ranking over the hard-filtered shortlist.

For Materials Project inputs, the selected conventional structure is downloaded as:

```text
<work-dir>/materials_project/<material_id>.cif
```

The converted base structure is written as:

```text
<work-dir>/materials_project/<material_id>.STRU
```

### ABACUS input generation

For each task, the agent writes:

```text
<work-dir>/<NN>_<task>/INPUT
<work-dir>/<NN>_<task>/STRU
<work-dir>/<NN>_<task>/KPT
```

Current generation behavior:

- The supported basis modes are `pw` and `lcao`.
- Default basis is `pw`.
- `lcao` is supported when `abacus.orb_dir` or `abacus.orbital_dir` is configured.
- Pseudopotentials are resolved from `abacus.pseudo_dir`.
- LCAO orbital files are resolved from `abacus.orb_dir`.
- `bands` uses a line-mode `KPT` path from `defaults.calculation.kpath`.
- Other tasks use a Gamma-centered mesh from `defaults.calculation.kmesh`.
- `bands` and `dos` run as ABACUS `nscf`.
- `relax` and `cell-relax` inputs set `out_stru 1` and `out_chg 0`.
- `bands`, `dos`, and `elastic` stage SCF charge-density restart files into `READ_CHG` when required.
- Downstream charge-reuse tasks set `init_chg file` and `read_file_dir READ_CHG`.
- If a successful relaxation dependency produced `OUT.<task_id>/STRU.cif`, downstream `scf` uses a converted relaxed `STRU`.
- If a successful `scf` dependency produced structure and charge artifacts, downstream `dos`, `bands`, and `elastic` use those artifacts.
- Failed upstream dependencies block downstream tasks; the executor does not silently fall back to the original input structure when a valid upstream result is required.
- `ecutrho` is not emitted by default for PW or LCAO. It is emitted only when explicitly provided by user/config input.

`onsite.dm` is staged for downstream tasks when present in the upstream SCF output. This DFT+U handoff path is covered by tests, but real DFT+U workflow validation is not claimed here.

### ABACUS execution

The runner supports:

- `abacus.run_mode: "mpirun"`
- `abacus.run_mode: "local"`
- `abacus.np`
- `abacus.use_hwthread_cpus`
- `abacus.oversubscribe`

When the task directory is on the configured WSL UNC path, or when the ABACUS executable is a Linux absolute path, the runner executes through:

```bash
wsl bash -lc "cd <task-dir> && <command>"
```

Otherwise it runs directly from the host process.

### Result parsing

After each ABACUS task, the agent records:

- Return code.
- Success or failed status.
- Output directory path when present.
- Tail of stdout and stderr.
- Parsed metrics from `OUT.<task_id>/running_*.log`, including:
  - convergence flag
  - total energy in eV
  - total energy in Ry
  - Fermi energy in eV
  - band gap for band calculations when present
  - output file list

## Quick Start

Install dependencies:

```bash
cd agent_rebuild
pip install -r requirements.txt
```

Copy the example config:

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml` for your local ABACUS setup:

```yaml
abacus:
  executable: "abacus"
  run_mode: "mpirun"
  np: 8
  pseudo_dir: "../abacus_data/Pseudopotential"
  orb_dir: "../abacus_data/StandardOrbitals"
```

For Materials Project inputs, set your API key in either the environment:

```bash
export MP_API_KEY="your_materials_project_key"
```

or in `config.yaml`:

```yaml
MP_API_KEY: "your_materials_project_key"
```

Run a workflow through the new CLI path:

```bash
PYTHONPATH=src python3 -m autodft.cli.main \
  --query "计算Si的结构弛豫，随后做能带和DOS" \
  --structure Si \
  --work-dir ./runs_mp \
  --config config.yaml
```

Force the four-task calculation sequence explicitly and bypass query decoding:

```bash
PYTHONPATH=src python3 -m autodft.cli.main \
  --query "manual run" \
  --structure mp-149 \
  --work-dir ./runs_manual \
  --config config.yaml \
  --tasks relax,scf,bands,dos
```

## Runtime Inputs

Required command-line inputs:

- `--query`: natural-language scientific request.
- `--structure`: local `.cif`, local `STRU`/`.stru`, Materials Project material ID, or formula.

Optional command-line inputs:

- `--work-dir`: output directory, default `./runs`.
- `--config`: YAML config path, default `config.yaml`.
- `--tasks`: comma-separated task list. When set, this bypasses automatic task decoding.

Required runtime resources:

- `MP_API_KEY` in `config.yaml` or the environment for Materials Project inputs.
- ABACUS executable available according to `abacus.executable`.
- Pseudopotential files under `abacus.pseudo_dir`.
- Orbital files under `abacus.orb_dir` for LCAO workflows.

## Configuration

Example:

```yaml
abacus:
  executable: "abacus"
  run_mode: "mpirun"  # mpirun or local
  np: 8
  pseudo_dir: "../abacus_data/Pseudopotential"
  orb_dir: "../abacus_data/StandardOrbitals"
  use_hwthread_cpus: false
  oversubscribe: false

defaults:
  calculation:
    basis_type: "pw"
    ecutwfc: 80
    # ecutrho is optional and is emitted only when explicitly configured.
    # ecutrho: 640
    kmesh: [6, 6, 6]
    smearing_method: "gaussian"
    smearing_sigma: 0.01
    scf_thr: 1e-7
    scf_nmax: 50
    ks_solver: "cg"
    nspin: 1
    symmetry: 1
    out_level: "ie"
    out_stru: 0
    relax_force_thr: 0.01
    stress_thr: 10
    dos_emin_ev: -15.0
    dos_emax_ev: 15.0
    dos_edelta_ev: 0.01

decoder:
  mode: "auto"  # rule, auto, or llm
  model: "gpt-4o-mini"
  base_url: "https://api.openai.com/v1"
  api_key: ""
  temperature: 0.0
  timeout: 60

mp_selection:
  hard_limit: 5
  llm:
    enabled: true
    model: "gpt-4o-mini"
    base_url: "https://api.openai.com/v1"
    api_key: ""
    temperature: 0.0
    timeout: 60

MP_API_KEY: ""
```

Relative `abacus.pseudo_dir`, `abacus.orb_dir`, and `abacus.orbital_dir` paths are resolved relative to the config file location.

The config loader also accepts simple quoted assignment lines such as:

```text
MP_API_KEY="..."
```

Those assignments are stripped before YAML parsing and then merged into the config.

## LLM Modes

Task decoding:

- `decoder.mode: "rule"` uses the built-in regex decoder.
- `decoder.mode: "llm"` requires an API key and fails if the model call fails.
- `decoder.mode: "auto"` tries the LLM first and falls back to the rule decoder if the LLM fails.

The decoder API must be OpenAI chat-completions compatible. It should return JSON with:

```json
{
  "tasks": [
    {
      "task_type": "scf",
      "description": "Run SCF",
      "depends_on": [],
      "params": {}
    }
  ]
}
```

Materials Project candidate ranking can also use an OpenAI-compatible model through `mp_selection.llm`. If ranking is disabled, missing an API key, or fails, the agent uses the deterministic rule-ranked candidate.

## Output Layout

Typical output:

```text
runs_mp/
  materials_project/
    mp-149.cif
    mp-149.STRU
  01_relax/
    INPUT
    STRU
    KPT
    run.log
    OUT.t1_relax/
  02_scf/
    INPUT
    STRU
    KPT
    OUT.t2_scf/
  03_bands/
    INPUT
    STRU
    KPT
    READ_CHG/
    OUT.t3_bands/
  04_dos/
    INPUT
    STRU
    KPT
    READ_CHG/
    OUT.t4_dos/
  05_elastic/
    INPUT
    STRU
    KPT
    READ_CHG/
    OUT.t5_elastic/
  run.log
  report.json
  summary.txt
```

`report.json` contains:

- Original query.
- Resolved structure metadata.
- Selected Materials Project structure when the input used Materials Project resolution.
- Candidate shortlist and LLM scores when available.
- Notices from selection, conversion, and dependency handling.
- Normalized task plan.
- Per-task execution results.
- Parsed metrics.
- `run_log`, the aggregate pipeline log path.
- Per-task `artifacts.run_log` paths with command, return code, stdout, stderr, and ABACUS `warning.log`/`running_*.log` error details.
- stdout and stderr tails for debugging failed runs.

## Current Limitations

- POSCAR input, defect builders, and slab builders are not implemented.
- MP structures are downloaded as conventional cells.
- Disordered or partial-occupancy CIFs are rejected during CIF-to-STRU conversion.
- Calculation parameters mostly come from `defaults.calculation`; the agent does not yet infer `ecutwfc`, k-mesh density, smearing, convergence thresholds, or magnetism from the query or material.
- `elastic` is represented as a task and currently generates an ABACUS `scf`-style input with relaxation-related thresholds; a full strain/deformation elastic workflow is not implemented.
- Both `pw` and `lcao` input generation are wired in; broader production validation is still needed.
- The legacy flat runtime path remains in the repository while the new `autodft` package path is validated.
- Long ABACUS production runs still need normal HPC scheduling, monitoring, and resource management outside this wrapper.

## Validated Examples

The new CLI path is runnable as:

```bash
PYTHONPATH=src python3 -m autodft.cli.main ...
```

Validated workflow examples in the current repository state include:

- Minimal PW `scf`.
- Minimal LCAO `scf`.
- `relax -> scf` with the SCF task using the relaxed structure output.
- Full LCAO workflow with dependency handoff: `relax -> scf -> dos -> elastic -> bands`.
- Query-order preservation after dependency insertion, including workflows where `dos`, `elastic`, and `bands` are requested in that order.

Example full LCAO workflow:

```bash
PYTHONPATH=src python3 -m autodft.cli.main \
  --query "relax the cell with LCAO method, and then calculate its density of states, elastic properties, and band structure" \
  --structure Si \
  --work-dir runs_Si_lcao_example \
  --config config.yaml
```
