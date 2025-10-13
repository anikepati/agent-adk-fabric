import streamlit as st
import logging

from agent_adk_fabric.registry import list_agents
from agent_adk_fabric.agent_spec import AgentSpec
from agent_adk_fabric.tools import get_tool_list

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Attempt to import ADK components
try:
    from google.adk.agents import LlmAgent
    from google.adk.sessions import InMemorySessionService
    from google.adk.runners import Runner
    from google.genai import types
    ADK_AVAILABLE = True
except ImportError:
    ADK_AVAILABLE = False

st.set_page_config(page_title="Agent Fabric Chat", layout="wide")
st.title("🤖 Agent Fabric UI")

def clear_chat_session():
    """Clears session state related to the chat and agent runner."""
    keys_to_clear = ["messages", "runner", "session", "session_service"]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    logger.info("Chat session cleared.")

def initialize_agent_runner(spec: AgentSpec):
    """Initializes the ADK Runner and Session for a given agent spec."""
    if not ADK_AVAILABLE:
        st.error("Google ADK is not installed. Please install 'google-adk' to run agents.")
        return None, None, None

    tool_list = get_tool_list(spec.adk.get("tools", []))

    try:
        agent = LlmAgent(
            name=spec.name,
            model=spec.adk["model"],
            tools=tool_list,
            description=spec.description
        )
        session_service = InMemorySessionService()
        runner = Runner(agent=agent, app_name=spec.id, session_service=session_service)

        user_id = "streamlit_user"
        session = session_service.create_session(app_name=spec.id, user_id=user_id)

        logger.info(f"Initialized runner for agent '{spec.id}' with session '{session.id}'")
        return runner, session, session_service
    except Exception as e:
        st.error(f"Failed to initialize ADK agent: {e}")
        logger.exception("ADK Initialization failed.")
        return None, None, None

# --- Main Application Logic ---

# 1. Agent Selection
registered_agents = list_agents()

if not registered_agents:
    st.warning(
        "**No agents found!** 😔\n\n"
        "Please deploy an agent first using the command line:\n\n"
        "`agentctl deploy-for-user`"
    )
    st.stop()

agent_options = {spec["name"]: aid for aid, spec in registered_agents.items()}
selected_agent_name = st.sidebar.selectbox(
    "Choose an agent",
    options=agent_options.keys(),
    key="agent_selector"
)
selected_agent_id = agent_options[selected_agent_name]

# 2. Session Management
if "current_agent_id" not in st.session_state or st.session_state.current_agent_id != selected_agent_id:
    clear_chat_session()
    st.session_state.current_agent_id = selected_agent_id

# 3. Initialize Agent and Chat History
if "messages" not in st.session_state:
    st.session_state.messages = []

agent_spec_dict = registered_agents[selected_agent_id]
spec = AgentSpec.from_dict(agent_spec_dict)
st.sidebar.info(f"**ID**: `{spec.id}`\n\n**Model**: `{spec.adk.get('model')}`\n\n**Description**: {spec.description}")

if "runner" not in st.session_state:
    runner, session, session_service = initialize_agent_runner(spec)
    if runner:
        st.session_state.runner = runner
        st.session_state.session = session
        st.session_state.session_service = session_service
    else:
        st.stop()

# 4. Display Chat History
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 5. Handle User Input
if prompt := st.chat_input(f"What do you want to ask {selected_agent_name}?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()

        try:
            runner = st.session_state.runner
            session = st.session_state.session

            content = types.Content(role="user", parts=[types.Part(text=prompt)])

            final_text = "Sorry, I could not process your request."
            for ev in runner.run(user_id=session.user_id, session_id=session.id, new_message=content):
                if ev.is_final_response():
                    final_text = ev.content.parts[0].text

            full_response = final_text
            message_placeholder.markdown(full_response)

        except Exception as e:
            full_response = f"An error occurred: {e}"
            message_placeholder.error(full_response)
            logger.exception("Error during agent run.")

    st.session_state.messages.append({"role": "assistant", "content": full_response})

