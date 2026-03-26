"""Config Store — load/save agent configuration with encrypted token storage."""

import json
import os
import sys
import logging
from pathlib import Path
from models import AgentConfig

logger = logging.getLogger("aurora-bridge")

# Config file location: next to the executable
CONFIG_DIR = Path(os.environ.get("AURORA_BRIDGE_CONFIG_DIR", Path.home() / ".aurora-bridge"))
CONFIG_FILE = CONFIG_DIR / "config.json"
TOKEN_FILE = CONFIG_DIR / "token.enc"


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _encrypt_token(token: str) -> bytes:
    """Encrypt token using Windows DPAPI. Falls back to plaintext on non-Windows."""
    if sys.platform == "win32":
        try:
            import win32crypt
            return win32crypt.CryptProtectData(
                token.encode("utf-8"), "AuroraBridge", None, None, None, 0
            )
        except ImportError:
            logger.warning("pywin32 not installed — storing token in plaintext")
    # Non-Windows or pywin32 missing: base64 encode (not truly encrypted)
    import base64
    return base64.b64encode(token.encode("utf-8"))


def _decrypt_token(data: bytes) -> str:
    """Decrypt token. Reverses _encrypt_token."""
    if sys.platform == "win32":
        try:
            import win32crypt
            _, decrypted = win32crypt.CryptUnprotectData(data, None, None, None, 0)
            return decrypted.decode("utf-8")
        except ImportError:
            pass
    import base64
    return base64.b64decode(data).decode("utf-8")


def load_config() -> AgentConfig:
    """Load configuration from disk."""
    _ensure_dir()
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            config = AgentConfig(**data)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            config = AgentConfig()
    else:
        config = AgentConfig()

    # Load encrypted token
    if TOKEN_FILE.exists() and not config.token:
        try:
            config.token = _decrypt_token(TOKEN_FILE.read_bytes())
        except Exception as e:
            logger.error(f"Failed to decrypt token: {e}")

    return config


def save_config(config: AgentConfig):
    """Save configuration to disk. Token is stored encrypted separately."""
    _ensure_dir()

    # Extract token for separate encrypted storage
    token = config.token
    config_dict = config.model_dump(exclude={"token"})

    CONFIG_FILE.write_text(json.dumps(config_dict, indent=2))

    if token:
        TOKEN_FILE.write_bytes(_encrypt_token(token))

    logger.info(f"Config saved to {CONFIG_DIR}")


def save_token(token: str):
    """Save just the token (used after OAuth flow)."""
    _ensure_dir()
    TOKEN_FILE.write_bytes(_encrypt_token(token))
    logger.info("Token saved")


def clear_token():
    """Remove stored token."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    logger.info("Token cleared")


def detect_mt5_path() -> str | None:
    """Auto-detect MT5 Common/Files directory on Windows."""
    if sys.platform != "win32":
        return None

    # MT5 stores files in AppData/Roaming/MetaQuotes/Terminal/Common/Files
    common_path = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    if common_path.exists():
        return str(common_path)

    # Also check individual terminal folders
    terminals_dir = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    if terminals_dir.exists():
        for d in terminals_dir.iterdir():
            if d.is_dir() and (d / "MQL5" / "Files").exists():
                return str(d / "MQL5" / "Files")

    return None
