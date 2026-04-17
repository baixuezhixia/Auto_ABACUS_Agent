"""Simple dependency ordering for phase-1 workflows."""

from __future__ import annotations

from typing import Dict, List, Set

from autodft.core.exceptions import PlanningError
from autodft.core.models import TaskNode, WorkflowSpec


class DependencyGraph:
    """Validate task dependencies and return tasks in execution order."""

    def __init__(self, workflow: WorkflowSpec) -> None:
        self.workflow = workflow
        self.tasks_by_id: Dict[str, TaskNode] = {task.task_id: task for task in workflow.tasks}
        if len(self.tasks_by_id) != len(workflow.tasks):
            raise PlanningError("Workflow contains duplicate task IDs.")
        self._validate_dependencies()

    def execution_order(self) -> List[TaskNode]:
        """Return tasks sorted by dependency order, preserving spec order where possible."""

        ordered: List[TaskNode] = []
        temporary: Set[str] = set()
        permanent: Set[str] = set()

        def visit(task: TaskNode) -> None:
            if task.task_id in permanent:
                return
            if task.task_id in temporary:
                raise PlanningError(f"Workflow dependency cycle includes task '{task.task_id}'.")
            temporary.add(task.task_id)
            for dependency_id in task.depends_on:
                visit(self.tasks_by_id[dependency_id])
            temporary.remove(task.task_id)
            permanent.add(task.task_id)
            ordered.append(task)

        for task in self.workflow.tasks:
            visit(task)
        return ordered

    def _validate_dependencies(self) -> None:
        for task in self.workflow.tasks:
            for dependency_id in task.depends_on:
                if dependency_id not in self.tasks_by_id:
                    raise PlanningError(f"Task '{task.task_id}' depends on unknown task '{dependency_id}'.")


__all__ = ["DependencyGraph"]

