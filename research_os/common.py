from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any


PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
RUN_PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}
RESOURCE_DIR_NAMES = ("control_plane", "templates", "projects", "configs")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runtime_root() -> Path:
    source_root = repo_root()
    if all((source_root / name).exists() for name in RESOURCE_DIR_NAMES):
        return source_root
    bundled_root = Path(__file__).resolve().parent / "_resources"
    if all((bundled_root / name).exists() for name in RESOURCE_DIR_NAMES):
        return bundled_root
    return source_root


def resource_path(*parts: str) -> Path:
    return runtime_root().joinpath(*parts)


def resolve_within_root(root: str | Path, relative_path: str | Path) -> Path:
    base = Path(root).resolve()
    candidate = Path(relative_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base / candidate).resolve()
    resolved.relative_to(base)
    return resolved


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def iso_in(seconds: int) -> str:
    return (dt.datetime.now().replace(microsecond=0) + dt.timedelta(seconds=seconds)).isoformat()


def minutes_since(value: str | None) -> float:
    parsed = parse_iso(value)
    if parsed is None:
        return 0.0
    delta = dt.datetime.now(parsed.tzinfo).replace(microsecond=0) - parsed
    return max(delta.total_seconds() / 60.0, 0.0)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_json(path: str | Path, default: Any) -> Any:
    p = Path(path)
    if not p.exists():
        return deepcopy(default)
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return deepcopy(default)
    return json.loads(raw)


def save_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False, dir=p.parent, encoding="utf-8") as handle:
        handle.write(data)
        tmp_name = handle.name
    os.replace(tmp_name, p)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        rows.append(json.loads(raw))
    return rows


def append_jsonl(path: str | Path, payload: dict[str, Any]) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_text(path: str | Path, default: str = "") -> str:
    p = Path(path)
    if not p.exists():
        return default
    return p.read_text(encoding="utf-8")


def write_text(path: str | Path, content: str) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=p.parent, encoding="utf-8") as handle:
        handle.write(content)
        tmp_name = handle.name
    os.replace(tmp_name, p)


def append_text(path: str | Path, content: str) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(content)


def deep_merge(base: Any, payload: Any) -> Any:
    if isinstance(base, dict) and isinstance(payload, dict):
        merged = dict(base)
        for key, value in payload.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    if isinstance(base, list) and isinstance(payload, list):
        return base + deepcopy(payload)
    return deepcopy(payload)


def lookup_path(data: Any, dotted_path: str, default: Any = None) -> Any:
    if not dotted_path:
        return data
    cur = data
    for chunk in dotted_path.split("."):
        if isinstance(cur, dict) and chunk in cur:
            cur = cur[chunk]
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(chunk)]
                continue
            except (ValueError, IndexError):
                return default
        return default
    return cur


def coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def coerce_str_list(value: Any) -> list[str]:
    return [str(item) for item in coerce_list(value) if str(item).strip()]


def is_placeholder_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip().lower()
        return text in {
            "",
            "replace-me",
            "todo",
            "tbd",
            "placeholder",
            "replace-with-your-model",
            "replace-with-your-dataset",
        }
    if isinstance(value, dict):
        return not value or all(is_placeholder_value(v) for v in value.values())
    if isinstance(value, list):
        return len(value) == 0 or all(is_placeholder_value(v) for v in value)
    return False


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "item"


def sort_priority(priority: str) -> int:
    return PRIORITY_ORDER.get(priority, 99)


def sort_run_priority(priority: str) -> int:
    return RUN_PRIORITY_ORDER.get((priority or "normal").lower(), 99)


def sha256_file(path: str | Path) -> str:
    p = Path(path)
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def json_hash(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def clamp_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed
