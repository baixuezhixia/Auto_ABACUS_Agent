"""Materials Project structure provider.

The provider preserves the current repository's MP-first behavior while
isolating MP-specific API access, candidate selection, and CIF persistence
behind the ``StructureProvider`` interface.
"""

from __future__ import annotations

import os
import re
import typing
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from autodft.core.enums import ArtifactType
from autodft.core.exceptions import ConfigurationError, StructureResolutionError
from autodft.core.models import ResolvedStructure
from autodft.structures.base import StructureProvider
from autodft.structures.structure_object import (
    StructureCandidate,
    make_artifact,
    make_resolved_structure,
)


SEARCH_FIELDS = [
    "material_id",
    "formula_pretty",
    "symmetry",
    "energy_above_hull",
    "is_stable",
    "theoretical",
    "deprecated",
]

ClientFactory = Callable[[str], Any]


class MaterialsProjectProvider(StructureProvider):
    """Resolve Materials Project material IDs or formulas to conventional CIFs."""

    name = "materials_project"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        selection_config: Optional[Dict[str, Any]] = None,
        client_factory: Optional[ClientFactory] = None,
    ) -> None:
        self.api_key = api_key
        self.selection_config = dict(selection_config or {})
        self.client_factory = client_factory

    def can_resolve(self, structure_input: str) -> bool:
        """Return true for MP material IDs and formula-like text.

        Future local providers should be ordered before this provider so local
        file paths can be claimed before formula fallback.
        """

        value = structure_input.strip()
        return bool(value) and (is_material_id(value) or _looks_formula_like(value))

    def resolve(
        self,
        structure_input: str,
        work_dir: str,
        *,
        query: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> ResolvedStructure:
        """Resolve an MP material ID or formula and write a conventional CIF."""

        raw_input = structure_input.strip()
        if not raw_input:
            raise StructureResolutionError(
                "Structure input is required and must be a Materials Project material ID or formula."
            )

        api_key = self._resolve_api_key(config or {})
        selection_config = dict(self.selection_config)
        selection_config.update((config or {}).get("mp_selection", {}))

        with self._open_client(api_key) as client:
            docs = _search_docs(client, raw_input)
            if not docs:
                raise StructureResolutionError(f"No Materials Project entries found for '{raw_input}'.")

            selected, candidates, notices = select_materials_project_doc(
                raw_input=raw_input,
                query=query,
                docs=docs,
                selection_config=selection_config,
            )
            selected_id = str(_field(selected, "material_id") or "")
            if not selected_id:
                raise StructureResolutionError(f"Materials Project entry for '{raw_input}' has no material_id.")
            structure = client.get_structure_by_material_id(selected_id, conventional_unit_cell=True)

        cif_path = _cif_path(work_dir, selected_id)
        try:
            structure.to(filename=str(cif_path))
        except Exception as exc:
            raise StructureResolutionError(f"Failed to write CIF for {selected_id}: {exc}") from exc

        return make_resolved_structure(
            provider=self.name,
            raw_input=raw_input,
            query=query,
            structure_id=selected_id,
            formula=str(_field(selected, "formula_pretty") or raw_input),
            lattice_type="conventional",
            artifacts=[
                make_artifact(
                    ArtifactType.CIF,
                    cif_path,
                    label="conventional_cif",
                    metadata={"source": self.name},
                )
            ],
            candidates=candidates,
            metadata={"notices": notices},
        )

    def _resolve_api_key(self, config: Dict[str, Any]) -> str:
        api_key = (
            self.api_key
            or config.get("MP_API_KEY")
            or config.get("mp_api_key")
            or os.environ.get("MP_API_KEY")
            or ""
        )
        api_key = str(api_key).strip()
        if not api_key:
            raise ConfigurationError("MP_API_KEY is not set. Provide MP_API_KEY before resolving Materials Project structures.")
        return api_key

    def _open_client(self, api_key: str) -> Any:
        if self.client_factory is not None:
            return self.client_factory(api_key)

        _ensure_typing_compatibility()
        try:
            from mp_api.client import MPRester
        except ImportError as exc:
            raise ConfigurationError(
                "mp-api could not be imported in the current Python environment. "
                "Install project dependencies before using Materials Project resolution."
            ) from exc
        return MPRester(api_key)


def is_material_id(value: str) -> bool:
    """Return whether an input looks like a Materials Project material ID."""

    return re.fullmatch(r"mp-\d+", value.strip(), flags=re.IGNORECASE) is not None


def select_materials_project_doc(
    *,
    raw_input: str,
    query: str,
    docs: List[Any],
    selection_config: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, List[Dict[str, Any]], List[str]]:
    """Select an MP summary document using deterministic phase-1 rules."""

    if not docs:
        raise StructureResolutionError(f"No Materials Project entries found for '{raw_input}'.")

    if is_material_id(raw_input):
        selected = docs[0]
        candidates = [_candidate_payload(doc, raw_input) for doc in docs[:5]]
        return selected, candidates, []

    notices: List[str] = []
    hard_limit = max(1, int((selection_config or {}).get("hard_limit", 5)))

    current = [_candidate_payload(doc, raw_input) for doc in docs]
    current = [item for item in current if item["material_id"]]
    if not current:
        raise StructureResolutionError(f"Materials Project search for '{raw_input}' returned entries without material IDs.")

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
            item
            for item in current
            if item["energy_above_hull"] is not None and item["energy_above_hull"] <= min_ehull + 0.05
        ]
        if near_hull:
            current = near_hull
            stage = "near_hull"

    shortlisted = sorted(current, key=_rule_sort_key)[:hard_limit]
    selected = shortlisted[0]

    if len(docs) > 1:
        notices.append(
            f"Materials Project search for '{raw_input}' returned {len(docs)} matches. "
            f"Rule filtering kept {len(shortlisted)} candidates after {stage}."
        )

    _ = query
    return _doc_by_id(docs, selected["material_id"]), shortlisted, notices


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


