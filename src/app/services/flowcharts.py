import re
from typing import Any


_CONTROL_CHARS_RE = re.compile(r"[\[\]{}()<>|\"`;]")
_WHITESPACE_RE = re.compile(r"\s+")


def render_student_flowchart_mermaid(result: Any) -> str:
    flowchart = _get(result, "solution_flowchart")
    if flowchart is None:
        return ""

    raw_nodes = _get(flowchart, "nodes")
    raw_edges = _get(flowchart, "edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return ""

    nodes = [_normalize_render_node(item) for item in raw_nodes]
    nodes = [item for item in nodes if item is not None]
    if len(nodes) < 2:
        return ""

    node_ids = {node["id"] for node in nodes}
    id_map = {node["id"]: f"N{index}" for index, node in enumerate(nodes, start=1)}
    edges = [
        edge
        for edge in (_normalize_render_edge(item) for item in raw_edges)
        if edge is not None and edge["from_id"] in node_ids and edge["to_id"] in node_ids
    ]
    if not edges:
        return ""

    lines = ["flowchart TD"]
    for node in nodes:
        lines.append(f"  {id_map[node['id']]}{_node_shape(node['kind'], node['label'])}")
    for edge in edges:
        from_id = id_map[edge["from_id"]]
        to_id = id_map[edge["to_id"]]
        label = edge["label"]
        if label:
            lines.append(f"  {from_id} -->|{label}| {to_id}")
        else:
            lines.append(f"  {from_id} --> {to_id}")
    return "\n".join(lines)


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _normalize_render_node(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    node_id = _clean_text(_get(value, "id"), max_length=32)
    label = _clean_text(_get(value, "label"), max_length=80)
    if not node_id or not label:
        return None
    return {
        "id": node_id,
        "label": label,
        "kind": _normalize_node_kind(_get(value, "kind")),
    }


def _normalize_render_edge(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    from_id = _clean_text(_get(value, "from_id"), max_length=32)
    to_id = _clean_text(_get(value, "to_id"), max_length=32)
    if not from_id or not to_id:
        return None
    return {
        "from_id": from_id,
        "to_id": to_id,
        "label": _clean_text(_get(value, "label"), max_length=24),
    }


def _normalize_node_kind(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"start", "input", "process", "decision", "output", "end"}:
        return text
    return "process"


def _clean_text(value: Any, *, max_length: int) -> str:
    text = _CONTROL_CHARS_RE.sub(" ", str(value or ""))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip()


def _node_shape(kind: str, label: str) -> str:
    if kind in {"start", "end"}:
        return f'(["{label}"])'
    if kind in {"input", "output"}:
        return f'[/"{label}"/]'
    if kind == "decision":
        return f'{{"{label}"}}'
    return f'["{label}"]'


__all__ = ["render_student_flowchart_mermaid"]
