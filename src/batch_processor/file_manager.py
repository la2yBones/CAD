#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件管理组件
负责CAD文件的查找、验证和输出目录管理
"""

import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class CADFileManager:
    """
    CAD文件管理器
    负责文件路径管理、格式验证、输出目录创建等
    """

    SUPPORTED_FORMATS = ['.dxf', '.dwg']
    OUTPUT_FORMATS = {
        'geometry': '.json',
        'model': '.step',
        'visualization': '.png'
    }

    def __init__(self, input_dir: Optional[str] = None, output_dir: Optional[str] = None):
        """
        初始化文件管理器

        Args:
            input_dir: 输入目录路径
            output_dir: 输出目录路径
        """
        self.input_dir = Path(input_dir) if input_dir else None
        self.base_output_dir = Path(output_dir) if output_dir else None
        self._validate_directories()

    def _validate_directories(self):
        """验证和创建基础目录"""
        if self.input_dir and not self.input_dir.exists():
            logger.warning(f"输入目录不存在: {self.input_dir}")

        if self.base_output_dir:
            self.base_output_dir.mkdir(parents=True, exist_ok=True)

    def set_input_dir(self, input_dir: str):
        """设置输入目录"""
        self.input_dir = Path(input_dir)
        if not self.input_dir.exists():
            logger.warning(f"输入目录不存在: {self.input_dir}")

    def set_output_dir(self, output_dir: str):
        """设置输出目录"""
        self.base_output_dir = Path(output_dir)
        self.base_output_dir.mkdir(parents=True, exist_ok=True)

    def list_available_files(self, input_dir: Optional[str] = None) -> List[Dict]:
        """
        列出目录中所有支持的CAD文件

        Args:
            input_dir: 可选，指定输入目录，默认使用初始化时的目录

        Returns:
            文件信息列表，每个元素包含文件名、路径、大小等信息
        """
        target_dir = Path(input_dir) if input_dir else self.input_dir
        if not target_dir or not target_dir.exists():
            logger.error(f"输入目录无效: {target_dir}")
            return []

        files = []
        for file_path in target_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_FORMATS:
                file_info = {
                    'name': file_path.name,
                    'stem': file_path.stem,
                    'path': str(file_path),
                    'suffix': file_path.suffix.lower(),
                    'size': file_path.stat().st_size
                }
                files.append(file_info)

        logger.info(f"在 {target_dir} 中找到 {len(files)} 个CAD文件")
        return sorted(files, key=lambda x: x['name'])

    def validate_file(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        验证CAD文件是否有效

        Args:
            file_path: 文件路径

        Returns:
            (是否有效, 错误信息)
        """
        path = Path(file_path)

        if not path.exists():
            return False, f"文件不存在: {file_path}"

        if not path.is_file():
            return False, f"不是文件: {file_path}"

        if path.suffix.lower() not in self.SUPPORTED_FORMATS:
            return False, f"不支持的文件格式: {path.suffix}"

        if path.stat().st_size == 0:
            return False, f"文件为空: {file_path}"

        return True, None

    def get_output_path(self, input_file: str, output_type: str = 'model',
                        create_subdir: bool = True) -> Path:
        """
        获取输出文件路径

        Args:
            input_file: 输入文件路径
            output_type: 输出类型 ('geometry', 'model', 'visualization')
            create_subdir: 是否为每个图纸创建独立子目录

        Returns:
            输出文件的完整路径
        """
        input_path = Path(input_file)
        base_name = input_path.stem

        if not self.base_output_dir:
            self.base_output_dir = input_path.parent.parent / 'output'

        if create_subdir:
            output_dir = self.base_output_dir / base_name
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = self.base_output_dir
            output_dir.mkdir(parents=True, exist_ok=True)

        suffix = self.OUTPUT_FORMATS.get(output_type, '.step')
        timestamp = ''  # 可以添加时间戳避免覆盖

        output_file = output_dir / f"{base_name}{timestamp}{suffix}"
        return output_file

    def create_output_structure(self, input_file: str) -> Dict[str, Path]:
        """
        为单个图纸创建完整的输出结构

        Args:
            input_file: 输入文件路径

        Returns:
            包含各类输出路径的字典
        """
        input_path = Path(input_file)
        base_name = input_path.stem

        if not self.base_output_dir:
            self.base_output_dir = input_path.parent.parent / 'output'

        output_subdir = self.base_output_dir / base_name
        output_subdir.mkdir(parents=True, exist_ok=True)

        structure = {
            'directory': output_subdir,
            'geometry': output_subdir / f"{base_name}_geometry.json",
            'model_step': output_subdir / f"{base_name}.step",
            'model_stl': output_subdir / f"{base_name}.stl",
            'visualization': output_subdir / f"{base_name}_preview.png",
            'log': output_subdir / f"{base_name}_process.log"
        }

        return structure

    def get_file_identifier(self, file_path: str) -> str:
        """
        生成文件唯一标识符

        Args:
            file_path: 文件路径

        Returns:
            唯一标识符字符串
        """
        import hashlib
        path = Path(file_path)
        content = f"{path.name}_{path.stat().st_mtime}_{path.stat().st_size}"
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def resolve_file_path(self, filename: str) -> Optional[Path]:
        """
        根据文件名解析完整路径

        Args:
            filename: 文件名或相对路径

        Returns:
            完整的文件路径，找不到返回None
        """
        # 尝试直接作为绝对路径
        path = Path(filename)
        if path.exists():
            return path

        # 尝试在输入目录中查找
        if self.input_dir:
            path_in_dir = self.input_dir / filename
            if path_in_dir.exists():
                return path_in_dir

        # 尝试添加常见扩展名
        for ext in self.SUPPORTED_FORMATS:
            path_with_ext = Path(filename + ext)
            if path_with_ext.exists():
                return path_with_ext
            if self.input_dir:
                path_with_ext_in_dir = self.input_dir / (filename + ext)
                if path_with_ext_in_dir.exists():
                    return path_with_ext_in_dir

        return None
