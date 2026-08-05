from dataclasses import dataclass


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    description: str
    path: str