"""Minimal artifact store for workflow task handoff."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from autodft.core.enums import ArtifactType
from autodft.core.models import ArtifactRef, ResolvedStructure, TaskExecutionRecord


@dataclass
class ArtifactStore:
    """Track structure, generated input, and execution artifacts by task."""

    artifacts: List[ArtifactRef] = field(default_factory=list)
    task_dirs: Dict[str, Path] = field(default_factory=dict)
    structure_paths: Dict[str, Path] = field(default_factory=dict)
    execution_records: Dict[str, TaskExecutionRecord] = field(default_factory=dict)
    structure: Optional[ResolvedStructure] = None

    def add(self, artifact: ArtifactRef) -> None:
        """Add one artifact reference."""

        self.artifacts.append(artifact)

    def add_many(self, artifacts: Iterable[ArtifactRef]) -> None:
        """Add several artifact references."""

        for artifact in artifacts:
            self.add(artifact)

    def add_execution(self, record: TaskExecutionRecord) -> None:
        """Add all artifacts from an execution record."""

        self.execution_records[record.task_id] = record
        self.add_many(record.artifacts)

    def set_structure(self, structure: ResolvedStructure) -> None:
        """Record the resolved structure and its artifacts."""

        self.structure = structure
        self.add_many(structure.artifacts)

    def register_task_dir(self, task_id: str, task_dir: Path) -> None:
        """Record the working directory for a task."""

        self.task_dirs[task_id] = task_dir

    def register_task_structure(self, task_id: str, structure_path: Path) -> None:
        """Record the STRU path used by a task."""

        self.structure_paths[task_id] = structure_path

    def by_task(self, task_id: str) -> List[ArtifactRef]:
        """Return artifacts owned by a task."""

        return [artifact for artifact in self.artifacts if artifact.task_id == task_id]

    def first(
        self,
        artifact_type: ArtifactType,
        *,
        task_id: Optional[str] = None,
        label: str = "",
    ) -> Optional[ArtifactRef]:
        """Return the first artifact matching type and optional filters."""

        for artifact in self.artifacts:
            if artifact.artifact_type != artifact_type:
                continue
            if task_id is not None and artifact.task_id != task_id:
                continue
            if label and artifact.label != label:
                continue
            return artifact
        return None


__all__ = ["ArtifactStore"]
