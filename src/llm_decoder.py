#LLM 版 task_decoder。
#它调用 OpenAI 兼容接口，让模型直接输出 JSON 任务列表，然后转换成内部任务结构

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List

from schema import CalcTask, TaskType


ALLOWED_TASKS = [t.value for t in TaskType]


def decode_tasks_with_llm(query: str, decoder_cfg: Dict[str, Any]) -> List[CalcTask]:
    payload = _build_payload(query, decoder_cfg)
    response_text = _call_openai_compatible_api(payload, decoder_cfg)
    parsed = _extract_json(response_text)
    return _to_tasks(parsed)


def _build_payload(query: str, decoder_cfg: Dict[str, Any]) -> Dict[str, Any]:
    model = decoder_cfg.get("model", "gpt-4o-mini")
    temperature = float(decoder_cfg.get("temperature", 0.0))
    system_prompt = decoder_cfg.get("system_prompt") or _default_system_prompt()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]
    return {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }


def _default_system_prompt() -> str:
    return (
        "You are a strict task decoder for ABACUS DFT workflows.\n"
        "Convert the user's scientific query into a JSON object only.\n"
        "Allowed task_type values: scf, relax, bands, dos, elastic.\n"
        "Rules:\n"
        "- If bands or dos appears, include scf first.\n"
        "- If elastic appears, include relax and scf before it.\n"
        "- depends_on may use either task ids like t1_scf or task types like scf.\n"
        "- Use short Chinese or English descriptions.\n"
        "- Output only JSON, no markdown, no prose.\n"
        "Expected schema:\n"
        "{\n"
        "  \"tasks\": [\n"
        "    {\n"
        "      \"task_type\": \"scf\",\n"
        "      \"description\": \"...\",\n"
        "      \"depends_on\": [],\n"
        "      \"params\": {}\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )


def _call_openai_compatible_api(payload: Dict[str, Any], decoder_cfg: Dict[str, Any]) -> str:
    base_url = decoder_cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")
    if not base_url:
        base_url = "https://api.openai.com/v1"
    url = base_url.rstrip("/") + "/chat/completions"

    api_key = decoder_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("LLM decoder requires api_key or OPENAI_API_KEY")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    timeout = float(decoder_cfg.get("timeout", 60.0))

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"LLM decoder HTTP error {exc.code}: {details or exc.reason}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("LLM decoder returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if not content.strip():
        raise RuntimeError("LLM decoder returned empty content")
    return content


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"LLM response did not contain JSON: {text[:200]}")


def _to_tasks(payload: Dict[str, Any]) -> List[CalcTask]:
    items = payload.get("tasks")
    if not isinstance(items, list) or not items:
        raise ValueError("LLM payload must contain non-empty tasks array")

    tasks: List[CalcTask] = []
    task_ids: List[str] = []
    task_types: Dict[str, List[str]] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Task entry #{index} is not an object")
        task_type_str = str(item.get("task_type", "")).strip().lower()
        if task_type_str not in ALLOWED_TASKS:
            raise ValueError(f"Unsupported task_type: {task_type_str}")
        task_type = TaskType(task_type_str)
        task_id = item.get("task_id") or f"t{index}_{task_type.value}"
        depends_on = item.get("depends_on") or []
        if not isinstance(depends_on, list):
            raise ValueError(f"depends_on must be a list for task {task_id}")
        params = item.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError(f"params must be an object for task {task_id}")

        tasks.append(
            CalcTask(
                task_id=str(task_id),
                task_type=task_type,
                description=str(item.get("description", f"Run {task_type.value}")),
                depends_on=[str(dep) for dep in depends_on],
                params=params,
            )
        )
        task_id_str = str(task_id)
        task_ids.append(task_id_str)
        task_types.setdefault(task_type.value, []).append(task_id_str)

    for task in tasks:
        normalized_deps: List[str] = []
        for dep in task.depends_on:
            normalized_deps.append(_resolve_dependency(dep, task_ids, task_types))
        task.depends_on = normalized_deps

    return tasks


def _resolve_dependency(dep: str, task_ids: List[str], task_types: Dict[str, List[str]]) -> str:
    dep_str = str(dep).strip()
    if dep_str in task_ids:
        return dep_str

    matches = task_types.get(dep_str.lower(), [])
    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        raise ValueError(
            f"Dependency '{dep_str}' is ambiguous because multiple tasks share this type: {matches}. "
            "Use task ids instead."
        )

    raise ValueError(f"Task depends on unknown task id or type: {dep_str}")
