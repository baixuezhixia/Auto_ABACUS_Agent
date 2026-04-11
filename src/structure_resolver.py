from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


IGNORED_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
}

IGNORED_DIR_PREFIXES = (
    "runs",
    "out.",
)


def resolve_structure(
    structure_input: Optional[str],
    work_dir: str,
    query: str,
    extra_search_roots: Optional[Sequence[str]] = None,
) -> Path:
    hint = (structure_input or "").strip()
    explicit = _resolve_explicit_path(hint)
    if explicit is not None:
        return explicit

    search_roots = _build_search_roots(work_dir, extra_search_roots)
    candidates = _discover_candidates(search_roots)
    if hint:
        hinted = [path for path in candidates if hint.lower() in str(path).lower()]
        if hinted:
            candidates = hinted
    if not candidates:
        searched = ", ".join(str(path) for path in search_roots)
        raise FileNotFoundError(
            "No ABACUS STRU file was found automatically. "
            f"Searched under: {searched}. "
            "Provide --structure explicitly or add a STRU file under examples/ or the working tree."
        )

    ranked = _rank_candidates(candidates, query=query, hint=hint, work_dir=work_dir)
    top_path, top_score = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == top_score and top_score <= 0:
        joined = "\n".join(f"- {path}" for path, _ in ranked[:8])
        raise FileNotFoundError(
            "Multiple STRU files were found and automatic selection is ambiguous. "
            "Pass --structure with a path or a more specific hint.\n"
            f"Candidates:\n{joined}"
        )
    return top_path


def _resolve_explicit_path(value: str) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    if candidate.is_dir():
        matches = _discover_candidates([candidate.resolve()])
        if len(matches) == 1:
            return matches[0]
        if matches:
            ranked = _rank_candidates(matches, query="", hint=value, work_dir=str(candidate))
            return ranked[0][0]
    return None


def _build_search_roots(work_dir: str, extra_search_roots: Optional[Sequence[str]]) -> List[Path]:
    repo_root = Path(__file__).resolve().parent.parent
    roots: List[Path] = []
    for raw in [work_dir, repo_root / "examples", repo_root, *(extra_search_roots or [])]:
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if path.exists() and path not in roots:
            roots.append(path)
    return roots


def _discover_candidates(search_roots: Iterable[Path]) -> List[Path]:
    found: List[Path] = []
    seen = set()
    for root in search_roots:
        if root.is_file() and root.name.upper() == "STRU":
            resolved = root.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
            continue
        if not root.is_dir():
            continue
        for path in root.rglob("STRU"):
            if not path.is_file() or _should_ignore(path):
                continue
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
    return found


def _should_ignore(path: Path) -> bool:
    lowered_parts = [part.lower() for part in path.parts]
    for part in lowered_parts:
        if part in IGNORED_DIR_NAMES:
            return True
        if any(part.startswith(prefix) for prefix in IGNORED_DIR_PREFIXES):
            return True
    return False


def _rank_candidates(
    candidates: Sequence[Path],
    query: str,
    hint: str,
    work_dir: str,
) -> List[Tuple[Path, int]]:
    query_tokens = _tokenize(query)
    hint_tokens = _tokenize(hint)
    work_dir_path = Path(work_dir).expanduser()
    if not work_dir_path.is_absolute():
        work_dir_path = Path.cwd() / work_dir_path
    work_dir_text = str(work_dir_path.resolve()).lower().replace("\\", "/")

    ranked: List[Tuple[Path, int]] = []
    for path in candidates:
        path_text = str(path).lower().replace("\\", "/")
        score = 0
        if "/examples/" in path_text:
            score += 40
        if "smoke" in path_text:
            score -= 10
        if work_dir_text in path_text:
            score += 20
        if hint and hint.lower() in path_text:
            score += 100
        score += sum(8 for token in hint_tokens if token in path_text)
        score += sum(3 for token in query_tokens if token in path_text)
        score -= len(path.parts)
        ranked.append((path, score))
    ranked.sort(key=lambda item: (-item[1], str(item[0])))
    return ranked


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[A-Za-z0-9_\\-]+", text.lower()) if len(token) >= 2]
