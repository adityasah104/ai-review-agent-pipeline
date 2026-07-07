import os
from typing import Dict

async def get_azure_devops_token() -> str:
    """
    Returns the Azure DevOps pipeline access token.
    """
    token = os.environ.get("SYSTEM_ACCESSTOKEN", "")
    if not token:
        # Fallback to PAT if running locally
        from src.config.settings import settings
        token = settings.AZURE_DEVOPS_PAT
    return token

async def get_auth_headers() -> Dict[str, str]:
    """
    Returns the appropriate Authorization header for Azure DevOps REST API.
    """
    token = await get_azure_devops_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

