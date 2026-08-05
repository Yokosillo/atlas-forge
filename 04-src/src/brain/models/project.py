from dataclasses import dataclass


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: str
    repository: str
    workspace_id: str
