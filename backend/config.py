import os
from typing import List
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load .env from project root if present
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)


class BotConfig(BaseModel):
    # Alpaca Credentials & Endpoints
    ALPACA_API_KEY: str = Field(default_factory=lambda: os.getenv("ALPACA_API_KEY", ""))
    ALPACA_SECRET_KEY: str = Field(default_factory=lambda: os.getenv("ALPACA_SECRET_KEY", ""))
    ALPACA_BASE_URL: str = Field(
        default_factory=lambda: os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    )
    ALPACA_DATA_URL: str = Field(
        default_factory=lambda: os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets/v2")
    )

    # Risk & Strategy Sizing
    RISK_PER_TRADE_PCT: float = Field(
        default_factory=lambda: float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))
    )
    MAX_POSITIONS: int = Field(
        default_factory=lambda: int(os.getenv("MAX_POSITIONS", "5"))
    )
    TRADING_SYMBOLS: List[str] = Field(
        default_factory=lambda: [
            s.strip().upper()
            for s in os.getenv("TRADING_SYMBOLS", "AAPL,MSFT,NVDA,SPY,QQQ").split(",")
            if s.strip()
        ]
    )

    # Strategy Parameters
    EMA_FAST_PERIOD: int = Field(default=9)
    EMA_SLOW_PERIOD: int = Field(default=21)
    RSI_PERIOD: int = Field(default=14)
    RSI_OVERSOLD: float = Field(default=40.0)
    RSI_OVERBOUGHT: float = Field(default=70.0)
    ATR_PERIOD: int = Field(default_factory=lambda: int(os.getenv("ATR_PERIOD", "14")))
    ATR_MULTIPLIER: float = Field(
        default_factory=lambda: float(os.getenv("ATR_MULTIPLIER", "2.0"))
    )
    TAKE_PROFIT_MULTIPLIER: float = Field(
        default_factory=lambda: float(os.getenv("TAKE_PROFIT_MULTIPLIER", "3.0"))
    )

    # Bot Execution
    POLL_INTERVAL_SECONDS: int = Field(
        default_factory=lambda: int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
    )
    MOCK_MODE: bool = Field(
        default_factory=lambda: (
            os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes")
            or not os.getenv("ALPACA_API_KEY")
            or not os.getenv("ALPACA_SECRET_KEY")
        )
    )

    # Database Path
    DB_PATH: str = os.path.join(PROJECT_ROOT, "trading_bot.db")


# Global active config instance
active_config = BotConfig()


def get_config() -> BotConfig:
    global active_config
    return active_config


def update_config(updates: dict) -> BotConfig:
    global active_config
    current_data = active_config.model_dump()
    for k, v in updates.items():
        if k in current_data:
            if k == "TRADING_SYMBOLS" and isinstance(v, str):
                v = [s.strip().upper() for s in v.split(",") if s.strip()]
            current_data[k] = v
    active_config = BotConfig(**current_data)
    return active_config
