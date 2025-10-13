import yaml
from pathlib import Path
from typing import Dict

def load_ad_map(path: str) -> Dict:
    """Loads the AD group-to-agent mapping YAML file."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_agent_spec(path: str) -> Dict:
    """Loads an agent's specification YAML file."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
