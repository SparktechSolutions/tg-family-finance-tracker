"""Application configuration, loaded from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # WhatsApp Cloud API
    whatsapp_verify_token: str = "change-me"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"

    # Telegram bot (free alternative to WhatsApp; from @BotFather)
    telegram_bot_token: str = ""
    # Family-only allowlist: comma-separated Telegram chat IDs the bot responds in.
    # Empty = open (anyone who finds the bot can use it). Set this to lock it down.
    telegram_allowed_chat_ids: str = ""

    # App
    database_url: str = "sqlite:///./expenses.db"
    default_currency: str = "INR"
    log_level: str = "INFO"


settings = Settings()
