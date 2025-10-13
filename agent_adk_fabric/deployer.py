from abc import ABC, abstractmethod
from agent_adk_fabric.agent_spec import AgentSpec

class AgentDeployer(ABC):
    """Abstract base class for an agent deployment strategy."""

    @abstractmethod
    def deploy(self, spec: AgentSpec) -> bool:
        """Deploy or register the given agent spec."""
        raise NotImplementedError()

    @abstractmethod
    def destroy(self, spec: AgentSpec) -> bool:
        """Destroy or unregister the agent."""
        raise NotImplementedError()
