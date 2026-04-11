from __future__ import annotations

import json
import os
import typing
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pymatgen.core import Composition

from schema import StructureArtifact


SEARCH_FIELDS = [
    "material_id",
    "formula_pretty",
    "symmetry",
    "energy_above_hull",
    "is_stable",
    "theoretical",
    "deprecated",
]


def fetch_conventional_cif(
    structure_input: str,
    work_dir: str,
    query: str = "",
    selection_cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[StructureArtifact, List[str]]:
    raw_input = structure_input.strip()
    if not raw_input:
        raise ValueError("Structure input is required and must be a Materials Project material ID or formula.")

    api_key = os.environ.get("MP_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("MP_API_KEY is not set. Export MP_API_KEY before running the agent.")

    _ensure_typing_compatibility()

    try:
        from mp_api.client import MPRester
    except ImportError as exc:
        raise ImportError(
            "mp-api could not be imported in the current Python environment. "
            "Check the installed dependency versions or upgrade Python."
        ) from exc

    notices: List[str] = []
    with MPRester(api_key) as mpr:
        docs = _search_docs(mpr, raw_input)
        if not docs:
            raise FileNotFoundError(f"No Materials Project entries found for '{raw_input}'.")

        selected, candidates, selection_notices = _select_doc(
            raw_input=raw_input,
            query=query,
            docs=docs,
            selection_cfg=selection_cfg or {},
        )
        notices.extend(selection_notices)
        selected_id = str(_field(selected, "material_id"))
        structure = mpr.get_structure_by_material_id(selected_id, conventional_unit_cell=True)

    cif_path = _cif_path(work_dir, selected_id)
    try:
        structure.to(filename=str(cif_path))
    except Exception as exc:
        raise RuntimeError(f"Failed to write CIF for {selected_id}: {exc}") from exc

    artifact = StructureArtifact(
        source="materials_project",
        input=raw_input,
        material_id=selected_id,
        formula=str(_field(selected, "formula_pretty") or raw_input),
        cif_path=str(cif_path.resolve()),
        lattice_type="conventional",
        candidates=candidates,
    )
    return artifact, notices


def _ensure_typing_compatibility() -> None:
    if hasattr(typing, "NotRequired") and hasattr(typing, "Required"):
        return
    try:
        from typing_extensions import NotRequired, Required
    except ImportError:
        return
    if not hasattr(typing, "NotRequired"):
        typing.NotRequired = NotRequired
    if not hasattr(typing, "Required"):
        typing.Required = Required


def _search_docs(mpr: Any, raw_input: str):
    if raw_input.lower().startswith("mp-"):
        return mpr.materials.summary.search(material_ids=[raw_input], fields=SEARCH_FIELDS)
    return mpr.materials.summary.search(formula=raw_input, fields=SEARCH_FIELDS)


def _select_doc(
    raw_input: str,
    query: str,
    docs: List[Any],
    selection_cfg: Dict[str, Any],
) -> Tuple[Any, List[Dict[str, Any]], List[str]]:
    if raw_input.lower().startswith("mp-"):
        selected = docs[0]
        candidates = [_candidate_payload(doc, raw_input) for doc in docs[:5]]
        return selected, candidates, []

    notices: List[str] = []
    hard_limit = max(1, int(selection_cfg.get("hard_limit", 5)))
    llm_cfg = selection_cfg.get("llm", {})

    enriched = [_candidate_payload(doc, raw_input) for doc in docs]
    current = [item for item in enriched if item["material_id"]]
    stage = "search"

    exact_formula = [item for item in current if item["formula_match"]]
    if exact_formula:
        current = exact_formula
        stage = "formula_match"

    non_deprecated = [item for item in current if not item["deprecated"]]
    if non_deprecated:
        current = non_deprecated
        stage = "drop_deprecated"

    if any(item["energy_above_hull"] is not None for item in current):
        min_ehull = min(item["energy_above_hull"] for item in current if item["energy_above_hull"] is not None)
        near_hull = [
            item for item in current if item["energy_above_hull"] is not None and item["energy_above_hull"] <= min_ehull + 0.05
        ]
        if near_hull:
            current = near_hull
            stage = "near_hull"

    current = sorted(current, key=_rule_sort_key)
    shortlisted = current[:hard_limit]
    selected = shortlisted[0]

    if len(docs) > 1:
        notices.append(
            f"Materials Project search for '{raw_input}' returned {len(docs)} matches. "
            f"Hard filtering kept {len(shortlisted)} candidates after {stage}."
        )

    if len(shortlisted) > 1:
        llm_candidates, llm_notice = _rank_candidates_with_llm(
            raw_input=raw_input,
            query=query,
            candidates=shortlisted,
            llm_cfg=llm_cfg,
        )
        if llm_candidates:
            shortlisted = llm_candidates
            selected = shortlisted[0]
            notices.append(llm_notice)
        elif llm_notice:
            notices.append(llm_notice)
    elif len(docs) > 1:
        notices.append(f"Rule filtering selected a single candidate: {selected['material_id']}.")

    return _doc_by_id(docs, selected["material_id"]), shortlisted, notices


def _rank_candidates_with_llm(
    raw_input: str,
    query: str,
    candidates: List[Dict[str, Any]],
    llm_cfg: Dict[str, Any],
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    enabled = bool(llm_cfg.get("enabled", True))
    if not enabled:
        return None, "MP selector LLM ranking disabled. Using rule-ranked candidate."

    api_key = llm_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "MP selector LLM ranking skipped because OPENAI_API_KEY is not set. Using rule-ranked candidate."

    try:
        payload = _build_llm_payload(raw_input, query, candidates, llm_cfg)
        response_text = _call_openai_compatible_api(payload, llm_cfg)
        ranked = _apply_llm_ranking(candidates, response_text)
    except Exception as exc:
        return None, f"MP selector LLM ranking failed ({exc}). Using rule-ranked candidate."

    selected = ranked[0]
    notice = f"MP selector chose {selected['material_id']} after LLM ranking over {len(ranked)} hard-filtered candidates."
    return ranked, notice


def _build_llm_payload(
    raw_input: str,
    query: str,
    candidates: List[Dict[str, Any]],
    llm_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    model = llm_cfg.get("model", "gpt-4o-mini")
    temperature = float(llm_cfg.get("temperature", 0.0))
    system_prompt = (
        "You are ranking Materials Project search candidates for a DFT agent.\n"
        "First respect the exact chemical formula. Then prefer stable, non-deprecated, representative bulk entries.\n"
        "Use the user query only to break ties by scientific intent.\n"
        "Return JSON only in this schema:\n"
        "{\n"
        '  "selected_id": "mp-xxx",\n'
        '  "ranked": [{"material_id": "mp-xxx", "score": 0.0, "reason": "..."}]\n'
        "}\n"
        "Scores must be between 0 and 1."
    )
    user_payload = {
        "structure_input": raw_input,
        "query": query,
        "candidates": [
            {
                "material_id": item["material_id"],
                "formula": item["formula"],
                "spacegroup": item["spacegroup"],
                "energy_above_hull": item["energy_above_hull"],
                "is_stable": item["is_stable"],
                "theoretical": item["theoretical"],
                "deprecated": item["deprecated"],
                "rule_rank": index,
            }
            for index, item in enumerate(candidates, start=1)
        ],
    }
    return {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }


def _call_openai_compatible_api(payload: Dict[str, Any], llm_cfg: Dict[str, Any]) -> str:
    base_url = llm_cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    url = base_url.rstrip("/") + "/chat/completions"
    api_key = llm_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("api_key is required")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    timeout = float(llm_cfg.get("timeout", 60.0))

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code}: {details or exc.reason}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("no choices returned")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if not content.strip():
        raise RuntimeError("empty content returned")
    return content


def _apply_llm_ranking(candidates: List[Dict[str, Any]], response_text: str) -> List[Dict[str, Any]]:
    payload = _extract_json(response_text)
    ranked = payload.get("ranked")
    if not isinstance(ranked, list) or not ranked:
        raise ValueError("ranked list missing from LLM response")

    candidate_map = {item["material_id"]: dict(item) for item in candidates}
    ordered: List[Dict[str, Any]] = []
    seen = set()
    for entry in ranked:
        if not isinstance(entry, dict):
            continue
        material_id = str(entry.get("material_id") or "").strip()
        if not material_id or material_id not in candidate_map or material_id in seen:
            continue
        item = candidate_map[material_id]
        item["llm_score"] = float(entry.get("score", 0.0) or 0.0)
        item["llm_reason"] = str(entry.get("reason") or "")
        ordered.append(item)
        seen.add(material_id)

    if not ordered:
        raise ValueError("LLM ranking did not reference valid candidate ids")

    for item in candidates:
        if item["material_id"] not in seen:
            ordered.append(item)
    return ordered


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"LLM response did not contain JSON: {text[:200]}")


def _cif_path(work_dir: str, material_id: str) -> Path:
    root = Path(work_dir).resolve() / "materials_project"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{material_id}.cif"


def _candidate_payload(doc: Any, raw_input: str) -> Dict[str, Any]:
    symmetry = _field(doc, "symmetry")
    symbol = getattr(symmetry, "symbol", None) if symmetry is not None else None
    formula = str(_field(doc, "formula_pretty") or "")
    return {
        "material_id": str(_field(doc, "material_id") or ""),
        "formula": formula,
        "spacegroup": symbol or "",
        "energy_above_hull": _field(doc, "energy_above_hull"),
        "is_stable": bool(_field(doc, "is_stable")),
        "theoretical": bool(_field(doc, "theoretical")),
        "deprecated": bool(_field(doc, "deprecated")),
        "formula_match": _normalized_formula(formula) == _normalized_formula(raw_input),
    }


def _field(doc: Any, name: str):
    if isinstance(doc, dict):
        return doc.get(name)
    return getattr(doc, name, None)


def _doc_by_id(docs: List[Any], material_id: str) -> Any:
    for doc in docs:
        if str(_field(doc, "material_id") or "") == material_id:
            return doc
    raise KeyError(f"Materials Project candidate not found: {material_id}")


def _rule_sort_key(item: Dict[str, Any]) -> Tuple[Any, ...]:
    ehull = item["energy_above_hull"]
    return (
        0 if item["formula_match"] else 1,
        0 if not item["deprecated"] else 1,
        0 if item["is_stable"] else 1,
        ehull if ehull is not None else 999.0,
        1 if item["theoretical"] else 0,
        item["material_id"],
    )


def _normalized_formula(text: str) -> str:
    try:
        return Composition(text).reduced_formula.replace(" ", "")
    except Exception:
        return text.replace(" ", "").lower()
