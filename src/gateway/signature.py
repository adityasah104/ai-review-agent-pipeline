import hmac
from fastapi import HTTPException, Request
from src.config.settings import settings


async def validate_azure_webhook(request: Request) -> bytes:
    """
    Azure DevOps Service Hooks send a shared secret in the Authorization header
    as a Basic auth token. We validate it here.
    
    Azure DevOps format: Authorization: Basic base64(username:password)
    We use the webhook secret as the password.
    """
    import base64

    auth_header = request.headers.get("Authorization", "")
    body = await request.body()

    if not auth_header:
        # During local testing with ngrok, allow bypass if header missing
        # Remove this in production
        return body

    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            _, password = decoded.split(":", 1)
            if not hmac.compare_digest(password, settings.AZURE_DEVOPS_WEBHOOK_SECRET):
                raise HTTPException(status_code=403, detail="Invalid webhook secret")
        except Exception:
            raise HTTPException(status_code=403, detail="Invalid Authorization header")

    return body