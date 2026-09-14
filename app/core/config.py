import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings:
    PORT: int = int(os.getenv("PORT", "25243"))
    BASE_URL: str = os.getenv("BASE_URL", "https://apis.elyriax.com")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://elyriax.com")
    GO_BASE_URL: str = os.getenv("GO_BASE_URL", "https://go.elyriax.com")
    TZ: str = os.getenv("TZ", "Asia/Ho_Chi_Minh")

    # Database
    DB_HOST: str = os.getenv("DB_HOST", "103.228.36.238")
    DB_PORT: int = int(os.getenv("DB_PORT", "3307"))
    DB_USER: str = os.getenv("DB_USER", "u171735_c7IHYfbPas")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "+f6L@PykEkvKBB3j@4RL+331")
    DB_NAME: str = os.getenv("DB_NAME", "s171735_sayraaxyz")
    DB_CONNECTION_LIMIT: int = int(os.getenv("DB_CONNECTION_LIMIT", "10"))

    # Security
    JWT_SECRET: str = os.getenv("JWT_SECRET", "ey.Sya8KqLm92XvRHa7NtP4ZwUdJfEc53ByAiVxQrMtL9nHsWp")
    GENSHIN_COOKIE_SECRET: str = os.getenv("GENSHIN_COOKIE_SECRET", "elyriax_8f3k9p2m7q1x5v0n4b6c8z2h9j0l3a5d7e1g4i6")

    # Discord
    DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
    DISCORD_CLIENT_ID: str = os.getenv("DISCORD_CLIENT_ID", "")
    DISCORD_CLIENT_SECRET: str = os.getenv("DISCORD_CLIENT_SECRET", "")
    GUILD_ID: str = os.getenv("GUILD_ID", "")
    USER_TOKEN: str = os.getenv("USER_TOKEN", "")

    # OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")

    # Payment
    SEPAY_WEBHOOK_TOKEN: str = os.getenv("SEPAY_WEBHOOK_TOKEN", "")
    BANK_ID: str = os.getenv("BANK_ID", "MB")
    BANK_ACCOUNT_NO: str = os.getenv("BANK_ACCOUNT_NO", "")
    BANK_ACCOUNT_NAME: str = os.getenv("BANK_ACCOUNT_NAME", "")

    # Admin
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", os.getenv("ADMIN_USER", "elyriax"))
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", os.getenv("ADMIN_PASS", "ElyriaxDeptrai"))
    ADMIN_USER: str = os.getenv("ADMIN_USER", os.getenv("ADMIN_USERNAME", "elyriax"))
    ADMIN_PASS: str = os.getenv("ADMIN_PASS", os.getenv("ADMIN_PASSWORD", "ElyriaxDeptrai"))
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")

    # Email
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "Elyriax <no-reply@elyriax.com>")

    # AI
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

settings = Settings()
