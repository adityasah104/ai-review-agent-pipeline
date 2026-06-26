from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Azure DevOps
    AZURE_DEVOPS_ORG: str
    AZURE_DEVOPS_PROJECT: str
    AZURE_DEVOPS_REPO: str
    AZURE_DEVOPS_PAT: str
    AZURE_DEVOPS_WEBHOOK_SECRET: str

    # AWS Bedrock
    AWS_REGION: str = "us-east-1"
    BEDROCK_MODEL_ID: str = "amazon.nova-pro-v1:0"
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Paths
    DEMO_REPO_PATH: str
    CHROMA_DB_PATH: str = "./chroma_db"
    SQLITE_DB_PATH: str = "./review_agent.db"

    # Aider
    AIDER_MAX_CI_RETRIES: int = 2
    MIN_FIX_CONFIDENCE: float = 0.95



    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()