from dataclasses import dataclass
from typing import Dict, List

@dataclass
class AgentSpec:
    name: str
    id: str
    description: str
    entrypoint: str
    adk: Dict
    env: Dict

    @staticmethod
    def from_dict(d: dict) -> "AgentSpec":
        return AgentSpec(
            name=d["name"],
            id=d["id"],
            description=d.get("description", ""),
            entrypoint=d.get("entrypoint", ""),
            adk=d.get("adk", {}),
            env=d.get("env", {}),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "id": self.id,
            "description": self.description,
            "entrypoint": self.entrypoint,
            "adk": self.adk,
            "env": self.env,
        }
