import json
from pathlib import Path
from typing import Dict, Optional

REG_PATH = Path.home() / ".agent_adk_fabric" / "registry.json"
REG_PATH.parent.mkdir(parents=True, exist_ok=True)

def _read() -> Dict[str, dict]:
    """Reads the agent registry from the JSON file."""
    if not REG_PATH.exists():
        return {}
    with REG_PATH.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def _write(d: Dict[str, dict]):
    """Writes the agent registry to the JSON file."""
    with REG_PATH.open("w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)

def register_agent(spec: dict):
    """Adds or updates an agent in the registry."""
    d = _read()
    d[spec["id"]] = spec
    _write(d)

def unregister_agent(agent_id: str):
    """Removes an agent from the registry."""
    d = _read()
    if agent_id in d:
        del d[agent_id]
        _write(d)

def list_agents() -> Dict[str, dict]:
    """Returns all agents in the registry."""
    return _read()

def get_agent(agent_id: str) -> Optional[dict]:
    """Retrieves a single agent from the registry by its ID."""
    return _read().get(agent_id)
