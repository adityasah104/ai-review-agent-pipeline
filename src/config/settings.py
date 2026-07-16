from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Azure DevOps (OAuth / SP)
    AZURE_TENANT_ID: str = ""
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    
    # Azure DevOps (Legacy/General)
    AZURE_DEVOPS_ORG: str
    AZURE_DEVOPS_PROJECT: str
    AZURE_DEVOPS_REPO: str
    AZURE_DEVOPS_PAT: str = ""
    AZURE_DEVOPS_WEBHOOK_SECRET: str

    # AWS Bedrock
    AWS_REGION: str = "us-east-1"
    BEDROCK_MODEL_ID: str = "amazon.nova-pro-v1:0"
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None

    # Groq (used by Aider for auto-fix)
    GROQ_API_KEY: str = ""

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Paths
    DEMO_REPO_PATH: str
    CHROMA_DB_PATH: str = "./chroma_db"
    SQLITE_DB_PATH: str = "./review_agent.db"

    # Aider
    AIDER_MAX_CI_RETRIES: int = 4
    MIN_FIX_CONFIDENCE: float = 0.80

    # New Hybrid Integration
    PR_AGENT_REFINE_URL: str = ""
    INTERNAL_API_SECRET: str = "my-super-secret-token"
    EXTERNAL_FINDINGS_TIMEOUT_SECONDS: int = 3600



    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()