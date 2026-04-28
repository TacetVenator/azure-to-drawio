"""Preview helpers for large JSON artifacts without loading full arrays into memory."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def _first_non_whitespace(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        while True:
            char = handle.read(1)
            if not char:
                return ""
            if not char.isspace():
                return char


def iter_json_array(path: Path, *, chunk_size: int = 64 * 1024) -> Iterator[Any]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as handle:
        buffer = ""
        pos = 0
        started = False
        eof = False

        while True:
            if not eof:
                chunk = handle.read(chunk_size)
                if chunk:
                    buffer += chunk
                else:
                    eof = True

            while True:
                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1

                if not started:
                    if pos >= len(buffer):
                        break
                    if buffer[pos] != "[":
                        raise ValueError("Preview only supports top-level JSON arrays or objects")
                    started = True
                    pos += 1
                    continue

                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1

                if pos < len(buffer) and buffer[pos] == "]":
                    return

                try:
                    item, next_pos = decoder.raw_decode(buffer, pos)
                except json.JSONDecodeError:
                    if eof:
                        raise ValueError("Malformed JSON array")
                    break

                yield item
                pos = next_pos

                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1

                if pos < len(buffer) and buffer[pos] == ",":
                    pos += 1
                    continue
                if pos < len(buffer) and buffer[pos] == "]":
                    return
                if eof and pos >= len(buffer):
                    return
                if pos >= len(buffer):
                    break

            if pos:
                buffer = buffer[pos:]
                pos = 0
            if eof and not buffer:
                return


def preview_json_artifact(path: Path, *, sample_limit: int = 50) -> dict[str, Any]:
    """Return a lightweight preview of a JSON artifact."""
    first_char = _first_non_whitespace(path)
    if not first_char:
        raise ValueError(f"Artifact is empty: {path}")

    if first_char == "[":
        sample = []
        total = 0
        for item in iter_json_array(path):
            total += 1
            if len(sample) < sample_limit:
                sample.append(item)
        return {
            "topLevelType": "array",
            "totalItems": total,
            "sampleCount": len(sample),
            "truncated": total > len(sample),
            "sample": sample,
        }

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        keys = sorted(data.keys())
        preview = {key: data[key] for key in keys[:sample_limit]}
        return {
            "topLevelType": "object",
            "totalKeys": len(keys),
            "sampleCount": len(preview),
            "truncated": len(keys) > len(preview),
            "sample": preview,
        }

    return {
        "topLevelType": type(data).__name__,
        "sampleCount": 1,
        "truncated": False,
        "sample": data,
    }