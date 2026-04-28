"""Import local discovery artifacts into a UI-managed run directory."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


ARTIFACT_TARGET_NAMES = {
    "seed": "seed.json",
    "inventory": "inventory.json",
}


@dataclass(frozen=True)
class ImportedArtifact:
    artifact_type: str
    source_path: str
    target_name: str
    size_bytes: int
    sha256: str


def default_import_output_dir(run_id: str) -> Path:
    return Path.cwd() / ".azdisc_ui_runs" / run_id


def _validate_source_file(path_str: str) -> Path:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Source file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Source path is not a file: {path}")
    return path


def _copy_file_with_digest(source: Path, target: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as src, target.open("wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _ensure_json_like(path: Path) -> None:
    with path.open("r", encoding="utf-8") as handle:
        while True:
            char = handle.read(1)
            if not char:
                raise ValueError(f"Artifact is empty: {path}")
            if char.isspace():
                continue
            if char not in "[{":
                raise ValueError(f"Artifact is not JSON-like: {path}")
            return


def import_artifacts(
    *,
    output_dir: str | Path,
    sources: Iterable[dict],
) -> List[ImportedArtifact]:
    """Copy supported artifacts into an output directory and emit a manifest."""
    target_root = Path(output_dir).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    imported: List[ImportedArtifact] = []
    seen_types: set[str] = set()
    for source in sources:
        artifact_type = str(source.get("artifactType", "")).strip().lower()
        source_path = str(source.get("path", "")).strip()
        if artifact_type not in ARTIFACT_TARGET_NAMES:
            raise ValueError(
                f"Unsupported artifactType {artifact_type!r}. Valid: {sorted(ARTIFACT_TARGET_NAMES)}"
            )
        if artifact_type in seen_types:
            raise ValueError(f"Duplicate artifactType provided: {artifact_type}")
        if not source_path:
            raise ValueError(f"Missing source path for artifactType {artifact_type}")

        source_file = _validate_source_file(source_path)
        _ensure_json_like(source_file)
        target_name = ARTIFACT_TARGET_NAMES[artifact_type]
        target_file = target_root / target_name
        size_bytes, sha256 = _copy_file_with_digest(source_file, target_file)
        imported.append(
            ImportedArtifact(
                artifact_type=artifact_type,
                source_path=str(source_file),
                target_name=target_name,
                size_bytes=size_bytes,
                sha256=sha256,
            )
        )
        seen_types.add(artifact_type)

    manifest = {
        "artifacts": [
            {
                "artifactType": item.artifact_type,
                "sourcePath": item.source_path,
                "targetName": item.target_name,
                "sizeBytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in imported
        ]
    }
    (target_root / "import-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return imported