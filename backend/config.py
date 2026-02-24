# shopify_bridge/config.py
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = Field(alias="DATABASE_URL")
    SUPABASE_URL: str | None = Field(default=None, alias="SUPABASE_URL")
    SUPABASE_KEY: str | None = Field(default=None, alias="SUPABASE_KEY")

    REDIS_PORT: int = Field(alias="REDIS_PORT")
    REDIS_PASS: str = Field(alias="REDIS_PASS")
    REDIS_HOST: str = Field(alias="REDIS_HOST")

    ENCRYPTION_KEY: str = Field(alias="ENCRYPT")
    JOINT_KEY: str = Field(alias="JOINT_KEY")

    @property
    def store(self) -> dict[str, str]:
        """sample property to bind multiple items"""
        return {"api_key": "NO_KEY"}

    # === Server Settings ===
    port: int = Field(alias="PORT")
    env: str = Field(alias="ENV")

    class Config:
        env_file = ("./creds/.env",)
        extra = "forbid"


settings = Settings()  # type: ignore


L1_JOB_LIMIT: int = 2
L2_JOB_LIMIT: int = 4
L3_JOB_LIMIT: int = 1

L1_HASH_PATH: str = "data-prep-msg"
L2_HASH_PATH: str = "indexing-workers-msg"
L3_HASH_PATH: str = "status-sync-worker-msg"

L1_STREAM_PREFIX: str = "stream:data-prep-agents"
L2_STREAM_PREFIX: str = "stream:indexing-workers"
L3_STREAM_PREFIX: str = "stream:status-sync-worker"

L1_GROUP: str = "L1-workers"
L2_GROUP: str = "L2-workers"
L3_GROUP: str = "L3-workers"
