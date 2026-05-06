# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
测试配置和依赖是否正确
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config


def test_libredwg(libredwg_path: str) -> bool:
    """测试LibreDWG是否可用"""
    print("\n" + "=" * 50)
    print("测试 LibreDWG 配置")
    print("=" * 50)
    
    libredwg_dir = Path(libredwg_path)
    if not libredwg_dir.exists():
        print(f"❌ LibreDWG路径不存在: {libredwg_dir}")
        return False
    
    print(f"✓ LibreDWG目录存在: {libredwg_dir}")
    
    # 查找 dwg2dxf.exe
    dwg2dxf = libredwg_dir / "dwg2dxf.exe"
    if not dwg2dxf.exists():
        # 尝试在子目录中查找
        found = False
        for p in libredwg_dir.rglob("dwg2dxf.exe"):
            dwg2dxf = p
            found = True
            break
        if not found:
            print("❌ 未找到 dwg2dxf.exe")
            return False
    
    print(f"✓ 找到 dwg2dxf.exe: {dwg2dxf}")
    
    # 测试运行
    try:
        import subprocess
        result = subprocess.run(
            [str(dwg2dxf), "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode in [0, 1]:  # --help 返回1是正常的
            print("✓ LibreDWG 可用")
            return True
        else:
            print(f"❌ LibreDWG 测试失败 (退出码: {result.returncode})")
            return False
    except Exception as e:
        print(f"❌ LibreDWG 测试出错: {e}")
        return False


def test_freecad(freecad_bin_path: str) -> bool:
    """测试FreeCAD是否可用"""
    print("\n" + "=" * 50)
    print("测试 FreeCAD 配置")
    print("=" * 50)
    
    freecad_dir = Path(freecad_bin_path)
    if not freecad_dir.exists():
        print(f"❌ FreeCAD路径不存在: {freecad_dir}")
        return False
    
    print(f"✓ FreeCAD目录存在: {freecad_dir}")
    
    # 添加路径到系统
    sys.path.insert(0, str(freecad_dir))
    import os
    if str(freecad_dir) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(freecad_dir) + os.pathsep + os.environ.get("PATH", "")
    
    # 尝试导入
    try:
        import FreeCAD as App
        import Part
        print("✓ FreeCAD 导入成功")
        print(f"  - FreeCAD版本: {App.Version()}")
        return True
    except ImportError as e:
        print(f"❌ FreeCAD 导入失败: {e}")
        print("  提示: 请检查FreeCAD安装路径是否正确")
        return False


def test_ezdxf() -> bool:
    """测试ezdxf是否可用"""
    print("\n" + "=" * 50)
    print("测试 ezdxf 库")
    print("=" * 50)
    
    try:
        import ezdxf
        print(f"✓ ezdxf 导入成功")
        print(f"  - ezdxf版本: {ezdxf.__version__}")
        return True
    except ImportError as e:
        print(f"❌ ezdxf 导入失败: {e}")
        return False


def main():
    print("\n" + "=" * 50)
    print("CAD建模系统 - 配置测试")
    print("=" * 50)
    
    # 加载配置
    config = load_config()
    print("\n✓ 配置加载成功")
    
    results = {}
    
    # 测试 ezdxf
    results["ezdxf"] = test_ezdxf()
    
    # 测试 LibreDWG
    libredwg_path = config.get("dxf_parser", {}).get("libredwg_path", "")
    if libredwg_path:
        results["libredwg"] = test_libredwg(libredwg_path)
    else:
        print("\n⚠️  未配置LibreDWG路径，跳过测试")
        results["libredwg"] = None
    
    # 测试 FreeCAD
    freecad_path = config.get("freecad", {}).get("bin_path", "")
    if freecad_path:
        results["freecad"] = test_freecad(freecad_path)
    else:
        print("\n⚠️  未配置FreeCAD路径，跳过测试")
        results["freecad"] = None
    
    # 总结
    print("\n" + "=" * 50)
    print("测试总结")
    print("=" * 50)
    
    for name, result in results.items():
        if result is True:
            print(f"✓ {name}: 通过")
        elif result is False:
            print(f"✗ {name}: 失败")
        else:
            print(f"- {name}: 跳过")
    
    # 如果有失败项，给出建议
    if any(v is False for v in results.values()):
        print("\n⚠️  存在失败项，请检查:")
        print("  1. 确认所有依赖已安装: pip install -r requirements.txt")
        print("  2. 检查 config/config.yaml 中的路径配置")
        print("  3. 确认 LibreDWG 和 FreeCAD 已正确安装")
    
    print("\n测试完成!")


if __name__ == "__main__":
    main()
