"""The project registry: `project add`, `project list` (plain functions; the CLI registers them)."""

from omniscient.onboarding.projects import (
    OnboardingError,
    add_project,
    list_projects,
    write_registry_entry,
)

__all__ = [
    "OnboardingError",
    "add_project",
    "list_projects",
    "write_registry_entry",
]
