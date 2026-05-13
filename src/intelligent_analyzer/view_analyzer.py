"""
工程视图分析器
识别二视图、三视图等工程视图结构
支持 DBSCAN 聚类自动识别 + 中国画法几何投影对齐验证
"""
import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ..utils.result import Result

logger = logging.getLogger(__name__)


class ViewAnalyzer:
    """
    工程视图分析器。
    优先级: DBSCAN 聚类 > 自适应间隙检测 > 硬编码坐标区域回退。
    验证规则: 长对正 / 高平齐 / 宽相等（中国画法几何投影原理）。
    """

    VIEW_ZONES = {
        "main": {"x": (0, 150), "y": (50, 150)},
        "top": {"x": (0, 150), "y": (150, 250)},
        "left": {"x": (-100, 0), "y": (50, 150)},
        "right": {"x": (150, 250), "y": (50, 150)},
        "bottom": {"x": (0, 150), "y": (-50, 50)},
    }

    DBSCAN_EPS_AUTO_FRACTION = 0.22
    DBSCAN_MIN_SAMPLES = 3
    CLUSTER_MERGE_OVERLAP_THRESHOLD = 0.25

    def __init__(self, api_key: str = "", api_config: Optional[Dict[str, Any]] = None):
        self._api_key = api_key
        self._api_config = api_config or {}
        self._dbscan_available = self._check_dbscan()

    def _check_dbscan(self) -> bool:
        try:
            from sklearn.cluster import DBSCAN  # noqa: F401
            return True
        except ImportError:
            logger.info("scikit-learn 不可用，回退到基于坐标区域的视图检测")
            return False

    def analyze_views(
        self, entities: List[Dict[str, Any]], layers: Optional[List[Dict[str, Any]]] = None
    ) -> Result[Dict[str, Any]]:
        """
        分析工程图纸视图结构。

        Args:
            entities: 几何实体列表
            layers: 图层信息（可选）

        Returns:
            Result[Dict]: Ok 时包含 views/relationships/layers 等信息
        """
        logger.info("开始分析工程视图结构")

        layers = layers or []
        layer_map = self._group_by_layer(entities)

        structural_entities = [
            e for e in entities
            if e.get("type") not in ("TEXT", "MTEXT", "DIMENSION")
        ]

        centers = []
        valid_indices = []
        for i, entity in enumerate(structural_entities):
            center = self._get_entity_center(entity)
            if center is not None:
                centers.append(center)
                valid_indices.append(i)

        if len(centers) < self.DBSCAN_MIN_SAMPLES:
            logger.info("实体数太少，回退到硬编码区域识别")
            data = self._analyze_fallback(entities, layer_map)
            return Result.Ok(data)

        view_groups = self._adaptive_zone_detect(centers, structural_entities)
        detection_method = "adaptive_zone"

        if view_groups is None and self._dbscan_available:
            try:
                cluster_labels = self._dbscan_cluster(centers)
                unique_labels = set(cluster_labels) - {-1}
                if len(unique_labels) >= 2:
                    raw_groups = self._build_cluster_groups(
                        structural_entities, valid_indices, cluster_labels
                    )
                    view_groups = self._merge_aligned_clusters(raw_groups)
                    detection_method = "DBSCAN"
                    logger.info(f"DBSCAN: {len(raw_groups)}→{len(view_groups)} 个簇")
            except Exception as e:
                logger.warning(f"DBSCAN 失败: {e}")

        if view_groups is None:
            data = self._analyze_fallback(entities, layer_map)
            return Result.Ok(data)

        views = self._infer_view_types(view_groups, centers, valid_indices, structural_entities)
        view_relationships = self._analyze_projection_relationships(views)

        result = {
            "views": views,
            "relationships": view_relationships,
            "layers": list(layer_map.keys()),
            "total_entities": len(entities),
            "detection_method": detection_method,
        }

        logger.info(f"视图分析完成: {len(views)} 个视图 ({detection_method})")
        return Result.Ok(result)

    def _adaptive_zone_detect(
        self, centers: List[Tuple[float, float]], entities: List[Dict]
    ) -> Optional[Dict[int, List[Dict]]]:
        """自适应间隙检测：基于 X/Y 坐标间隙自动划分视图区域。"""
        xs = [c[0] for c in centers]
        ys = [c[1] for c in centers]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        data_range = max(max_x - min_x, max_y - min_y, 1.0)

        x_boundaries = self._find_gaps(xs, min_gap_ratio=0.10, max_groups=3)
        y_boundaries = self._find_gaps(ys, min_gap_ratio=0.08, max_groups=3)

        if len(x_boundaries) <= 1 and len(y_boundaries) <= 1:
            return None

        x_zones: List[Tuple[float, float]] = []
        prev = min_x - 1
        for b in sorted(x_boundaries):
            x_zones.append((prev, b))
            prev = b
        x_zones.append((prev, max_x + data_range))

        y_zones: List[Tuple[float, float]] = []
        prev = min_y - 1
        for b in sorted(y_boundaries):
            y_zones.append((prev, b))
            prev = b
        y_zones.append((prev, max_y + data_range))

        groups = self._assign_to_grid(centers, entities, x_zones, y_zones)
        nonempty = {k: v for k, v in groups.items() if v}
        if len(nonempty) >= 2:
            logger.info(
                f"自适应区域: {len(x_zones)}×{len(y_zones)} 网格, "
                f"{len(nonempty)} 个非空单元格"
            )
            return nonempty
        return None

    def _find_gaps(
        self, values: List[float], min_gap_ratio: float, max_groups: int
    ) -> List[float]:
        """在排序值中寻找显著间隙。"""
        if len(values) < 4:
            return []
        sorted_vals = sorted(values)
        data_range = sorted_vals[-1] - sorted_vals[0]
        if data_range <= 0:
            return []
        min_gap = data_range * min_gap_ratio
        gaps: List[Tuple[float, float]] = []
        for i in range(len(sorted_vals) - 1):
            g = sorted_vals[i + 1] - sorted_vals[i]
            if g >= min_gap:
                mid = (sorted_vals[i] + sorted_vals[i + 1]) / 2
                gaps.append((g, mid))
        gaps.sort(key=lambda x: -x[0])
        return [mid for _, mid in gaps[:max_groups - 1]]

    def _assign_to_grid(
        self,
        centers: List[Tuple[float, float]],
        entities: List[Dict],
        x_zones: List[Tuple[float, float]],
        y_zones: List[Tuple[float, float]],
    ) -> Dict[int, List[Dict]]:
        """将实体分配到网格的各个单元格。"""
        groups: Dict[int, List[Dict]] = defaultdict(list)
        for ci, (cx, cy) in enumerate(centers):
            xi = 0
            for i, (xlo, xhi) in enumerate(x_zones):
                if xlo <= cx < xhi:
                    xi = i
                    break
            yi = 0
            for j, (ylo, yhi) in enumerate(y_zones):
                if ylo <= cy < yhi:
                    yi = j
                    break
            cell_id = xi * 100 + yi
            groups[cell_id].append(entities[ci])
        return dict(groups)

    def _analyze_fallback(
        self, entities: List[Dict], layers: Dict[str, List[Dict]]
    ) -> Dict[str, Any]:
        """硬编码区域回退（保持向后兼容）。"""
        view_groups = self._group_by_position(entities)
        views = self._identify_view_types(view_groups, layers)
        relationships = self._analyze_view_relationships(views)
        return {
            "views": views,
            "relationships": relationships,
            "layers": list(layers.keys()),
            "total_entities": len(entities),
            "detection_method": "zone_fallback",
        }

    def _dbscan_cluster(self, centers: List[Tuple[float, float]]) -> List[int]:
        from sklearn.cluster import DBSCAN
        xs = [c[0] for c in centers]
        ys = [c[1] for c in centers]
        data_range = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        eps = data_range * self.DBSCAN_EPS_AUTO_FRACTION
        eps = max(eps, 5.0)
        eps = min(eps, 500.0)
        clustering = DBSCAN(eps=eps, min_samples=self.DBSCAN_MIN_SAMPLES)
        return list(clustering.fit_predict(centers))

    def _build_cluster_groups(
        self, entities: List[Dict], valid_indices: List[int], labels: List[int]
    ) -> Dict[int, List[Dict]]:
        groups: Dict[int, List[Dict]] = defaultdict(list)
        for vi, label in zip(valid_indices, labels):
            if label >= 0:
                groups[label].append(entities[vi])
        return dict(groups)

    def _merge_aligned_clusters(
        self, groups: Dict[int, List[Dict]]
    ) -> Dict[int, List[Dict]]:
        """合并投影对齐的碎片簇。"""
        if len(groups) <= 1:
            return groups
        labels = list(groups.keys())
        bboxes = {l: self._compute_bbox_for_cluster(groups[l]) for l in labels}
        parent = {l: l for l in labels}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                bi, bj = bboxes[labels[i]], bboxes[labels[j]]
                x_overlap = self._range_overlap((bi[0], bi[2]), (bj[0], bj[2]))
                y_overlap = self._range_overlap((bi[1], bi[3]), (bj[1], bj[3]))
                if x_overlap > self.CLUSTER_MERGE_OVERLAP_THRESHOLD or \
                   y_overlap > self.CLUSTER_MERGE_OVERLAP_THRESHOLD:
                    union(labels[i], labels[j])

        merged: Dict[int, List[Dict]] = defaultdict(list)
        for l in labels:
            root = find(l)
            merged[root].extend(groups[l])
        return dict(merged)

    def _compute_bbox_for_cluster(
        self, entities: List[Dict]
    ) -> Tuple[float, float, float, float]:
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        for e in entities:
            for x, y in self._extract_coords(e):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
        if min_x == float('inf'):
            return (0.0, 0.0, 0.0, 0.0)
        return (min_x, min_y, max_x, max_y)

    def _extract_coords(self, entity: Dict) -> List[Tuple[float, float]]:
        etype = entity.get("type")
        coords: List[Tuple[float, float]] = []
        if etype == "LINE":
            coords.append((entity["start"][0], entity["start"][1]))
            coords.append((entity["end"][0], entity["end"][1]))
        elif etype in ("CIRCLE", "ARC"):
            cx, cy = entity["center"][0], entity["center"][1]
            r = entity.get("radius", 0)
            coords.append((cx - r, cy - r))
            coords.append((cx + r, cy + r))
        elif etype in ("LWPOLYLINE", "ELLIPSE", "SPLINE"):
            for v in entity.get("vertices", []):
                coords.append((v[0], v[1]))
        elif etype == "TEXT":
            coords.append((entity["position"][0], entity["position"][1]))
        elif etype == "DIMENSION":
            for p in entity.get("definition_points", []):
                coords.append((p[0], p[1]))
        else:
            c = self._get_entity_center(entity)
            if c:
                coords.append(c)
        return coords

    def _infer_view_types(
        self,
        view_groups: Dict[int, List[Dict]],
        centers: List[Tuple[float, float]],
        valid_indices: List[int],
        entities: List[Dict],
    ) -> List[Dict]:
        """基于簇质心相对位置推断视图类型。"""
        if len(view_groups) == 1:
            label = list(view_groups.keys())[0]
            return [{
                "name": "single",
                "type": "单视图",
                "entities": view_groups[label],
                "entity_count": len(view_groups[label]),
                "bbox": self._compute_bbox(view_groups[label]),
            }]

        centroids = {label: self._compute_centroid(group) for label, group in view_groups.items()}
        sorted_clusters = sorted(centroids.items(), key=lambda kv: kv[1][0])
        main_label = sorted_clusters[0][0]
        main_cx, main_cy = centroids[main_label]

        name_map: Dict[str, List[int]] = defaultdict(list)
        name_map["main"].append(main_label)

        for label, (cx, cy) in centroids.items():
            if label == main_label:
                continue
            dx, dy = cx - main_cx, cy - main_cy
            if abs(dx) < abs(dy) * 0.8:
                name_map["top" if dy > 0 else "bottom"].append(label)
            else:
                name_map["right" if dx > 0 else "left"].append(label)

        type_map = {
            "main": "主视图", "top": "俯视图", "bottom": "仰视图",
            "left": "左视图", "right": "右视图",
        }
        views: List[Dict] = []
        for name in ["main", "top", "bottom", "left", "right"]:
            labels = name_map.get(name)
            if not labels:
                continue
            merged = []
            for l in labels:
                merged.extend(view_groups[l])
            views.append({
                "name": name,
                "type": type_map[name],
                "entities": merged,
                "entity_count": len(merged),
                "bbox": self._compute_bbox(merged),
                "centroid": list(self._compute_centroid(merged)),
            })
        return views

    def _analyze_projection_relationships(self, views: List[Dict]) -> List[Dict]:
        """中国画法几何投影对齐验证。"""
        if len(views) < 2:
            return []
        main = next((v for v in views if v["name"] == "main"), None)
        if main is None:
            return []
        main_bbox = main.get("bbox") or self._compute_bbox(main["entities"])
        relationships = []
        for view in views:
            if view["name"] == "main":
                continue
            v_bbox = view.get("bbox") or self._compute_bbox(view["entities"])
            relation = {"type": "projection", "views": ["main", view["name"]]}
            x_overlap = self._range_overlap((main_bbox[0], main_bbox[2]), (v_bbox[0], v_bbox[2]))
            y_overlap = self._range_overlap((main_bbox[1], main_bbox[3]), (v_bbox[1], v_bbox[3]))
            if view["name"] in ("top", "bottom"):
                if x_overlap > 0.5:
                    relation["description"] = f"主视图与{view['type']}长对正 (X重叠度 {x_overlap:.0%})"
                else:
                    relation["description"] = f"主视图与{view['type']}X方向偏差较大 (重叠度 {x_overlap:.0%})"
            if view["name"] in ("left", "right"):
                if y_overlap > 0.5:
                    relation["description"] = f"主视图与{view['type']}高平齐 (Y重叠度 {y_overlap:.0%})"
                else:
                    relation["description"] = f"主视图与{view['type']}Y方向偏差较大 (重叠度 {y_overlap:.0%})"
            v_width = v_bbox[2] - v_bbox[0]
            main_width = main_bbox[2] - main_bbox[0]
            width_ratio = min(main_width, v_width) / max(main_width, v_width, 0.001)
            if width_ratio > 0.3 and view["name"] in ("top", "bottom"):
                relation["width_match"] = f"宽相等 (宽度比 {width_ratio:.0%})"
            relationships.append(relation)
        return relationships

    def _range_overlap(self, r1: Tuple[float, float], r2: Tuple[float, float]) -> float:
        a1, b1 = sorted(r1)
        a2, b2 = sorted(r2)
        overlap = min(b1, b2) - max(a1, a2)
        if overlap <= 0:
            return 0.0
        union = max(b1, b2) - min(a1, a2)
        return overlap / union if union > 0 else 0.0

    def _compute_centroid(self, entities: List[Dict]) -> Tuple[float, float]:
        xs, ys = [], []
        for e in entities:
            c = self._get_entity_center(e)
            if c:
                xs.append(c[0])
                ys.append(c[1])
        return (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else (0.0, 0.0)

    def _compute_bbox(self, entities: List[Dict]) -> Tuple[float, float, float, float]:
        xs, ys = [], []
        for e in entities:
            c = self._get_entity_center(e)
            if c:
                xs.append(c[0])
                ys.append(c[1])
        return (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)

    def _group_by_layer(self, entities: List[Dict]) -> Dict[str, List[Dict]]:
        layers: Dict[str, List[Dict]] = defaultdict(list)
        for entity in entities:
            layer = entity.get("layer", "default")
            layers[layer].append(entity)
        return dict(layers)

    def _group_by_position(self, entities: List[Dict]) -> Dict[str, List[Dict]]:
        view_groups: Dict[str, List[Dict]] = defaultdict(list)
        for entity in entities:
            center = self._get_entity_center(entity)
            if center is None:
                continue
            for view_name, zone in self.VIEW_ZONES.items():
                if zone["x"][0] <= center[0] <= zone["x"][1] and \
                   zone["y"][0] <= center[1] <= zone["y"][1]:
                    view_groups[view_name].append(entity)
                    break
            else:
                view_groups["unknown"].append(entity)
        return dict(view_groups)

    def _get_entity_center(self, entity: Dict) -> Optional[Tuple[float, float]]:
        entity_type = entity.get("type")
        if entity_type == "CIRCLE":
            return (entity["center"][0], entity["center"][1])
        elif entity_type == "LINE":
            return (
                (entity["start"][0] + entity["end"][0]) / 2,
                (entity["start"][1] + entity["end"][1]) / 2,
            )
        elif entity_type in ("LWPOLYLINE", "ELLIPSE", "SPLINE"):
            pts = entity.get("vertices", [])
            if pts:
                return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        elif entity_type == "TEXT":
            return (entity["position"][0], entity["position"][1])
        elif entity_type == "DIMENSION":
            pts = entity.get("definition_points", [])
            if pts:
                return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        elif entity_type == "ARC":
            return (entity["center"][0], entity["center"][1])
        elif entity_type == "INSERT":
            pos = entity.get("position")
            if pos:
                return (pos[0], pos[1])
        return None

    def _identify_view_types(
        self, view_groups: Dict[str, List[Dict]], layers: Dict[str, List[Dict]]
    ) -> List[Dict]:
        views = []
        for view_name, group_entities in view_groups.items():
            if view_name == "unknown" or not group_entities:
                continue
            views.append({
                "name": view_name,
                "type": self._determine_view_type(view_name),
                "entities": group_entities,
                "entity_count": len(group_entities),
                "layers": list(set(e.get("layer", "default") for e in group_entities)),
            })
        return views

    def _determine_view_type(self, view_name: str) -> str:
        return {
            "main": "主视图", "top": "俯视图",
            "left": "左视图", "right": "右视图", "bottom": "仰视图",
        }.get(view_name, "未知视图")

    def _analyze_view_relationships(self, views: List[Dict]) -> List[Dict]:
        relationships = []
        main_view = next((v for v in views if v["name"] == "main"), None)
        top_view = next((v for v in views if v["name"] == "top"), None)
        left_view = next((v for v in views if v["name"] == "left"), None)
        if main_view and top_view:
            relationships.append({
                "type": "projection",
                "views": ["main", "top"],
                "description": "主视图与俯视图长对正",
            })
        if main_view and left_view:
            relationships.append({
                "type": "projection",
                "views": ["main", "left"],
                "description": "主视图与左视图高平齐",
            })
        if top_view and left_view:
            relationships.append({
                "type": "projection",
                "views": ["top", "left"],
                "description": "俯视图与左视图宽相等",
            })
        return relationships
