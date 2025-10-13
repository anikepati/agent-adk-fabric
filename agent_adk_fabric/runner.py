import logging
import subprocess
from agent_adk_fabric.registry import get_agent
from agent_adk_fabric.ad_auth import get_current_user_groups, is_user_in_group
from agent_adk_fabric.agent_spec import AgentSpec

logger = logging.getLogger(__name__)

class AgentRunner:
    """Handles the logic of checking permissions and running an agent."""

    def can_run(self, allowed_groups: list) -> bool:
        """Checks if the current user is in any of the allowed groups."""
        user_groups = get_current_user_groups()
        for grp in allowed_groups:
            if is_user_in_group(grp, user_groups):
                return True
        return False

    def run_local(self, agent_id: str, allowed_groups: list):
        """Runs a locally-defined agent as a subprocess."""
        if not self.can_run(allowed_groups):
            logger.error(f"User not in allowed groups: {allowed_groups}")
            return False

        spec_json = get_agent(agent_id)
        if not spec_json:
            logger.error(f"Agent not registered: {agent_id}")
            return False

        spec = AgentSpec.from_dict(spec_json)
        cmd = spec.entrypoint
        logger.info(f"Running entrypoint: {cmd}")
        p = subprocess.Popen(cmd, shell=True)
        p.wait()
        return p.returncode == 0
