import json
from typing import Dict, List, Any, Optional
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)


class GeometryAnalyzer:
    """几何关系分析器，使用Qwen3.5分析实体间关系"""

    def __init__(self, api_key: str, config: Optional[Dict] = None):
        self.api_key = api_key
        self.config = config or {}
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self.model = self.config.get("model", "qwen3.5-plus")

    def analyze(self, geometry_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析几何实体间的关系

        Args:
            geometry_data: 从DXF解析得到的几何数据

        Returns:
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
        """使用本地几何计算进行基础分析"""
        try:
            import shapely.geometry as sg
            from shapely.ops import nearest_points

            entities = geometry_data.get("entities", [])
            pairs = []

            # 创建几何对象
            shapes = []
            for i, entity in enumerate(entities):
                shape = self._entity_to_shapely(entity)
                if shape:
                    shapes.append((i, shape))

            # 计算关系
            for i in range(len(shapes)):
                for j in range(i + 1, len(shapes)):
                    idx1, shape1 = shapes[i]
                    idx2, shape2 = shapes[j]

                    relationship = self._calculate_relationship(shape1, shape2)
                    pairs.append({
                        "id1": idx1,
                        "id2": idx2,
                        "relationship": relationship
                    })

            return {
                "entity_pairs": pairs,
                "summary": f"检测到 {len(entities)} 个实体，分析了 {len(pairs)} 对关系",
                "method": "local"
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
        """使用Qwen3.5进行AI分析"""
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
                temperature=self.config.get("temperature", 0.3),
                max_tokens=self.config.get("max_tokens", 4096),
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

    def _build_prompt(self, geometry_data: Dict[str, Any]) -> str:
        """构建AI分析的提示词"""
        entities = geometry_data.get("entities", [])

        entities_desc = []
        for i, entity in enumerate(entities):
            entities_desc.append(f"实体{i} ({entity['type']}): {json.dumps(entity, ensure_ascii=False)}")

        prompt = f"""
        以下是CAD图纸中的几何实体数据：

        {chr(10).join(entities_desc)}

        请分析这些实体之间的空间拓扑关系，包括：包含、相交、相切、相离、同心、共线等关系。
        """

        return prompt
