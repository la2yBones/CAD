import logging
import re
import sys
from pathlib import Path
from typing import Optional


class SensitiveDataFilter(logging.Filter):
    """从日志记录中过滤 API Key、token 和其他敏感数据。"""

    _SENSITIVE_PATTERNS = [
        (re.compile(r'sk-[a-zA-Z0-9]{32,}'), 'sk-***REDACTED***'),
        (re.compile(r'api[_-]?key["\s:=]+["\']?([a-zA-Z0-9\-_]{16,})'), r'api_key=***REDACTED***'),
        (re.compile(r'token["\s:=]+["\']?([a-zA-Z0-9\-_]{16,})'), r'token=***REDACTED***'),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "msg") and isinstance(record.msg, str):
            for pattern, replacement in self._SENSITIVE_PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        if record.args:
            record.args = self._sanitize_args(record.args)
        return True

    def _sanitize_text(self, value: str) -> str:
        for pattern, replacement in self._SENSITIVE_PATTERNS:
            value = pattern.sub(replacement, value)
        return value

    def _sanitize_args(self, args):
        if isinstance(args, dict):
            return {
                key: self._sanitize_args(value)
                for key, value in args.items()
            }
        if isinstance(args, tuple):
            return tuple(
                self._sanitize_args(value)
                for value in args
            )
        if isinstance(args, list):
            return [self._sanitize_args(value) for value in args]
        if isinstance(args, str):
            return self._sanitize_text(args)
        return args


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    name: str = "cad_modeler"
) -> logging.Logger:
    """
    设置日志配置

    参数:
        level: 日志级别
        log_file: 日志文件路径
        name: logger名称

    返回:
        配置好的logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    if logger.handlers:
        return logger

    sensitive_filter = SensitiveDataFilter()

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sensitive_filter)
    logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler.addFilter(sensitive_filter)
        logger.addHandler(file_handler)

    return logger
