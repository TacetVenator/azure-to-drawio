"""Terminal review workflow for deep-discovery related candidates."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from .config import Config
from .discover import _DEEP_REASON_FIELD, _load_inventory_artifact, write_related_review_report
from .util import load_json_file, normalize_id

_HELP_TEXT = """Commands:
  list                      Show the current filtered candidate list
  filter <text>             Filter by name, type, group, id, or explanation text
  clear                     Clear the active filter
  open <n>                  Show one candidate in detail
  keep <n>                  Keep one candidate in the promoted file
  drop <n>                  Drop one candidate from the promoted file
  keep-all                  Keep every candidate in the current filtered list
  drop-all                  Drop every candidate in the current filtered list
  props <n> [path]          Pretty-print JSON for a candidate subtree (default: full item)
  save                      Write the promoted JSON and refresh the review report
  help                      Show this help text
  quit                      Exit without additional changes
"""


def _candidate_context(candidate: Dict[str, Any]) -> str:
    parts = [
        candidate.get("name", ""),
        candidate.get("type", ""),
        candidate.get("resourceGroup", ""),
        candidate.get("subscriptionId", ""),
        candidate.get("id", ""),
    ]
    for evidence in candidate.get(_DEEP_REASON_FIELD, []):
        parts.append(evidence.get("explanation", ""))
        for related in evidence.get("relatedResources") or []:
            parts.append(related.get("name", ""))
            parts.append(related.get("matchedTerms", ""))
            parts.append(related.get("association", ""))
    return "\n".join(parts).lower()


def _format_candidate_line(idx: int, candidate: Dict[str, Any], kept: bool) -> str:
    marker = "KEEP" if kept else "DROP"
    return (
        f"[{idx}] {marker:<4} {candidate.get('name', '<unnamed>')} | "
        f"{candidate.get('type', '')} | {candidate.get('resourceGroup', '')}"
    )


def _resolve_path(obj: Any, path: str) -> Any:
    current = obj
    if not path:
        return current
    for raw_part in path.split('.'):
        part = raw_part
        while True:
            if '[' in part:
                field, remainder = part.split('[', 1)
                if field:
                    if not isinstance(current, dict):
                        raise KeyError(field)
                    current = current[field]
                index_text, remainder = remainder.split(']', 1)
                if not isinstance(current, list):
                    raise KeyError(index_text)
                current = current[int(index_text)]
                part = remainder.lstrip('.')
                if not part:
                    break
            else:
                if not isinstance(current, dict):
                    raise KeyError(part)
                current = current[part]
                break
    return current


def _load_candidates(path: Path, context: str) -> List[Dict[str, Any]]:
    return load_json_file(
        path,
        context=context,
        expected_type=list,
        advice=f"Fix {path.name} or rerun the producing stage.",
    )


def run_review_related(cfg: Config, *, input_fn=input, output: Optional[TextIO] = None) -> None:
    if not cfg.deepDiscovery.enabled:
        raise ValueError("deepDiscovery.enabled must be true to review related candidates")

    out = output or sys.stdout
    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError("inventory.json not found. Run 'expand' or 'run' first.")
    inventory = _load_inventory_artifact(inv_path, "Deep discovery base inventory")

    candidate_path = cfg.deep_out(cfg.deepDiscovery.candidateFile)
    promoted_path = cfg.deep_out(cfg.deepDiscovery.promotedFile)
    if not candidate_path.exists():
        raise FileNotFoundError(f"Candidate file not found at {candidate_path}. Run 'related-candidates' first.")
    if not promoted_path.exists():
        raise FileNotFoundError(f"Promoted related resource file not found at {promoted_path}. Run 'related-candidates' first.")

    candidates = _load_candidates(candidate_path, "Deep discovery candidate file")
    promoted = _load_candidates(promoted_path, "Deep discovery promoted file")
    kept_ids = {normalize_id(item.get("id", "")) for item in promoted if item.get("id")}
    filtered = list(range(len(candidates)))

    write_related_review_report(cfg, inventory, candidates, kept_ids)
    print(f"Loaded {len(candidates)} candidates from {candidate_path}", file=out)
    print(_HELP_TEXT, file=out)

    while True:
        try:
            raw = input_fn("review-related> ")
        except EOFError:
            raw = "quit"
        command = raw.strip()
        if not command:
            continue
        parts = command.split(maxsplit=2)
        verb = parts[0].lower()

        if verb == "help":
            print(_HELP_TEXT, file=out)
            continue

        if verb == "list":
            if not filtered:
                print("No candidates match the current filter.", file=out)
                continue
            for display_idx, candidate_idx in enumerate(filtered, start=1):
                candidate = candidates[candidate_idx]
                print(_format_candidate_line(display_idx, candidate, normalize_id(candidate.get("id", "")) in kept_ids), file=out)
            continue

        if verb == "filter":
            needle = command[len("filter"):].strip().lower()
            filtered = [idx for idx, item in enumerate(candidates) if needle in _candidate_context(item)]
            print(f"Filter matched {len(filtered)} candidate(s).", file=out)
            continue

        if verb == "clear":
            filtered = list(range(len(candidates)))
            print(f"Filter cleared. {len(filtered)} candidate(s) available.", file=out)
            continue

        if verb in {"open", "keep", "drop", "props"}:
            if len(parts) < 2 or not parts[1].isdigit():
                print("A numeric candidate index is required.", file=out)
                continue
            display_idx = int(parts[1])
            if display_idx < 1 or display_idx > len(filtered):
                print("Candidate index is out of range for the current filter.", file=out)
                continue
            candidate = candidates[filtered[display_idx - 1]]
            candidate_id = normalize_id(candidate.get("id", ""))

            if verb == "open":
                print(json.dumps({
                    "name": candidate.get("name"),
                    "type": candidate.get("type"),
                    "resourceGroup": candidate.get("resourceGroup"),
                    "subscriptionId": candidate.get("subscriptionId"),
                    "id": candidate.get("id"),
                    _DEEP_REASON_FIELD: candidate.get(_DEEP_REASON_FIELD, []),
                }, indent=2, sort_keys=True), file=out)
                continue

            if verb == "keep":
                kept_ids.add(candidate_id)
                print(f"Kept {candidate.get('name', '<unnamed>')}", file=out)
                continue

            if verb == "drop":
                kept_ids.discard(candidate_id)
                print(f"Dropped {candidate.get('name', '<unnamed>')}", file=out)
                continue

            path_arg = parts[2].strip() if len(parts) > 2 else ""
            try:
                value = _resolve_path(candidate, path_arg)
            except (KeyError, IndexError, ValueError) as exc:
                print(f"Path not found: {exc}", file=out)
                continue
            print(json.dumps(value, indent=2, sort_keys=True), file=out)
            continue

        if verb == "keep-all":
            for idx in filtered:
                kept_ids.add(normalize_id(candidates[idx].get("id", "")))
            print(f"Kept {len(filtered)} filtered candidate(s).", file=out)
            continue

        if verb == "drop-all":
            for idx in filtered:
                kept_ids.discard(normalize_id(candidates[idx].get("id", "")))
            print(f"Dropped {len(filtered)} filtered candidate(s).", file=out)
            continue

        if verb == "save":
            promoted_items = [item for item in candidates if normalize_id(item.get("id", "")) in kept_ids]
            promoted_path.write_text(json.dumps(promoted_items, indent=2, sort_keys=True))
            report_path = write_related_review_report(cfg, inventory, candidates, kept_ids)
            print(f"Saved {len(promoted_items)} promoted candidate(s) to {promoted_path}", file=out)
            print(f"Updated review report at {report_path}", file=out)
            continue

        if verb == "quit":
            print("Leaving review-related without further changes.", file=out)
            return

        print("Unknown command. Type 'help' for the command list.", file=out)