def _search_docs(client: Any, raw_input: str) -> List[Any]:
    if is_material_id(raw_input):
        return list(client.materials.summary.search(material_ids=[raw_input], fields=SEARCH_FIELDS))
    return list(client.materials.summary.search(formula=raw_input, fields=SEARCH_FIELDS))


def _cif_path(work_dir: str, material_id: str) -> Path:
    root = Path(work_dir).resolve() / "materials_project"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{material_id}.cif"


def _candidate_payload(doc: Any, raw_input: str) -> Dict[str, Any]:
    candidate = StructureCandidate(
        structure_id=str(_field(doc, "material_id") or ""),
        formula=str(_field(doc, "formula_pretty") or ""),
        spacegroup=_spacegroup_symbol(_field(doc, "symmetry")),
        energy_above_hull=_field(doc, "energy_above_hull"),
        is_stable=bool(_field(doc, "is_stable")),
        theoretical=bool(_field(doc, "theoretical")),
        deprecated=bool(_field(doc, "deprecated")),
        formula_match=_normalized_formula(str(_field(doc, "formula_pretty") or "")) == _normalized_formula(raw_input),
    )
    return candidate.to_dict()


def _spacegroup_symbol(symmetry: Any) -> str:
    if symmetry is None:
        return ""
    if isinstance(symmetry, dict):
        return str(symmetry.get("symbol") or "")
    return str(getattr(symmetry, "symbol", "") or "")


def _field(doc: Any, name: str) -> Any:
    if isinstance(doc, dict):
        return doc.get(name)
    return getattr(doc, name, None)


def _doc_by_id(docs: List[Any], material_id: str) -> Any:
    for doc in docs:
        if str(_field(doc, "material_id") or "") == material_id:
            return doc
    raise StructureResolutionError(f"Materials Project candidate not found: {material_id}")


def _rule_sort_key(item: Dict[str, Any]) -> Tuple[Any, ...]:
    energy_above_hull = item["energy_above_hull"]
    return (
        0 if item["formula_match"] else 1,
        0 if not item["deprecated"] else 1,
        0 if item["is_stable"] else 1,
        energy_above_hull if energy_above_hull is not None else 999.0,
        1 if item["theoretical"] else 0,
        item["material_id"],
    )


def _normalized_formula(text: str) -> str:
    try:
        from pymatgen.core import Composition

        return Composition(text).reduced_formula.replace(" ", "")
    except Exception:
        return text.replace(" ", "").lower()


def _looks_formula_like(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", value.strip()) is not None


__all__ = [
    "MaterialsProjectProvider",
    "SEARCH_FIELDS",
    "is_material_id",
    "select_materials_project_doc",
]

