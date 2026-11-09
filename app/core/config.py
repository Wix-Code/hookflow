from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet
from pydantic import field_validator


class Settings(BaseSettings):
        # hide_input_in_errors: a mistyped secret must not be printed back in the error message.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_name: str = "HookFlow"
    database_url: str = "sqlite:///./hookflow.sqlite"
    jwt_secret_key: str = "dev-only-insecure-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    
    # Encrypts webhook signing secrets in the database. Put your OWN key in .env.
    encryption_key: str = "-beQb7mSqGkduqc01YIoCXfbAUkrROwbK5j_5YFo5Pw="

    # LOCAL DEVELOPMENT ONLY. Lets webhook URLs use http://, localhost and IP addresses so you can test against a
    # mock receiver on your own computer. Never turn this on in a deployed environment.
    allow_unsafe_webhook_urls: bool = False
    
    # The delivery worker (python -m app.worker).
    worker_poll_interval_seconds: float = 2.0  # how long to sleep when nothing is due
    worker_concurrency: int = 4  # deliveries sent at the same time by one worker process
    delivery_timeout_seconds: float = 10.0  # each network step (connect, send, wait for the reply)
    delivery_lease_seconds: int = 60  # how long a worker may hold a delivery before others may take it over

    @field_validator("encryption_key")
    @classmethod
    def must_be_a_fernet_key(cls, value: str) -> str:
        # Fail when the app starts, with a clear message, instead of with a 500 the first time a secret is saved.
        try:
            Fernet(value.encode("utf-8"))
        except Exception:
            raise ValueError(
                "ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()