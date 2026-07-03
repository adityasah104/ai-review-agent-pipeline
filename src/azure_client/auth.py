import httpx
import base64
from typing import Dict
from src.config.settings import settings

# In-memory cache for the token
_cached_token = None
_token_expires_at = 0

async def get_azure_devops_token() -> str:
    """
    Returns an Azure DevOps OAuth Bearer token if Service Principal credentials are provided.
    Falls back to the legacy PAT if Client ID is missing.
    """
    if not settings.AZURE_CLIENT_ID:
        # Fall back to Legacy PAT for local dev
        return settings.AZURE_DEVOPS_PAT
        
    import time
    global _cached_token, _token_expires_at
    
    # Return cached token if valid (buffer of 60 seconds)
    if _cached_token and time.time() < (_token_expires_at - 60):
        return _cached_token
        
    url = f"https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}/oauth2/v2.0/token"
    
    # Azure DevOps Resource ID is 499b84ac-1321-427f-aa17-267ca6975798 for all tenants
    data = {
        "client_id": settings.AZURE_CLIENT_ID,
        "client_secret": settings.AZURE_CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "499b84ac-1321-427f-aa17-267ca6975798/.default"
    }
    
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, data=data)
        resp.raise_for_status()
        
        body = resp.json()
        _cached_token = body["access_token"]
        _token_expires_at = time.time() + body.get("expires_in", 3599)
        
        return _cached_token

async def get_auth_headers() -> Dict[str, str]:
    """
    Returns the appropriate Authorization header for Azure DevOps REST API.
    """
    if not settings.AZURE_CLIENT_ID:
        token = base64.b64encode(f":{settings.AZURE_DEVOPS_PAT}".encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }
        
    token = await get_azure_devops_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
