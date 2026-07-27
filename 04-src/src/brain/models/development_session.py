from dataclasses import dataclass, field
from typing import Any


@dataclass
class DevelopmentSession:
    id: str
    project_id: str
    status: str = "created"
    agents: list[Any] = field(default_factory=list)
