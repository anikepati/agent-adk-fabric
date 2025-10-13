import logging
import requests
from agent_adk_fabric.deployer import AgentDeployer
from agent_adk_fabric.agent_spec import AgentSpec

logger = logging.getLogger(__name__)

class EngineApiDeployer(AgentDeployer):
    """A deployer that interacts with a remote agent engine API."""

    def __init__(self, engine_url: str, api_token: str):
        self.engine_url = engine_url.rstrip("/")
        self.api_token = api_token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

    def deploy(self, spec: AgentSpec) -> bool:
        logger.info(f"Deploying agent '{spec.id}' to remote engine at {self.engine_url}")
        payload = spec.to_dict()
        url = f"{self.engine_url}/api/v1/agents"
        try:
            resp = requests.post(url, json=payload, headers=self._headers())
            if resp.status_code in (200, 201):
                return True
            logger.error(f"Engine deploy failed: {resp.status_code} {resp.text}")
            return False
        except requests.RequestException as e:
            logger.error(f"Request to engine failed: {e}")
            return False

    def destroy(self, spec: AgentSpec) -> bool:
        logger.info(f"Destroying agent '{spec.id}' on remote engine.")
        url = f"{self.engine_url}/api/v1/agents/{spec.id}"
        try:
            resp = requests.delete(url, headers=self._headers())
            return resp.status_code in (200, 204)
        except requests.RequestException as e:
            logger.error(f"Request to engine failed: {e}")
            return False
