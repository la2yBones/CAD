"""
尺寸标注提取器
从工程图纸中提取尺寸标注信息
"""
import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ..utils.result import Result

logger = logging.getLogger(__name__)


class DimensionExtractor:
    """尺寸标注提取器，提取并解析工程图纸中的尺寸标注。"""

    DIMENSION_PATTERNS = [
        r'(\d+\.?\d*)',
        r'φ?(\d+\.?\d*)',
        r'R(\d+\.?\d*)',
        r'M(\d+\.?\d*)',
        r'(\d+\.?\d*)[-~](\d+\.?\d*)',
    ]

    def __init__(self, api_key: str = "", api_config: Optional[Dict[str, Any]] = None):
        self._api_key = api_key
        self._api_config = api_config or {}

    def extract_dimensions(
        self, entities: List[Dict[str, Any]], views: Optional[List[Dict[str, Any]]] = None
    ) -> Result[Dict[str, Any]]:
        """
        提取尺寸标注信息。

        Args:
            entities: 几何实体列表
            views: 视图分析结果（可选）

        Returns:
            Result[Dict]: Ok 时包含 dimensions/classified/total/text_count 等字段
        """
        logger.info("开始提取尺寸标注")

        texts = [e for e in entities if e.get("type") in ("TEXT", "MTEXT")]
        lines = [e for e in entities if e.get("type") == "LINE"]

        dimension_texts = self._identify_dimension_texts(texts)

        dimensions = []
        for text_info in dimension_texts:
            dim_data = self._parse_dimension_text(text_info, lines)
            if dim_data:
                dimensions.append(dim_data)

        classified = self._classify_dimensions(dimensions)

        result = {
            "dimensions": dimensions,
            "classified": classified,
            "total": len(dimensions),
            "text_count": len(dimension_texts),
        }

        logger.info(f"尺寸提取完成: 找到 {len(dimensions)} 个尺寸")
        return Result.Ok(result)

    def _identify_dimension_texts(self, texts: List[Dict]) -> List[Dict]:
        """识别可能是尺寸标注的文本。"""
        dimension_texts = []
        for entity in texts:
            text_content = entity.get("text", "")
            if self._is_likely_dimension(text_content):
                dimension_texts.append({
                    "text": text_content,
                    "position": entity.get("position", [0, 0, 0]),
                    "entity": entity,
                })
        return dimension_texts

    def _is_likely_dimension(self, text: str) -> bool:
        """判断文本是否可能是尺寸标注。"""
        if not text or not text.strip():
            return False
        for pattern in self.DIMENSION_PATTERNS:
            if re.search(pattern, text):
                return True
        return False

    def _parse_dimension_text(
        self, text_info: Dict, lines: List[Dict]
    ) -> Optional[Dict]:
        """解析尺寸文本。"""
        text = text_info["text"]
        value = self._extract_numeric_value(text)
        if value is None:
            return None
        return {
            "text": text,
            "value": value,
            "type": self._determine_dimension_type(text),
            "position": text_info["position"],
            "associated_lines": self._find_nearby_lines(text_info["position"], lines),
        }

    def _extract_numeric_value(self, text: str) -> Optional[float]:
        match = re.search(r'(\d+\.?\d*)', text)
        if match:
            return float(match.group(1))
        return None

    def _determine_dimension_type(self, text: str) -> str:
        if 'φ' in text or 'Φ' in text:
            return "直径"
        elif 'R' in text or 'r' in text:
            return "半径"
        elif 'M' in text:
            return "螺纹"
        else:
            return "线性"

    def _find_nearby_lines(
        self, position: List[float], lines: List[Dict], max_dist: float = 20.0
    ) -> List[Dict]:
        """查找尺寸文本附近的线段（标注线）。"""
        pos_x, pos_y = position[0], position[1]
        nearby = []
        for line in lines:
            dist = self._distance_to_line(pos_x, pos_y, line)
            if dist <= max_dist:
                nearby.append({"line": line, "distance": dist})
        nearby.sort(key=lambda x: x["distance"])
        return nearby[:3]

    def _distance_to_line(self, px: float, py: float, line: Dict) -> float:
        x1, y1 = line["start"][0], line["start"][1]
        x2, y2 = line["end"][0], line["end"][1]
        A, B = px - x1, py - y1
        C, D = x2 - x1, y2 - y1
        dot = A * C + B * D
        len_sq = C * C + D * D
        param = dot / len_sq if len_sq != 0 else -1.0
        if param < 0:
            xx, yy = x1, y1
        elif param > 1:
            xx, yy = x2, y2
        else:
            xx = x1 + param * C
            yy = y1 + param * D
        dx, dy = px - xx, py - yy
        return (dx * dx + dy * dy) ** 0.5

    def _classify_dimensions(
        self, dimensions: List[Dict]
    ) -> Dict[str, List[Dict]]:
        classified: Dict[str, List[Dict]] = defaultdict(list)
        for dim in dimensions:
            dim_type = dim.get("type", "其他")
            classified[dim_type].append(dim)
        return dict(classified)
