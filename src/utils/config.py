import yaml
from pathlib import Path
from typing import Dict, Any, Optional


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径，默认为 config/config.yaml

    Returns:
        配置字典
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"

    config_path = Path(config_path)

    if not config_path.exists():
        # 尝试加载示例配置
        example_path = config_path.parent / "config.example.yaml"
        if example_path.exists():
            config_path = example_path
        else:
            return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"加载配置失败: {e}")
        return {}
