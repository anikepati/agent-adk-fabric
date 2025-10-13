import argparse
import logging
from agent_adk_fabric.registry import get_agent
from agent_adk_fabric.agent_spec import AgentSpec
from agent_adk_fabric.tools import get_tool_list

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_with_adk(spec: AgentSpec):
    """Initializes and runs an interactive session with the Google ADK."""
    try:
        from google.adk.agents import LlmAgent
        from google.adk.sessions import InMemorySessionService
        from google.adk.runners import Runner
        from google.genai import types
    except ImportError as e:
        logger.error(f"ADK import failed. Cannot run agent. Error: {e}")
        return

    # Build tools using the centralized factory
    tool_list = get_tool_list(spec.adk.get("tools", []))

    # Create agent
    agent = LlmAgent(
        name=spec.name,
        model=spec.adk["model"],
        tools=tool_list,
        description=spec.description
    )
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=spec.id, session_service=session_service)

    user_id = "terminal_user"
    session = session_service.create_session(app_name=spec.id, user_id=user_id)

    print(f"✅ Session started for agent '{spec.name}'. Type 'exit' or 'quit' to end.")
    try:
        while True:
            user_input = input("You> ")
            if user_input.strip().lower() in ("exit", "quit"):
                break
            content = types.Content(role="user", parts=[types.Part(text=user_input)])
            # The runner streams events; we only print the final one for simplicity.
            for ev in runner.run(user_id=session.user_id, session_id=session.id, new_message=content):
                if ev.is_final_response():
                    print("Agent:", ev.content.parts[0].text)
    finally:
        session_service.delete_session(app_name=spec.id, user_id=session.user_id, session_id=session.id)
        logger.info("Session ended and cleaned up.")

def run_fallback(spec: AgentSpec):
    """A simple fallback REPL if ADK is not available."""
    print(f"⚠️ ADK not available. Running agent '{spec.name}' in fallback mode.")
    while True:
        query = input("ask> ")
        if query.strip().lower() in ("exit", "quit"):
            break
        print(f"[fallback] You asked about: {query}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-id", required=True, help="The ID of the agent to run.")
    args = parser.parse_args()

    spec_json = get_agent(args.agent_id)
    if not spec_json:
        logger.error(f"Agent '{args.agent_id}' is not registered or deployed. Aborting.")
        return

    spec = AgentSpec.from_dict(spec_json)

    try:
        # Check if ADK is available to decide the execution path
        import google.adk
        run_with_adk(spec)
    except ImportError:
        run_fallback(spec)

if __name__ == "__main__":
    main()
