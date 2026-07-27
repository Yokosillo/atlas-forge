from dataclasses import dataclass


@dataclass
class Job:
    id: str
    session_id: str
    agent_id: str
    description: str
    status: str = "created"
    result: str = ""
    created_at: str = ""
    completed_at: str = ""
