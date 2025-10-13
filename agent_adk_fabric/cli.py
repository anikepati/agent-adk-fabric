import click
import logging
import os
import subprocess
import sys
from dotenv import load_dotenv

from agent_adk_fabric.config_loader import load_ad_map, load_agent_spec
from agent_adk_fabric.agent_spec import AgentSpec
from agent_adk_fabric.registry import register_agent, list_agents, get_agent, unregister_agent
from agent_adk_fabric.ad_auth import get_current_user_groups, is_user_in_group
from agent_adk_fabric.deployers.local_adk_deployer import LocalAdkDeployer
from agent_adk_fabric.deployers.engine_api_deployer import EngineApiDeployer

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("agentctl")

@click.group()
def main():
    """agentctl: A CLI for managing agents in the ADK fabric."""
    pass

@main.command()
@click.option("--config", default="config/ad_groups.yaml", help="Path to AD group mapping YAML.")
@click.option("--deploy-mode", default="local", type=click.Choice(["local", "engine"]), help="Deployment target.")
@click.option("--engine-url", envvar="ENGINE_API_URL", help="Engine URL (or set ENGINE_API_URL).")
@click.option("--engine-token", envvar="ENGINE_API_TOKEN", help="Engine token (or set ENGINE_API_TOKEN).")
def deploy_for_user(config, deploy_mode, engine_url, engine_token):
    """Deploys agents based on the current user's AD group membership."""
    ad_map = load_ad_map(config)
    user_groups = get_current_user_groups()
    logger.info(f"Current user groups found: {user_groups}")

    agents_to_deploy = set()
    for group_name, data in ad_map.get("groups", {}).items():
        if is_user_in_group(group_name, user_groups):
            logger.info(f"User is in group '{group_name}', adding agents.")
            for agent_yaml in data.get("agents", []):
                agents_to_deploy.add(agent_yaml)

    if not agents_to_deploy:
        logger.info("No agents are configured for this user's groups.")
        return

    if deploy_mode == "local":
        deployer = LocalAdkDeployer()
    else:
        if not engine_url or not engine_token:
            logger.error("Engine URL and token are required for 'engine' deploy mode.")
            return
        deployer = EngineApiDeployer(engine_url, engine_token)

    for yaml_path in agents_to_deploy:
        spec_dict = load_agent_spec(yaml_path)
        spec = AgentSpec.from_dict(spec_dict)
        if deployer.deploy(spec):
            register_agent(spec_dict)
            logger.info(f"Successfully deployed and registered agent: {spec.id}")
        else:
            logger.error(f"Failed to deploy agent: {spec.id}")

@main.command("list")
def list_deployed_agents():
    """Lists all locally registered agents."""
    agents = list_agents()
    if not agents:
        click.echo("No agents are currently registered.")
        return
    click.echo("Registered Agents:")
    for aid, spec in agents.items():
        click.echo(f"- {aid}: {spec.get('name')} ({spec.get('description')})")

@main.command()
@click.argument("agent_id")
def run(agent_id):
    """Runs a specified agent in the terminal."""
    spec = get_agent(agent_id)
    if not spec:
        click.echo(f"Agent '{agent_id}' not found.")
        sys.exit(1)

    entrypoint_str = spec.get("entrypoint")
    if not entrypoint_str:
        click.echo(f"No entrypoint defined for agent '{agent_id}'.")
        sys.exit(1)

    # Use the same Python interpreter that is running the CLI to run the agent script
    command = [sys.executable] + entrypoint_str.split()[1:]
    subprocess.run(command)

@main.command()
@click.argument("agent_id")
@click.option("--deploy-mode", default="local", type=click.Choice(["local", "engine"]))
@click.option("--engine-url", envvar="ENGINE_API_URL")
@click.option("--engine-token", envvar="ENGINE_API_TOKEN")
def destroy(agent_id, deploy_mode, engine_url, engine_token):
    """Destroys and unregisters a specified agent."""
    spec_dict = get_agent(agent_id)
    if not spec_dict:
        click.echo(f"Agent '{agent_id}' not found.")
        return
    spec = AgentSpec.from_dict(spec_dict)

    if deploy_mode == "local":
        deployer = LocalAdkDeployer()
    else:
        if not engine_url or not engine_token:
            logger.error("Engine URL and token are required for 'engine' deploy mode.")
            return
        deployer = EngineApiDeployer(engine_url, engine_token)

    if deployer.destroy(spec):
        unregister_agent(agent_id)
        click.echo(f"Successfully destroyed agent: {agent_id}")
    else:
        click.echo(f"Failed to destroy agent: {agent_id}")
