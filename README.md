# Agent Rebuild

This repository contains an isolated Python prototype for running ABACUS DFT workflows from a natural-language request and a Materials Project structure reference.

The agent currently:

1. Decodes a user query into an ordered calculation workflow, including the common four-task `relax -> scf -> bands -> dos` flow.
2. Searches Materials Project by material ID or formula.
3. Selects a Materials Project entry with deterministic filters and optional LLM ranking.
4. Downloads a conventional-cell CIF.
5. Converts the CIF to an ABACUS `STRU`.
6. Generates one ABACUS task directory per calculation stage.
7. Runs ABACUS tasks in dependency order.
8. Parses basic run metrics and writes `report.json`.

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

The workflow is normalized before execution. The common four-task electronic-structure sequence is:

```text
relax -> scf -> bands -> dos
```

`elastic` remains an optional fifth task type and is ordered after the electronic-structure tasks when requested.

Dependency rules:

- `bands`, `dos`, and `elastic` add `scf` if missing.
- `elastic` adds `relax` if missing.
- `scf` depends on `relax` when both are present.
- `bands` and `dos` depend on `scf` when present.

The implemented basis modes are `pw` and `lcao`. If the query explicitly mentions either token, that basis hint is propagated into every decoded task. In ABACUS input generation, `lcao` enables the `NUMERICAL_ORBITAL` block and requires configured orbital files.

### Materials Project structure resolution

`--structure` must be one of:

- A Materials Project material ID, such as `mp-149`.
- A formula, such as `Si` or `SiO2`.

For material IDs, the agent fetches that exact entry. For formula searches, the agent ranks candidates with:

- Exact reduced-formula matching.
- Deprecated-entry filtering.
- Near-hull filtering using `energy_above_hull`.
- Rule sorting by stability, hull distance, theoretical flag, and material ID.
- Optional LLM ranking over the hard-filtered shortlist.

The selected conventional structure is downloaded as:

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
- `bands` and `dos` stage charge-density restart files from the dependency task into `READ_CHG` when available.
- If a relaxation dependency produced `OUT.<task_id>/STRU.cif`, downstream tasks use a converted relaxed `STRU`.

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

Set your Materials Project API key in either the environment:

```bash
export MP_API_KEY="your_materials_project_key"
```

or in `config.yaml`:

```yaml
MP_API_KEY: "your_materials_project_key"
```

Run a workflow:

```bash
python3 src/main.py \
  --query "计算Si的结构弛豫，随后做能带和DOS" \
  --structure Si \
  --work-dir ./runs_mp \
  --config config.yaml
```

Force the four-task calculation sequence explicitly and bypass query decoding:

```bash
python3 src/main.py \
  --query "manual run" \
  --structure mp-149 \
  --work-dir ./runs_manual \
  --config config.yaml \
  --tasks relax,scf,bands,dos
```

## Runtime Inputs

Required command-line inputs:

- `--query`: natural-language scientific request.
- `--structure`: Materials Project material ID or formula.

Optional command-line inputs:

- `--work-dir`: output directory, default `./runs`.
- `--config`: YAML config path, default `config.yaml`.
- `--tasks`: comma-separated task list. When set, this bypasses automatic task decoding.

Required runtime resources:

- `MP_API_KEY` in `config.yaml` or the environment.
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
    ecutrho: 640
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
  report.json
```

`report.json` contains:

- Original query.
- Selected Materials Project structure.
- Candidate shortlist and LLM scores when available.
- Notices from selection, conversion, and dependency handling.
- Normalized task plan.
- Per-task execution results.
- Parsed metrics.
- stdout and stderr tails for debugging failed runs.

## Current Limitations

- Structures are currently sourced only from Materials Project; local CIF or local STRU input is not implemented.
- MP structures are downloaded as conventional cells.
- Disordered or partial-occupancy CIFs are rejected during CIF-to-STRU conversion.
- Calculation parameters mostly come from `defaults.calculation`; the agent does not yet infer `ecutwfc`, k-mesh density, smearing, convergence thresholds, or magnetism from the query or material.
- `elastic` is represented as a task and currently generates an ABACUS `scf`-style input with relaxation-related thresholds; a full strain/deformation elastic workflow is not implemented.
- Both `pw` and `lcao` input generation are wired in; `lcao` still needs broader validation against production ABACUS workflows.
- Long ABACUS production runs still need normal HPC scheduling, monitoring, and resource management outside this wrapper.


