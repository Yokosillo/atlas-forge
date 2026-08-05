from dataclasses import dataclass, field


@dataclass
class JobPlanStep:
    description: str
    mechanism: str  # "script" | "scribe" | "agent"
    agent_role: str | None = None  # solo relevante si mechanism == "agent"
    agent_id: str | None = None  # T-FB022-US06-01: desambiguación con
    # múltiples agentes del mismo rol activos.
    # "pending" | "running" | "completed" | "failed" | "cancelled"
    # (T-FB008-US04-03/T-FB008-US08-01, progreso consultable durante el
    # despacho — ver dispatcher/job_plan_dispatch.py).
    status: str = "pending"
    result: str = ""


@dataclass
class JobPlan:
    goal: str
    steps: list[JobPlanStep] = field(default_factory=list)
    status: str = "proposed"  # "proposed" | "approved" | "rejected" | "blocked" | "cancelled"
