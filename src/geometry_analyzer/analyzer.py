"""
[DEPRECATED] 基础几何分析器

本模块为早期原型，将在 v1.0 移除。
新代码请使用 intelligent_analyzer 模块进行 AI 驱动的视图检测与尺寸提取。
"""

from typing import Any, Dict, List, Optional

from ..utils.result import Result


class GeometryAnalyzer:
    """[DEPRECATED] 基础几何分析器。"""

    def analyze(self, parsed_data: Dict[str, Any]) -> Result[Dict[str, Any]]:
        """
        对已解析的 CAD 数据进行基础几何分析。

        Args:
            parsed_data: CADParser.parse() 的 Ok 值

        Returns:
            Result[Dict]: Ok 时包含基本统计信息
        """
        try:
            entities = parsed_data.get("entities", [])
            layers = parsed_data.get("layers", [])

            stats = self._compute_stats(entities)
            bounds = self._compute_bounds(entities)
            layer_dist = self._layer_distribution(entities)

            return Result.Ok({
                "entity_count": len(entities),
                "layer_count": len(layers),
                "statistics": stats,
                "bounds": bounds,
                "layer_distribution": layer_dist,
            })
        except Exception as e:
            return Result.Err(f"几何分析失败: {e}")

    def _compute_stats(self, entities: List[Dict[str, Any]]) -> Dict[str, int]:
        """统计各类型实体数量。"""
        stats: Dict[str, int] = {}
        for e in entities:
            etype = e.get("type", "UNKNOWN")
            stats[etype] = stats.get(etype, 0) + 1
        return stats

    def _compute_bounds(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算实体的包围盒（仅处理 LINE/CIRCLE/LWPOLYLINE）。"""
        xs, ys = [], []
        for e in entities:
            etype = e.get("type", "")
            if etype == "LINE":
                xs.extend([e.get("start", (0, 0))[0], e.get("end", (0, 0))[0]])
                ys.extend([e.get("start", (0, 0))[1], e.get("end", (0, 0))[1]])
            elif etype == "CIRCLE":
                cx, cy = e.get("center", (0, 0))
                r = e.get("radius", 0)
                xs.extend([cx - r, cx + r])
                ys.extend([cy - r, cy + r])
            elif etype == "LWPOLYLINE":
                for pt in e.get("points", []):
                    xs.append(pt[0])
                    ys.append(pt[1])

        if not xs or not ys:
            return {"min_x": 0, "max_x": 0, "min_y": 0, "max_y": 0}

        return {
            "min_x": min(xs),
            "max_x": max(xs),
            "min_y": min(ys),
            "max_y": max(ys),
            "width": max(xs) - min(xs),
            "height": max(ys) - min(ys),
        }

    def _layer_distribution(self, entities: List[Dict[str, Any]]) -> Dict[str, int]:
        """统计各图层实体数量。"""
        dist: Dict[str, int] = {}
        for e in entities:
            layer = e.get("layer", "0")
            dist[layer] = dist.get(layer, 0) + 1
        return dist
