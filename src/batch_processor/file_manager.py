"""
文件管理器

负责扫描输入目录、校验文件格式、构建输出目录结构。
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.result import Result


class FileManager:
    """CAD 文件管理器，负责文件发现与校验。"""

    SUPPORTED_EXTENSIONS = (".dxf", ".dwg")

    @classmethod
    def scan_files(cls, input_dir: str) -> Result[List[Path]]:
        """
        扫描目录中所有支持的 CAD 文件。

        Args:
            input_dir: 输入目录路径

        Returns:
            Result[List[Path]]: Ok 时为 Path 列表，扫描失败或目录为空时返回 Err。
        """
        path = Path(input_dir)
        if not path.exists():
            return Result.Err(f"输入目录不存在: {input_dir}")
        if not path.is_dir():
            return Result.Err(f"输入路径不是目录: {input_dir}")

        files: List[Path] = []
        for ext in cls.SUPPORTED_EXTENSIONS:
            files.extend(path.rglob(f"*{ext}"))
            files.extend(path.rglob(f"*{ext.upper()}"))

        files = sorted(set(files))
        if not files:
            return Result.Err(f"目录中未找到支持的 CAD 文件（{cls.SUPPORTED_EXTENSIONS}）: {input_dir}")

        return Result.Ok(files)

    @classmethod
    def validate_file(cls, file_path: str) -> Result[Path]:
        """
        校验单个文件是否有效（存在且扩展名受支持）。

        Args:
            file_path: 文件路径

        Returns:
            Result[Path]: Ok 时为 Path 对象，校验失败时返回 Err。
        """
        path = Path(file_path)
        if not path.exists():
            return Result.Err(f"文件不存在: {file_path}")
        if path.suffix.lower() not in cls.SUPPORTED_EXTENSIONS:
            return Result.Err(
                f"不支持的文件类型: {path.suffix}，仅支持 {cls.SUPPORTED_EXTENSIONS}"
            )
        return Result.Ok(path)

    @classmethod
    def build_output_structure(cls, input_path: str, output_dir: str) -> Result[Dict[str, Any]]:
        """
        为输入文件构建输出目录结构。

        Args:
            input_path: 输入文件路径
            output_dir: 输出根目录

        Returns:
            Result[Dict]: Ok 时包含 directory/models 等路径信息
        """
        validate_result = cls.validate_file(input_path)
        if validate_result.is_err():
            return Result.Err(validate_result.error)

        in_path = validate_result.value
        base_name = in_path.stem
        out_path = Path(output_dir) / base_name
        out_path.mkdir(parents=True, exist_ok=True)

        return Result.Ok({
            "input_file": str(in_path),
            "base_name": base_name,
            "directory": str(out_path),
            "models_dir": str(out_path / "models"),
            "analysis_dir": str(out_path / "analysis"),
            "logs_dir": str(out_path / "logs"),
        })
