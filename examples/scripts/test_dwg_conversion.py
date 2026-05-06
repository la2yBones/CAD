# -*- coding: utf-8 -*-
"""
DWG 文件转换和处理测试脚本
测试 LibreDWG 转换功能和 DWG 解析
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
from src.cad_parser import CADParser

def test_libredwg(config):
    """测试 LibreDWG 转换工具"""
    print("\n" + "="*60)
    print("1. 测试 LibreDWG 配置")
    print("="*60)
    
    libredwg_path = config.get("dxf_parser", {}).get("libredwg_path", "")
    converter_type = config.get("dxf_parser", {}).get("dwg_converter", "")
    
    print(f"   转换器类型: {converter_type}")
    print(f"   LibreDWG 路径: {libredwg_path}")
    
    libredwg_dir = Path(libredwg_path)
    if not libredwg_dir.exists():
        print(f"❌ 错误: LibreDWG 路径不存在: {libredwg_dir}")
        return False
    
    print(f"✓ LibreDWG 目录存在")
    
    # 查找 dwg2dxf
    dwg2dxf = None
    exe_names = ["dwg2dxf.exe", "dwg2dxf"]
    for exe_name in exe_names:
        candidate = libredwg_dir / exe_name
        if candidate.exists():
            dwg2dxf = candidate
            break
    
    if not dwg2dxf:
        # 在子目录中查找
        print("   在子目录中查找...")
        for p in libredwg_dir.rglob("*"):
            if p.name in exe_names and p.is_file():
                dwg2dxf = p
                break
    
    if dwg2dxf:
        print(f"✓ 找到转换器: {dwg2dxf}")
        
        # 测试运行
        try:
            import subprocess
            result = subprocess.run(
                [str(dwg2dxf), "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='ignore'
            )
            print(f"✓ 转换器运行正常 (返回码: {result.returncode})")
            return True
        except Exception as e:
            print(f"⚠️  无法测试转换器: {e}")
            return True
    else:
        print(f"❌ 未找到 dwg2dxf.exe 或 dwg2dxf")
        return False


def create_test_dwg_hint():
    """创建测试 DWG 文件提示"""
    print("\n" + "="*60)
    print("2. 测试说明")
    print("="*60)
    print("\n要测试 DWG 处理功能，请：")
    print("   1. 将您的 .dwg 或 .dxf 文件放入 examples/cad_files/ 目录")
    print("   2. 修改下方代码中的文件名")
    print("   3. 重新运行此脚本")


def test_dwg_parsing(config, dwg_filename=None):
    """测试 CAD 文件解析（支持 DWG 和 DXF）"""
    print("\n" + "="*60)
    print("3. CAD 文件解析测试")
    print("="*60)
    
    if not dwg_filename:
        # 查找 cad_files 目录中的文件
        cad_dir = project_root / "examples" / "cad_files"
        if cad_dir.exists():
            dwg_files = list(cad_dir.glob("*.dwg"))
            dxf_files = list(cad_dir.glob("*.dxf"))
            
            if dwg_files:
                print(f"✓ 找到 {len(dwg_files)} 个 DWG 文件")
                for f in dwg_files:
                    print(f"   - {f.name}")
                dwg_filename = str(dwg_files[0])
            elif dxf_files:
                print(f"⚠️  未找到 DWG 文件，但找到 {len(dxf_files)} 个 DXF 文件")
                print(f"   将使用 DXF 文件进行测试")
                dwg_filename = str(dxf_files[0])
            else:
                print("⚠️  未找到测试文件")
                return False
        else:
            print("⚠️  目录不存在")
            return False
    
    print(f"\n   使用文件: {Path(dwg_filename).name}")
    
    try:
        print(f"\n   正在解析文件...")
        parser = CADParser(dwg_filename, config.get("dxf_parser", {}))
        geometry_data = parser.parse()
        
        print(f"✓ 解析成功！")
        print(f"   图纸版本: {geometry_data.get('version', 'unknown')}")
        print(f"   图纸单位: {geometry_data.get('units', 'unknown')}")
        print(f"   实体数量: {len(geometry_data.get('entities', []))}")
        
        # 显示前几个实体
        entities = geometry_data.get('entities', [])
        if entities:
            print(f"\n   前 5 个实体:")
            for i, entity in enumerate(entities[:5]):
                etype = entity.get('type', 'unknown')
                layer = entity.get('layer', '0')
                print(f"     {i+1}. [{etype}] (layer: {layer})")
        
        # 导出 JSON
        output_dir = project_root / "examples" / "output"
        output_dir.mkdir(exist_ok=True)
        output_json = output_dir / "dwg_test_output.json"
        parser.export_json(str(output_json))
        print(f"\n✓ JSON 已导出: {output_json}")
        
        return True
        
    except Exception as e:
        print(f"❌ 解析失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "="*60)
    print("DWG 文件处理测试")
    print("="*60)
    
    # 加载配置
    config = load_config()
    
    # 1. 测试 LibreDWG
    libredwg_ok = test_libredwg(config)
    
    # 2. 提示说明
    create_test_dwg_hint()
    
    # 3. 测试文件解析
    parsing_ok = test_dwg_parsing(config)
    
    # 总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)
    print(f"   LibreDWG 配置: {'✓ OK' if libredwg_ok else '❌ 失败'}")
    print(f"   文件解析:      {'✓ OK' if parsing_ok else '❌ 失败'}")
    
    print("\n提示:")
    print("   - 将您的 DWG 或 DXF 文件放入 examples/cad_files/ 目录")
    print("   - 此脚本会自动检测并处理")
    print("   - 查看完整使用文档: docs/guides/getting_started.md")


if __name__ == "__main__":
    main()
