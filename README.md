# Agent ADK Fabric

This project provides a complete framework for dynamically deploying, running, and managing LLM agents using the Google Agent Development Kit (ADK). Agent availability is controlled by Active Directory (AD) group membership, and the project includes both a command-line interface (`agentctl`) and a web-based chat UI built with Streamlit.



## ✨ Features

-   **Active Directory Integration**: Agent access is determined by the user's AD group membership.
-   **Dynamic Deployment**: Deploy and destroy agents on-the-fly.
-   **Dual Interface**: Manage agents via a powerful CLI (`agentctl`) or interact with them through an intuitive Streamlit web UI.
-   **Full Agent Lifecycle**: Supports deploying, listing, running, and destroying agents.
-   **ADK Session Management**: Uses ADK's `Runner` and `SessionService` for stateful, conversational interactions.
-   **Tool Support**: Comes with built-in support for `Google Search` and a functional `weather` tool that calls a live API.
-   **Cross-Platform**: Works on Windows (with native AD lookup) and on Linux/macOS (using an environment variable for simulation).

---

## ⚙️ Setup and Installation

### Prerequisites

-   Python 3.9+
-   An environment where you can install Python packages.
-   (Optional) For native AD integration, a domain-joined Windows machine.

### Installation Steps

1.  **Clone the Repository**
    ```bash
    # git clone <your-repo-url>
    # cd agent_adk_fabric
    ```

2.  **(Recommended) Create a Virtual Environment**
    ```bash
    python -m venv .venv
    # On Windows
    .venv\Scripts\activate
    # On macOS/Linux
    source .venv/bin/activate
    ```

3.  **Install Dependencies**
    Install the project in editable mode, which includes all dependencies from `pyproject.toml`.
    ```bash
    pip install -e .
    ```

4.  **Configure Environment**
    If you are **not** on a domain-joined Windows machine, you must simulate AD group membership. Copy the example environment file:
    ```bash
    cp .env.example .env
    ```
    Then, edit the `.env` file to include the groups you want to be a part of:
    ```
    # For non-Windows users to simulate AD group membership
    AGENT_FABRIC_GROUPS="DevGroup,AdminGroup"
    ```

---

## 🚀 Usage

### 1. Using the Command-Line (`agentctl`)

The `agentctl` tool is your primary interface for managing the agent lifecycle.

#### Deploy Agents
Deploy agents based on your (real or simulated) AD group membership defined in `config/ad_groups.yaml`.
```bash
agentctl deploy-for-user
````

#### List Deployed Agents

See which agents have been deployed and are available to run.

```bash
agentctl list
```

#### Run an Agent (in terminal)

Execute an agent directly in your terminal for a quick, text-based chat session.

```bash
agentctl run dev-llm-agent
```

#### Destroy an Agent

Remove an agent's deployment and unregister it from the fabric.

```bash
agentctl destroy dev-llm-agent
```

### 2\. Using the Streamlit Web UI

The Streamlit app provides a user-friendly chat interface for interacting with your deployed agents.

#### How to Run

1.  **Ensure agents are deployed**: Run `agentctl deploy-for-user` at least once.
2.  **Launch the app**:
    ```bash
    streamlit run app.py
    ```

Your web browser will open a new tab with the interface. You can select an available agent from the sidebar and start your conversation. The chat session automatically resets when you switch agents.
