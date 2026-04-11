# Agent Rebuild (Isolated)

This folder is an isolated prototype for rebuilding the DFT agent.

Current workflow:

1. Decode a natural-language scientific query into concrete calculation tasks.
2. Search Materials Project by formula or material ID.
3. Select one MP entry with layered filtering: hard rules first, optional LLM ranking second.
4. Download the selected conventional CIF.
5. Convert CIF to ABACUS `STRU`.
6. Generate per-task `INPUT` / `STRU` / `KPT` files.
7. Run ABACUS tasks in sequence and write `report.json`.

No files outside this folder are modified.

## What Is Implemented

- Task decoding
  - Rule-based decoder for common task intents:
    - scf
    - relax
    - band structure
    - density of states
    - elastic properties
  - Basic dependency expansion:
    - bands adds scf if missing
    - dos adds scf if missing
    - elastic adds relax and scf if missing
  - Optional LLM decoder mode:
    - set `decoder.mode = llm` or `auto` in `config.yaml`
    - the model must return JSON with `tasks[]`
    - if `mode = auto`, rule-based decoding is used as fallback when LLM fails

- Materials Project structure acquisition
  - Search Materials Project by `material_id` like `mp-149` or formula like `Si`
  - Layered candidate selection:
    - hard filters: exact formula match, drop deprecated entries, near-hull shortlist
    - optional LLM ranking on the shortlisted candidates
  - Record shortlisted candidates, scores, and reasons in `report.json`
  - Download the selected conventional CIF to `--work-dir/materials_project/`

- CIF to STRU conversion
  - Parse CIF with `pymatgen`
  - Reject disordered / partial-occupancy structures
  - Generate ABACUS `STRU` with explicit `LATTICE_VECTORS`
  - Resolve pseudopotential filenames from `abacus.pseudo_dir`

- ABACUS input generation and execution
  - Generate one task directory per calculation stage
  - Write `INPUT`, `STRU`, and `KPT`
  - Run ABACUS in sequence
  - Support `abacus.use_hwthread_cpus` and `abacus.oversubscribe`

## Actual Workflow

The current pipeline is:

1. `query` -> task list
2. `structure` -> MP search
3. MP candidates -> hard filtering -> optional LLM ranking
4. selected MP entry -> conventional CIF
5. CIF -> ABACUS `STRU`
6. `STRU` + defaults + task type -> per-task `INPUT/KPT/STRU`
7. ABACUS execution
8. `report.json`

## Quick Start

1. Install dependencies.

```bash
cd agent_rebuild
pip install -r requirements.txt
```

2. Copy config and edit your ABACUS / decoder settings.

```bash
cp config.example.yaml config.yaml
```

3. Set your Materials Project API key.

Preferred YAML form:

```yaml
MP_API_KEY: "your_materials_project_key"
```

4. Run the agent.

```bash
cd /home/yukino/TritonDFT-43C7/agent_rebuild
python3 src/main.py \
  --query "计算Si的结构弛豫，随后做能带和DOS" \
  --structure Si \
  --work-dir ./runs_mp \
  --config config.yaml
```

## Runtime Inputs

The runtime currently needs:

- `--query`: the natural-language science question
- `--structure`: a Materials Project material ID or formula, for example `mp-149`, `Si`, `SiO2`
- `--work-dir`: the output directory for generated files and reports
- `MP_API_KEY`: provided in `config.yaml` or the environment

If you already know the exact task sequence, you can bypass decoding and force the task list:

```bash
python src/main.py \
  --query "ignore this text" \
  --structure mp-149 \
  --work-dir ./runs_mp \
  --config config.yaml \
  --tasks scf,relax,bands,dos
```

## MP Selection Rule

If multiple Materials Project entries match, the agent uses two stages:

- Hard filtering:
  - exact formula match
  - non-deprecated entries preferred
  - near-hull shortlist using `energy_above_hull`
- Optional LLM ranking:
  - rank the hard-filtered shortlist with an OpenAI-compatible model
  - store `llm_score` and `llm_reason` in the report

If LLM ranking is disabled or unavailable, the agent falls back to the rule-ranked candidate.

## Output Layout

Each run currently creates files like these:

- `materials_project/<material_id>.cif`
- `materials_project/<material_id>.STRU`
- `01_relax/INPUT`, `01_relax/STRU`, `01_relax/KPT`
- `02_scf/INPUT`, `02_scf/STRU`, `02_scf/KPT`
- `...`
- `report.json`

Example:

- `./runs_mp/materials_project/mp-149.cif`
- `./runs_mp/materials_project/mp-149.STRU`
- `./runs_mp/01_relax/INPUT`
- `./runs_mp/report.json`

`report.json` includes:

- decoded task plan
- selected Materials Project structure
- shortlisted MP candidates
- LLM scores and reasons when available
- execution results per task
- stdout / stderr tails for failed runs

## LLM Task Decoding

To let LLM decode the task graph:

```yaml
decoder:
  mode: "llm"
  model: "gpt-4o-mini"
  base_url: "https://api.openai.com/v1"
  api_key: ""
  temperature: 0.0
  timeout: 180
```

Export `OPENAI_API_KEY` or put `api_key` in `config.yaml`.

## Configuration Summary

`config.yaml` controls:

- `abacus.executable`
- `abacus.run_mode`
- `abacus.np`
- `abacus.use_hwthread_cpus`
- `abacus.oversubscribe`
- `abacus.pseudo_dir`
- `abacus.orb_dir`
- `defaults.calculation.*`
- `decoder.mode`
- `decoder.model`
- `decoder.base_url`
- `decoder.api_key`
- `decoder.timeout`
- `mp_selection.hard_limit`
- `mp_selection.llm.*`
- `MP_API_KEY`

## Current Limitations

- The current implementation generates conventional-cell `STRU` from MP CIF by default.
- `defaults.calculation` is still a fixed default parameter block. It is not yet adapted dynamically from the user's scientific question, material system, or calculation intent.
- The current task decoder can decide task types and dependencies, but it does not yet synthesize calculation parameters such as `ecutwfc`, `kmesh`, smearing settings, or convergence thresholds from the query.
- `elastic` is still only represented at the task-planning level; there is no full strain workflow yet.
- Long production runs may require manual execution and monitoring of ABACUS outside this wrapper.
