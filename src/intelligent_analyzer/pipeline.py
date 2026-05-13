"""
智能分析流水线

整合视图分析、尺寸提取与建模指令生成，提供统一的分析入口。
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.result import Result
from .view_analyzer import ViewAnalyzer
from .dimension_extractor import DimensionExtractor
from .modeling_generator import ModelingGenerator


class IntelligentEngineeringAnalyzer:
    """
    智能工程分析器。

    整合以下分析步骤：
    1. 视图识别（ViewAnalyzer）
    2. 尺寸提取（DimensionExtractor）
    3. 建模指令生成（ModelingGenerator）
    """

    def __init__(
        self,
        api_key: str,
        api_config: Optional[Dict[str, Any]] = None,
        enable_cache: bool = True,
        cache_dir: Optional[str] = None,
        cache_ttl: int = 86400,
    ):
        self._api_key = api_key
        self._api_config = api_config or {}
        self._enable_cache = enable_cache
        self._cache_dir = cache_dir
        self._cache_ttl = cache_ttl

        self._view_analyzer = ViewAnalyzer(
            api_key=api_key,
            api_config=self._api_config,
        )
        self._dim_extractor = DimensionExtractor(
            api_key=api_key,
            api_config=self._api_config,
        )
        self._modeling_generator = ModelingGenerator()

    def analyze_full(
        self,
        geometry_data: Dict[str, Any],
        extrude_height: float = 10.0,
        file_path: Optional[str] = None,
    ) -> Result[Dict[str, Any]]:
        """
        执行完整的智能分析流水线。

        Args:
            geometry_data: CAD 解析后的几何数据（含 entities, layers 等）
            extrude_height: 默认拉伸高度（毫米）
            file_path: 原始文件路径（用于缓存键）

        Returns:
            Result[Dict]: Ok 时包含 views/dimensions/modeling_instructions 等字段
        """
        start_time = time.time()

        entities = geometry_data.get("entities", [])
        layers = geometry_data.get("layers", [])

        if not entities:
            return Result.Err("几何数据中未找到任何实体，无法进行分析。")

        view_result = self._view_analyzer.analyze_views(entities, layers)
        if view_result.is_err():
            return Result.Err(f"视图分析失败: {view_result.error}")
        views = view_result.value

        dim_result = self._dim_extractor.extract_dimensions(entities, views)
        if dim_result.is_err():
            return Result.Err(f"尺寸提取失败: {dim_result.error}")
        dimensions = dim_result.value

        gen_result = self._modeling_generator.generate(views, dimensions, extrude_height)
        if gen_result.is_err():
            return Result.Err(f"建模指令生成失败: {gen_result.error}")
        generation = gen_result.value

        elapsed = round(time.time() - start_time, 2)

        return Result.Ok({
            "success": True,
            "views": views,
            "dimensions": dimensions,
            "modeling_instructions": generation.get("modeling_instructions", {}),
            "freecad_script": generation.get("freecad_script", ""),
            "extrude_height": extrude_height,
            "statistics": {
                "entity_count": len(entities),
                "layer_count": len(layers),
                "view_count": len(views),
                "dimension_count": len(dimensions),
                "analysis_time_seconds": elapsed,
            },
            "analysis_id": self._generate_analysis_id(file_path),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    def _generate_analysis_id(self, file_path: Optional[str]) -> str:
        """基于文件路径和时间戳生成分析ID。"""
        if file_path:
            stem = Path(file_path).stem
            return f"analysis_{stem}_{int(time.time())}"
        return f"analysis_{int(time.time())}"

    def get_view_analyzer(self) -> ViewAnalyzer:
        """获取视图分析器实例。"""
        return self._view_analyzer

    def get_dimension_extractor(self) -> DimensionExtractor:
        """获取尺寸提取器实例。"""
        return self._dim_extractor
