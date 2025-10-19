from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .logging_setup import resolve_log_dir


router = APIRouter()


def _read_lines(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        try:
            raw = path.read_bytes()
            return raw.decode("utf-8", errors="ignore").splitlines()
        except Exception:
            return []


def _extract_stack_from_json_line(line: str, target_id: str) -> Optional[str]:
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if str(obj.get("trace_id", "")) != target_id:
        return None
    exc = obj.get("exception")
    if isinstance(exc, str) and exc.strip():
        return exc
    return None


def _nearest_traceback_block(lines: List[str], index: int) -> Optional[str]:
    # Expand outwards from index to find a Traceback block
    start = index
    end = index
    n = len(lines)
    # Look backwards for a Traceback header
    s = index
    while s >= 0:
        if lines[s].startswith("Traceback (most recent call last):"):
            start = s
            break
        s -= 1
    # If not found before, check forward if the current line is the header
    if start == index and not lines[index].startswith("Traceback (most recent call last):"):
        s = index + 1
        while s < n and s - index < 100:
            if lines[s].startswith("Traceback (most recent call last):"):
                start = s
                break
            s += 1
    # Now find the end: a non-indented line after the stack or end of file
    e = start
    while e + 1 < n:
        line = lines[e + 1]
        if not line.startswith(" ") and not line.startswith("\t") and not line.startswith("File "):
            end = e + 1
            break
        e += 1
    if start != index and start >= 0 and start < n:
        # collect until end or next blank
        block = "\n".join(lines[start : (end if end > start else min(start + 50, n))])
        return block
    return None


def _collect_hits(log_dir: Path, trace_id: str, context: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    hits: List[Dict[str, Any]] = []
    best_stack: Optional[str] = None
    for path in sorted(log_dir.glob("*.log")):
        lines = _read_lines(path)
        if not lines:
            continue
        for idx, line in enumerate(lines):
            if trace_id not in line:
                continue
            start = max(0, idx - context)
            end = min(len(lines), idx + context + 1)
            hits.append(
                {
                    "file": str(path),
                    "line": idx + 1,
                    "context_before": lines[start:idx],
                    "line_text": line,
                    "context_after": lines[idx + 1 : end],
                }
            )
            if best_stack is None:
                # Try JSON extraction
                stack = _extract_stack_from_json_line(line, trace_id)
                if not stack:
                    stack = _nearest_traceback_block(lines, idx)
                if stack:
                    best_stack = stack
    return hits, best_stack


@router.get("/logs/{trace_id}")
async def get_logs(trace_id: str, request: Request, context: int = 200):
    # Clamp context to a reasonable upper bound
    context = max(0, min(int(context or 0), 400))
    log_dir = resolve_log_dir()
    if not log_dir.exists() or not log_dir.is_dir():
        raise HTTPException(status_code=404, detail="trace_id not found")
    hits, stack = _collect_hits(log_dir, trace_id, context)
    if not hits:
        raise HTTPException(status_code=404, detail="trace_id not found")
    return JSONResponse(
        content={
            "trace_id": trace_id,
            "hits": hits,
            "stacktrace": stack or "",
        }
    )


@router.head("/logs/{trace_id}")
async def head_logs(trace_id: str):
    log_dir = resolve_log_dir()
    if not log_dir.exists() or not log_dir.is_dir():
        raise HTTPException(status_code=404, detail="trace_id not found")
    for path in log_dir.glob("*.log"):
        try:
            if trace_id in path.read_text(encoding="utf-8", errors="ignore"):
                return Response(status_code=200)
        except Exception:
            continue
    raise HTTPException(status_code=404, detail="trace_id not found")

