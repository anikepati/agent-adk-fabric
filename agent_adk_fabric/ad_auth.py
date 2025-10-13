import logging
import os
import platform
from typing import List

logger = logging.getLogger(__name__)

def _get_groups_windows() -> List[str]:
    """Fetches user groups using pywin32 on Windows."""
    try:
        import win32api
        import win32security
    except ImportError:
        logger.error("pywin32 is not installed. Please run 'pip install pywin32'")
        return []

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    groups = win32security.GetTokenInformation(token, win32security.TokenGroups)

    result = []
    for sid, _ in groups:
        try:
            name, domain, _ = win32security.LookupAccountSid(None, sid)
            result.append(f"{domain}\\{name}" if domain else name)
        except Exception:
            # This can fail for some SIDs, which is normal.
            pass
    return result

def _get_groups_fallback() -> List[str]:
    """Fetches user groups from an environment variable on non-Windows systems."""
    groups_str = os.environ.get("AGENT_FABRIC_GROUPS")
    if not groups_str:
        logger.warning(
            "Running on a non-Windows OS and AGENT_FABRIC_GROUPS env var is not set. "
            "No group memberships will be found."
        )
        return []
    return [group.strip() for group in groups_str.split(',')]

def get_current_user_groups() -> List[str]:
    """
    Gets the current user's security groups.
    Uses Windows-specific APIs if available, otherwise falls back to an
    environment variable `AGENT_FABRIC_GROUPS`.
    """
    system = platform.system()
    if system == "Windows":
        return _get_groups_windows()
    else:
        return _get_groups_fallback()

def is_user_in_group(group_name: str, user_groups: List[str]) -> bool:
    """Checks if a user is in a specific group (case-insensitive)."""
    target_lower = group_name.lower()
    for group in user_groups:
        group_lower = group.lower()
        # Check for 'DOMAIN\group' or just 'group'
        if group_lower.endswith(f"\\{target_lower}") or group_lower == target_lower:
            return True
    return False
