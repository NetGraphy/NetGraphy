"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """NetGraphy API configuration.

    All settings can be overridden via environment variables with the
    NETGRAPHY_ prefix (e.g., NETGRAPHY_NEO4J_URI).
    """

    model_config = {"env_prefix": "NETGRAPHY_"}

    # --- Application ---
    app_name: str = "NetGraphy"
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "netgraphy"
    neo4j_database: str = "neo4j"
    neo4j_max_connection_pool_size: int = 50

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- NATS ---
    nats_url: str = "nats://localhost:4222"

    # --- MinIO / Object Storage ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "netgraphy"
    minio_secret_key: str = "netgraphy"
    minio_secure: bool = False
    minio_bucket: str = "netgraphy"

    # --- Plugins ---
    plugin_schema_dirs: list[str] = []  # Additional schema dirs from plugins (auto-discovered from Git repos)

    # --- Auth ---
    secret_key: str = "CHANGE-ME-IN-PRODUCTION"
    access_token_expire_minutes: int = 1440  # 24 hours
    algorithm: str = "HS256"

    # --- Workers ---
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"


settings = Settings()
