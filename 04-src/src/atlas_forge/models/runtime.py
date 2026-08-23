from dataclasses import dataclass, field


@dataclass(frozen=True)
class Runtime:
    id: str
    name: str
    type: str
    command: str
    args: list[str] = field(default_factory=list)
    working_directory: str = ""
