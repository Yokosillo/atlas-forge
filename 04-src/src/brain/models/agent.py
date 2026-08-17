from dataclasses import dataclass


@dataclass
class Agent:
    id: str
    name: str
    role: str
    prompt: str
    runtime_id: str
    status: str = "idle"
    last_command_at: str = ""
    limited_until: str | None = None
