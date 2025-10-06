"""YAML compatibility helpers with an optional PyYAML dependency.

This module exposes :func:`safe_load` and :func:`safe_dump` with the same
signatures as the PyYAML helpers.  When PyYAML is available it is used
directly.  Otherwise a small fallback parser/serializer is used that supports
the subset of YAML required by the application (nested mappings, sequences and
simple scalar values).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping, Sequence, TextIO

import json


class YamlFallbackError(RuntimeError):
    """Raised when the built-in YAML fallback cannot parse the input."""


def _strip_inline_comment(text: str) -> str:
    in_single = False
    in_double = False
    for idx, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return text[:idx].rstrip()
    return text.rstrip()


@dataclass
class _Line:
    indent: int
    content: str


def _tokenise(text: str) -> Iterator[_Line]:
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise YamlFallbackError("Indentation must use multiples of two spaces")
        yield _Line(indent=indent, content=_strip_inline_comment(raw[indent:]))


def _parse_scalar(token: str) -> Any:
    lowered = token.lower()
    if lowered in {"", "null", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return json.loads(token)
    except json.JSONDecodeError:
        # Fall back to raw string; strip surrounding whitespace only.
        return token.strip()


def _parse_block(lines: Sequence[_Line], start: int, indent: int) -> tuple[Any, int]:
    items: list[Any] = []
    mapping: dict[str, Any] = {}
    mode: str | None = None  # "list" or "dict"
    idx = start
    while idx < len(lines):
        line = lines[idx]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise YamlFallbackError("Unexpected indentation")
        content = line.content
        if content.startswith("- ") or content == "-":
            if mode == "dict":
                raise YamlFallbackError("Mixed mapping and sequence content")
            mode = "list"
            entry = content[1:].strip()
            if not entry:
                value, idx = _parse_block(lines, idx + 1, indent + 2)
            else:
                key, sep, rest = entry.partition(":")
                if sep:
                    nested_value = rest.strip()
                    if not nested_value:
                        value, idx = _parse_block(lines, idx + 1, indent + 2)
                    else:
                        value = {key.strip(): _parse_scalar(nested_value)}
                        idx += 1
                else:
                    value = _parse_scalar(entry)
                    idx += 1
            items.append(value)
            continue
        if mode == "list":
            raise YamlFallbackError("Mixed mapping and sequence content")
        mode = "dict"
        key, sep, rest = content.partition(":")
        if not sep:
            raise YamlFallbackError("Expected ':' in mapping entry")
        key = key.strip()
        value_token = rest.strip()
        if not value_token:
            value, idx = _parse_block(lines, idx + 1, indent + 2)
        else:
            value = _parse_scalar(value_token)
            idx += 1
        mapping[key] = value
    if mode == "list":
        return items, idx
    if mode == "dict":
        return mapping, idx
    return {}, idx


def _fallback_safe_load(data: str | bytes | TextIO) -> Any:
    if hasattr(data, "read"):
        text = data.read()
    else:
        text = data
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    if not isinstance(text, str):
        raise YamlFallbackError("Unsupported YAML input type")
    stripped = text.strip()
    if not stripped:
        return None
    lines = list(_tokenise(text))
    if not lines:
        return None
    value, end = _parse_block(lines, 0, lines[0].indent)
    if end != len(lines):
        raise YamlFallbackError("Trailing content after parsing YAML block")
    return value


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(str(value))


def _dump_mapping(mapping: Mapping[Any, Any], indent: int, sort_keys: bool) -> list[str]:
    pad = " " * indent
    items = mapping.items()
    if sort_keys:
        items = sorted(items, key=lambda kv: str(kv[0]))  # type: ignore[arg-type]
    lines: list[str] = []
    for key, value in items:
        key_text = str(key)
        if isinstance(value, Mapping):
            if value:
                lines.append(f"{pad}{key_text}:")
                lines.extend(_dump_mapping(value, indent + 2, sort_keys))
            else:
                lines.append(f"{pad}{key_text}: {{}}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if value:
                lines.append(f"{pad}{key_text}:")
                lines.extend(_dump_sequence(value, indent + 2, sort_keys))
            else:
                lines.append(f"{pad}{key_text}: []")
        else:
            lines.append(f"{pad}{key_text}: {_format_scalar(value)}")
    return lines


def _dump_sequence(seq: Iterable[Any], indent: int, sort_keys: bool) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    for value in seq:
        if isinstance(value, Mapping):
            if value:
                lines.append(f"{pad}-")
                lines.extend(_dump_mapping(value, indent + 2, sort_keys))
            else:
                lines.append(f"{pad}- {{}}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if value:
                lines.append(f"{pad}-")
                lines.extend(_dump_sequence(value, indent + 2, sort_keys))
            else:
                lines.append(f"{pad}- []")
        else:
            lines.append(f"{pad}- {_format_scalar(value)}")
    return lines


def _fallback_safe_dump(data: Any, stream: Any | None = None, *, sort_keys: bool = False) -> str:
    if isinstance(data, Mapping):
        lines = _dump_mapping(data, 0, sort_keys)
        text = "\n".join(lines) + ("\n" if lines else "{}\n")
    elif isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        lines = _dump_sequence(data, 0, sort_keys)
        text = "\n".join(lines) + ("\n" if lines else "[]\n")
    else:
        text = _format_scalar(data) + "\n"
    if stream is not None:
        stream.write(text)
    return text


try:  # pragma: no cover - exercised indirectly in environments with PyYAML
    import yaml as _pyyaml  # type: ignore

    safe_load = _pyyaml.safe_load
    safe_dump = _pyyaml.safe_dump
    YAMLError = getattr(_pyyaml, "YAMLError", Exception)

    def have_pyyaml() -> bool:
        return True

except ModuleNotFoundError:  # pragma: no cover - covered by dedicated tests
    safe_load = _fallback_safe_load
    safe_dump = _fallback_safe_dump
    YAMLError = YamlFallbackError

    def have_pyyaml() -> bool:
        return False


__all__ = ["safe_load", "safe_dump", "have_pyyaml", "YAMLError"]

