import logging
import requests
from typing import Callable, List

logger = logging.getLogger(__name__)

def get_weather(city: str) -> str:
    """
    Gets the current weather for a given city using the Open-Meteo API.

    Args:
        city: The name of the city.

    Returns:
        A string describing the weather or an error message.
    """
    try:
        # 1. Get coordinates for the city
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": city, "count": 1, "language": "en", "format": "json"}
        response = requests.get(geo_url, params=params)
        response.raise_for_status()
        geo_data = response.json()

        if not geo_data.get("results"):
            return f"Could not find coordinates for city: {city}"

        location = geo_data["results"][0]
        lat, lon = location["latitude"], location["longitude"]

        # 2. Get weather for the coordinates
        weather_url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": True,
        }
        response = requests.get(weather_url, params=params)
        response.raise_for_status()
        weather_data = response.json()["current_weather"]

        temp = weather_data["temperature"]
        wind = weather_data["windspeed"]

        return f"Weather in {city}: Temperature is {temp}°C, Wind Speed is {wind} km/h."

    except requests.exceptions.RequestException as e:
        logger.error(f"API call failed for weather tool: {e}")
        return f"Error: Could not retrieve weather data for {city}."
    except (KeyError, IndexError) as e:
        logger.error(f"API response parsing failed for weather tool: {e}")
        return f"Error: Could not parse weather data for {city}."


# --- Tool Factory ---

TOOL_REGISTRY: dict[str, Callable] = {
    "weather": get_weather,
}

def get_tool_list(tool_names: List[str]) -> List[Callable]:
    """
    Constructs a list of tool functions based on their names.
    Handles special ADK-provided tools and custom tools from the registry.
    """
    tool_objects = []
    for name in tool_names:
        if name == "google_search":
            try:
                # ADK provides this tool directly
                from google.adk.tools import google_search
                tool_objects.append(google_search)
            except ImportError:
                logger.warning("Could not import 'google_search' from ADK. Skipping.")
        elif name in TOOL_REGISTRY:
            tool_objects.append(TOOL_REGISTRY[name])
        else:
            logger.warning(f"Unknown tool '{name}' requested. Skipping.")
    return tool_objects
