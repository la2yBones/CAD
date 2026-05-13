import os
import re
import yaml
from pathlib import Path
from typing import Dict, Any, Optional

_ENV_VAR_RE = re.compile(r'\$\{(\w+)\}')


def _load_dotenv(env_path: Optional[Path] = None) -> Dict[str, str]:
    """Load key=value pairs from a .env file."""
    if env_path is None:
        env_path = Path(__file__).parent.parent.parent / ".env"
    if not env_path.exists():
        return {}
    result: Dict[str, str] = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                result[key] = value
    return result


def _resolve_env_vars(value: Any, dotenv_vars: Dict[str, str]) -> Any:
    """Recursively resolve ${VAR} placeholders in config values."""
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:
            var_name = m.group(1)
            return os.environ.get(var_name) or dotenv_vars.get(var_name, m.group(0))
        return _ENV_VAR_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v, dotenv_vars) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v, dotenv_vars) for v in value]
    return value


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration with .env file and environment variable resolution.

    Resolution order (highest priority first):
      1. OS environment variables
      2. .env file in project root
      3. Config file literal values (fallback)

    Args:
        config_path: Path to config YAML file. Defaults to config/config.yaml.

    Returns:
        Resolved configuration dictionary.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"

    config_path = Path(config_path)

    if not config_path.exists():
        example_path = config_path.parent / "config.example.yaml"
        if example_path.exists():
            config_path = example_path
        else:
            return {}

    dotenv_vars = _load_dotenv()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Failed to load config: {e}")
        return {}

    return _resolve_env_vars(raw_config, dotenv_vars)
