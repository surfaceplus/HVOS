"""
HVOS API Configuration
=====================
Configuration management for HVOS API layer.
Reads from environment variables with sensible defaults.

Environment Variables:
  HVOS_API_PORT           - Server port (default: 5000)
  HVOS_API_HOST           - Server host (default: 0.0.0.0)
  HVOS_API_KEY            - API key for authentication
  HVOS_DEBUG              - Debug mode (default: false)
  WEIXIN_BOT_TOKEN        - WeChat iLink Bot token
  WEIXIN_BOT_URL          - WeChat iLink Bot webhook URL
  WOOCOMMERCE_DB_HOST     - WooCommerce MySQL host
  WOOCOMMERCE_DB_PORT     - WooCommerce MySQL port
  WOOCOMMERCE_DB_USER     - WooCommerce MySQL user
  WOOCOMMERCE_DB_PASSWORD - WooCommerce MySQL password
  WOOCOMMERCE_DB_NAME     - WooCommerce MySQL database name
  HVOS_SESSION_DIR        - Session storage directory
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class HVOSConfig:
    """HVOS API Configuration"""
    
    # Server settings
    port: int = 5000
    host: str = "0.0.0.0"
    debug: bool = False
    
    # Auth
    api_key: Optional[str] = None
    
    # WeChat iLink Bot
    weixin_bot_token: Optional[str] = None
    weixin_bot_url: Optional[str] = None
    
    # WooCommerce MySQL
    wc_db_host: str = "localhost"
    wc_db_port: int = 3306
    wc_db_user: str = "root"
    wc_db_password: Optional[str] = None
    wc_db_name: str = "woocommerce"
    
    # Session
    session_dir: str = "C:/Users/Administrator/AppData/Local/hermes/hvos/memory"
    
    # Opportunity Engine
    opportunity_config: dict = None
    
    @classmethod
    def from_env(cls) -> "HVOSConfig":
        """Load configuration from environment variables"""
        return cls(
            port=int(os.getenv("HVOS_API_PORT", "5000")),
            host=os.getenv("HVOS_API_HOST", "0.0.0.0"),
            debug=os.getenv("HVOS_DEBUG", "false").lower() in ("true", "1", "yes"),
            api_key=os.getenv("HVOS_API_KEY"),
            weixin_bot_token=os.getenv("WEIXIN_BOT_TOKEN"),
            weixin_bot_url=os.getenv("WEIXIN_BOT_URL"),
            wc_db_host=os.getenv("WOOCOMMERCE_DB_HOST", "localhost"),
            wc_db_port=int(os.getenv("WOOCOMMERCE_DB_PORT", "3306")),
            wc_db_user=os.getenv("WOOCOMMERCE_DB_USER", "root"),
            wc_db_password=os.getenv("WOOCOMMERCE_DB_PASSWORD"),
            wc_db_name=os.getenv("WOOCOMMERCE_DB_NAME", "woocommerce"),
            session_dir=os.getenv("HVOS_SESSION_DIR", 
                "C:/Users/Administrator/AppData/Local/hermes/hvos/memory"),
            opportunity_config={},
        )


# Global config instance
_config: Optional[HVOSConfig] = None


def get_config() -> HVOSConfig:
    """Get or create global config instance"""
    global _config
    if _config is None:
        _config = HVOSConfig.from_env()
    return _config


def reload_config():
    """Reload configuration from environment"""
    global _config
    _config = HVOSConfig.from_env()
    return _config