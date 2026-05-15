import json
import warnings
from typing import Dict, List, Any, Optional
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

LOCAL_ANALYSIS_LIMIT = 300
class GeometryAnalyzer:
    """
    【已废弃】 几何关系分析器，使用DeepSeek分析实体间关系

    此分析器已废弃。请使用 IntelligentEngineeringAnalyzer 替代:
        from src.intelligent_analyzer import IntelligentEngineeringAnalyzer

    IntelligentEngineeringAnalyzer 整合了视图识别、尺寸提取、本地几何分析回退
    和 AI 建模指令生成，功能更完整且性能更优（STRtree 空间索引）。
    此分析器保留以确保向后兼容，将在 v1.0 中移除。
    """

    def __init__(self, api_key: str, config: Optional[Dict] = None):
        warnings.warn(
            "GeometryAnalyzer 已废弃，请使用 IntelligentEngineeringAnalyzer 替代。"
            "详见 src/intelligent_analyzer/pipeline.py",
            DeprecationWarning,
            stacklevel=2
        )
        self.api_key = api_key
        self.config = config or {}
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.config.get("base_url", "https://api.deepseek.com")
        )
        self.model = self.config.get("model", "deepseek-v4-pro")

        max_prompt_tokens = self.config.get("max_prompt_tokens", 12000)
        self.MAX_PROMPT_CHARS = max_prompt_tokens * 4

    def analyze(self, geometry_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析几何实体间的关系

        ??:
            geometry_data: 从DXF解析得到的几何数据

        ??:
            包含关系分析结果的字典
        """
        logger.info("开始分析几何关系")

        # 首先尝试使用本地计算（如果可用）
        try:
            local_result = self._analyze_local(geometry_data)
            if local_result.get("entity_pairs"):
                logger.info("本地几何分析完成")
                return local_result
        except Exception as e:
            logger.warning(f"本地分析失败，将使用AI分析: {e}")

        # 使用AI分析
        ai_result = self._analyze_ai(geometry_data)
        logger.info("AI几何分析完成")
        return ai_result

    def _analyze_local(self, geometry_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用本地几何计算进行基础分析 (STRtree, O(n log n))"""
        try:
            import shapely.geometry as sg
            from shapely.strtree import STRtree

            entities = geometry_data.get("entities", [])
            if len(entities) > LOCAL_ANALYSIS_LIMIT:
                logger.info(
                    f"实体数 {len(entities)} 超过阈值 {LOCAL_ANALYSIS_LIMIT}，跳过本地分析"
                )
                return {"entity_pairs": [], "summary": "", "method": "local_skipped"}

            shapes = []
            for i, entity in enumerate(entities):
                shape = self._entity_to_shapely(entity)
                if shape:
                    shapes.append((i, shape))

            if len(shapes) < 2:
                return {
                    "entity_pairs": [],
                    "summary": f"仅 {len(shapes)} 个可分析实体",
                    "method": "local"
                }

            shapely_objects = [s[1] for s in shapes]
            tree = STRtree(shapely_objects)

            pairs = []
            for i in range(len(shapes)):
                idx1, shape1 = shapes[i]
                candidates = tree.query(shape1)
                for j in candidates:
                    if j <= i:
                        continue
                    idx2, shape2 = shapes[j]
                    relationship = self._calculate_relationship(shape1, shape2)
                    if relationship != "相离":
                        pairs.append({
                            "id1": idx1,
                            "id2": idx2,
                            "relationship": relationship
                        })

            return {
                "entity_pairs": pairs,
                "summary": f"检测到 {len(entities)} 个实体，分析了 {len(pairs)} 对关系",
                "method": "local_strtree"
            }

        except ImportError:
            raise Exception("需要安装shapely库")

    def _entity_to_shapely(self, entity: Dict):
        """将实体转换为Shapely几何对象"""
        import shapely.geometry as sg

        entity_type = entity.get("type")

        if entity_type == "LINE":
            return sg.LineString([entity["start"][:2], entity["end"][:2]])
        elif entity_type == "CIRCLE":
            return sg.Point(entity["center"][:2]).buffer(entity["radius"])
        elif entity_type == "LWPOLYLINE":
            points = [p[:2] for p in entity["vertices"]]
            if entity.get("closed", False):
                return sg.Polygon(points)
            else:
                return sg.LineString(points)
        elif entity_type == "ARC":
            return None  # Shapely对圆弧支持有限

        return None

    def _calculate_relationship(self, shape1, shape2) -> str:
        """计算两个几何对象的关系"""
        if shape1.contains(shape2) or shape2.contains(shape1):
            return "包含"
        elif shape1.intersects(shape2):
            if shape1.touches(shape2):
                return "相切"
            else:
                return "相交"
        else:
            return "相离"

    def _analyze_ai(self, geometry_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用DeepSeek进行AI分析"""
        prompt = self._build_prompt(geometry_data)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """你是专业的CAD几何分析专家。请分析输入的几何数据，识别实体间的空间关系。
                        输出格式要求：JSON格式，包含以下字段：
                        - entity_pairs: 实体对列表，每项包含id1, id2, relationship
                        - relationship_types: 包含、相交、相切、相离、同心、共线
                        - summary: 关系总结
                        """
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.config.get("max_tokens", 4096),
                extra_body={"thinking": {"type": "enabled", "reasoning_effort": self.config.get("reasoning_effort", "max")}} if self.config.get("thinking", True) else None,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            result["method"] = "ai"
            return result

        except Exception as e:
            logger.error(f"AI分析失败: {e}")
            return {
                "entity_pairs": [],
                "summary": f"AI分析失败: {str(e)}",
                "method": "none"
            }

    MAX_ENTITIES_IN_PROMPT = 30
    MAX_ENTITY_JSON_CHARS = 500

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _truncate_entity_json(self, entity: Dict) -> str:
        raw = json.dumps(entity, ensure_ascii=False)
        if len(raw) > self.MAX_ENTITY_JSON_CHARS:
            raw = raw[:self.MAX_ENTITY_JSON_CHARS] + "..."
        return raw

    def _build_prompt(self, geometry_data: Dict[str, Any]) -> str:
        entities = geometry_data.get("entities", [])

        if len(entities) > self.MAX_ENTITIES_IN_PROMPT:
            type_counts = {}
            for e in entities:
                t = e.get("type", "unknown")
                type_counts[t] = type_counts.get(t, 0) + 1

            entities_desc = []
            for i, e in enumerate(entities[:self.MAX_ENTITIES_IN_PROMPT]):
                entities_desc.append(f"实体{i} ({e['type']}): {self._truncate_entity_json(e)}")

            entities_desc.append(
                f"\n... 共 {len(entities)} 个实体，已展示前 {self.MAX_ENTITIES_IN_PROMPT} 个"
            )
            entities_desc.append(
                f"实体类型分布: {json.dumps(type_counts, ensure_ascii=False)}"
            )
        else:
            entities_desc = [
                f"实体{i} ({e['type']}): {self._truncate_entity_json(e)}"
                for i, e in enumerate(entities)
            ]

        prompt = f"""
        以下是CAD图纸中的几何实体数据：

        {chr(10).join(entities_desc)}

        请分析这些实体之间的空间拓扑关系，包括：包含、相交、相切、相离、同心、共线等关系。
        """

        if len(prompt) > self.MAX_PROMPT_CHARS:
            logger.warning(
                f"Prompt过长 ({len(prompt)}字符, ~{self._estimate_tokens(prompt)} tokens), 进行截断"
            )
            prompt = prompt[:self.MAX_PROMPT_CHARS] + "\n... (内容已截断以适配token限制)"

        estimated_tokens = self._estimate_tokens(prompt)
        logger.info(f"Prompt大小: {len(prompt)}字符, ~{estimated_tokens} tokens")
        return prompt
