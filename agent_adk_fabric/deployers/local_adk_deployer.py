import logging
import json
from pathlib import Path
from agent_adk_fabric.deployer import AgentDeployer
from agent_adk_fabric.agent_spec import AgentSpec
from agent_adk_fabric.tools import get_tool_list

logger = logging.getLogger(__name__)
DEPLOY_REG_DIR = Path.home() / ".agent_adk_fabric" / "deployed"
DEPLOY_REG_DIR.mkdir(parents=True, exist_ok=True)

try:
    from google.adk.agents import LlmAgent
    ADK_AVAILABLE = True
except ImportError:
    logger.warning("Google ADK not found. Some functionality will be disabled.")
    ADK_AVAILABLE = False

def _register_local(spec: AgentSpec):
    """Saves the agent spec to a local JSON file to mark it as 'deployed'."""
    path = DEPLOY_REG_DIR / f"{spec.id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(spec.to_dict(), f, indent=2)

def _unregister_local(spec: AgentSpec) -> bool:
    """Removes the local agent spec file."""
    path = DEPLOY_REG_DIR / f"{spec.id}.json"
    if path.exists():
        path.unlink()
        return True
    return False

class LocalAdkDeployer(AgentDeployer):
    """A deployer that validates and registers agents locally."""

    def deploy(self, spec: AgentSpec) -> bool:
        logger.info(f"Deploying local ADK agent: {spec.id}")
        if not ADK_AVAILABLE:
            logger.info("ADK not available. Registering as a stub deployment.")
            _register_local(spec)
            return True

        try:
            # Use the centralized tool factory
            tool_objs = get_tool_list(spec.adk.get("tools", []))

            # Create the agent instance to validate the spec against the ADK
            LlmAgent(
                name=spec.name,
                model=spec.adk["model"],
                tools=tool_objs,
                description=spec.description
            )
            # This step conceptually validates the ADK spec.

            _register_local(spec)
            logger.info(f"Agent '{spec.id}' deployed and registered locally.")
            return True
        except Exception as e:
            logger.exception(f"Failed to deploy agent '{spec.id}' via ADK: {e}")
            return False

    def destroy(self, spec: AgentSpec) -> bool:
        logger.info(f"Destroying agent: {spec.id}")
        # For local deployments, destroying just means unregistering.
        return _unregister_local(spec)
