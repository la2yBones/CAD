import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


def _find_project_root() -> Path:
    """
    自动发现项目根目录。
    优先级：环境变量 CAD_PROJECT_ROOT → 向上查找包含 config/ 目录的父级 → 相对于本文件的回退路径。
    """
    env_root = os.environ.get("CAD_PROJECT_ROOT")
    if env_root:
        p = Path(env_root)
        if p.exists():
            return p

    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "config").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    return Path(__file__).parent.parent.parent


def _resolve_config_path(config_path: Optional[str] = None) -> Optional[Path]:
    """
    解析配置文件路径。
    优先级：显式参数 → 环境变量 CAD_CONFIG_PATH → 项目根目录下的 config/config.yaml。
    """
    if config_path is not None:
        return Path(config_path)

    env_path = os.environ.get("CAD_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    project_root = _find_project_root()
    default_path = project_root / "config" / "config.yaml"
    if default_path.exists():
        return default_path

    example_path = project_root / "config" / "config.example.yaml"
    if example_path.exists():
        return example_path

    return None


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    加载配置文件。

    Args:
        config_path: 配置文件路径。为 None 时按优先级自动解析。

    Returns:
        配置字典，加载失败时返回空字典。
    """
    resolved = _resolve_config_path(config_path)
    if resolved is None or not resolved.exists():
        return {}

    try:
        with open(resolved, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            return config if isinstance(config, dict) else {}
    except Exception as e:
        print(f"加载配置失败 ({resolved}): {e}")
        return {}
