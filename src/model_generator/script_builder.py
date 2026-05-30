#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FreeCAD 脚本生成公共模块 — 轮廓分组与 fallback 脚本构建。"""

import math
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SUPPORTED_CONTOUR_TYPES = ("LINE", "CIRCLE", "ARC", "LWPOLYLINE", "ELLIPSE", "SPLINE")


def group_entities_into_contours(entities: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    TOL = 1e-3
    processed: set = set()
    contours: List[List[Dict[str, Any]]] = []

    def get_endpoints(e: Dict[str, Any]) -> Tuple[Optional[Tuple], Optional[Tuple]]:
        t = e.get("type")
        if t == "LINE":
            s = tuple(e.get("start", [0, 0])[:2])
            ep = tuple(e.get("end", [0, 0])[:2])
            return s, ep
        elif t == "LWPOLYLINE":
            v = e.get("vertices", [])
            if len(v) >= 2:
                return tuple(v[0])[:2], tuple(v[-1])[:2]
            return None, None
        elif t == "ARC":
            center = e.get("center", [0, 0])
            cx, cy = center[0], center[1]
            r = e.get("radius", 0)
            sa = math.radians(e.get("start_angle", 0))
            ea = math.radians(e.get("end_angle", 0))
            sx, sy = cx + r * math.cos(sa), cy + r * math.sin(sa)
            ex, ey = cx + r * math.cos(ea), cy + r * math.sin(ea)
            return (sx, sy), (ex, ey)
        return None, None

    def pts_close(p1: Tuple, p2: Tuple) -> bool:
        return abs(p1[0] - p2[0]) < TOL and abs(p1[1] - p2[1]) < TOL

    def follow_chain(start_pt: Tuple, remaining: List[Tuple[int, Dict]]) -> Tuple[List[Dict], Tuple]:
        chain: List[Dict] = []
        current_pt = start_pt
        while True:
            found = None
            found_idx = -1
            next_pt = None
            for ri, (_, entity) in enumerate(remaining):
                s, e = get_endpoints(entity)
                if s is None:
                    continue
                if pts_close(current_pt, s):
                    found = entity
                    found_idx = ri
                    next_pt = e
                    break
                elif pts_close(current_pt, e):
                    found = entity
                    found_idx = ri
                    next_pt = s
                    break
            if found is None:
                break
            chain.append(found)
            remaining.pop(found_idx)
            current_pt = next_pt
            if pts_close(current_pt, start_pt):
                break
        return chain, current_pt

    model_entities = [e for e in entities if e.get("type") in _SUPPORTED_CONTOUR_TYPES]

    for i, entity in enumerate(model_entities):
        if i in processed:
            continue
        etype = entity.get("type")
        if etype == "CIRCLE":
            contours.append([entity])
            processed.add(i)
            continue
        if etype == "LWPOLYLINE" and entity.get("closed", False):
            contours.append([entity])
            processed.add(i)
            continue

        start, end = get_endpoints(entity)
        if start is None:
            continue

        remaining = [(j, e) for j, e in enumerate(model_entities) if j != i and j not in processed]
        chain, final_pt = follow_chain(end, remaining)

        contour = [entity] + (chain or [])
        for j in range(len(model_entities)):
            for c in (chain or []):
                if c is model_entities[j]:
                    processed.add(j)

        if chain and pts_close(final_pt, start):
            contours.append(contour)
        elif chain:
            contours.append(contour)
        else:
            contours.append([entity])

        processed.add(i)

    logger.info(f"轮廓分组: {len(model_entities)} 个实体 -> {len(contours)} 个轮廓")
    return contours


def contour_edges_to_code(contour: List[Dict[str, Any]]) -> Optional[List[str]]:
    lines: List[str] = ["edges = []"]
    for entity in contour:
        etype = entity.get("type")
        if etype == "LWPOLYLINE":
            vertices = entity.get("vertices", [])
            if len(vertices) >= 2:
                for i in range(len(vertices)):
                    nxt = (i + 1) % len(vertices)
                    if not entity.get("closed") and i == len(vertices) - 1:
                        break
                    lines.append(
                        f"edges.append(Part.LineSegment("
                        f"App.Vector({vertices[i][0]}, {vertices[i][1]}, 0), "
                        f"App.Vector({vertices[nxt][0]}, {vertices[nxt][1]}, 0)).toShape())"
                    )
            else:
                return None
        elif etype in ("ELLIPSE", "SPLINE"):
            vertices = entity.get("vertices", [])
            if len(vertices) >= 2:
                for i in range(len(vertices) - 1):
                    lines.append(
                        f"edges.append(Part.LineSegment("
                        f"App.Vector({vertices[i][0]}, {vertices[i][1]}, 0), "
                        f"App.Vector({vertices[i+1][0]}, {vertices[i+1][1]}, 0)).toShape())"
                    )
                if entity.get("closed", False):
                    lines.append(
                        f"edges.append(Part.LineSegment("
                        f"App.Vector({vertices[-1][0]}, {vertices[-1][1]}, 0), "
                        f"App.Vector({vertices[0][0]}, {vertices[0][1]}, 0)).toShape())"
                    )
            else:
                return None
        elif etype == "LINE":
            x1, y1 = entity["start"][0], entity["start"][1]
            x2, y2 = entity["end"][0], entity["end"][1]
            lines.append(
                f"edges.append(Part.LineSegment("
                f"App.Vector({x1}, {y1}, 0), App.Vector({x2}, {y2}, 0)).toShape())"
            )
        elif etype == "CIRCLE":
            cx, cy = entity["center"][0], entity["center"][1]
            r = entity["radius"]
            lines.append(
                f"circle = Part.Circle(App.Vector({cx}, {cy}, 0), App.Vector(0, 0, 1), {r})"
            )
            lines.append("edges.append(circle.toShape())")
        elif etype == "ARC":
            cx, cy = entity["center"][0], entity["center"][1]
            r = entity["radius"]
            sa = entity.get("start_angle", 0) * math.pi / 180.0
            ea = entity.get("end_angle", 360) * math.pi / 180.0
            lines.append(
                f"circle = Part.Circle(App.Vector({cx}, {cy}, 0), App.Vector(0, 0, 1), {r})"
            )
            lines.append(f"arc = Part.ArcOfCircle(circle, {sa}, {ea})")
            lines.append("edges.append(arc.toShape())")
        else:
            return None
    return lines


def build_fallback_script(geometry_data: Dict[str, Any], extrude_height: float) -> str:
    entities = geometry_data.get("entities", [])
    contours = group_entities_into_contours(entities)

    script_lines = [
        "import FreeCAD as App",
        "import Part",
        "",
        "doc = App.newDocument('GeneratedModel')",
        "",
        f"extrude_height = {extrude_height}",
        "",
    ]

    total_solids = 0
    for ci, contour in enumerate(contours):
        edges_code = contour_edges_to_code(contour)
        if not edges_code:
            continue
        script_lines.append(f"# 轮廓 {ci+1} ({len(contour)} 个实体)")
        for line in edges_code:
            script_lines.append(line)
        script_lines.append(f"wire = Part.Wire(edges)")
        script_lines.append(f"if wire.isValid() and wire.isClosed():")
        script_lines.append(f"    face = Part.Face(wire)")
        script_lines.append(f"    solid = face.extrude(App.Vector(0, 0, extrude_height))")
        script_lines.append(f"    Part.show(solid, 'Solid_{ci+1}')")
        script_lines.append(f"else:")
        script_lines.append(f"    print('BRIDGE_WARNING: 轮廓 {ci+1} 未闭合, 跳过')")
        script_lines.append("")
        total_solids += 1

    if total_solids == 0:
        script_lines.append("print('BRIDGE_WARNING: 没有有效的闭合轮廓可建模')")

    script_lines.extend([
        "doc.recompute()",
        "",
        "doc.saveAs('model.FCStd')",
        "print('建模完成')",
        f"print('BRIDGE_FEATURE_COUNT:' + str(len(doc.Objects)))",
    ])

    return "\n".join(script_lines)
