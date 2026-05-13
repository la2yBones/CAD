# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
测试 DeepSeek API 连接和基本功能
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config


def test_basic_api_call(config):
    """测试基本的 API 调用"""
    print("\n" + "=" * 50)
    print("测试 DeepSeek API 连接")
    print("=" * 50)
    
    api_config = config.get("api", {}).get("deepseek", {})
    api_key = api_config.get("api_key", "")
    
    if not api_key or api_key == "your-deepseek-api-key-here":
        print("❌ 请先配置 API 密钥")
        return False
    
    print(f"✓ API 密钥已配置: {api_key[:15]}...")
    
    try:
        from openai import OpenAI
        
        client = OpenAI(
            api_key=api_key,
            base_url=api_config.get("base_url", "https://api.deepseek.com")
        )
        
        print(f"✓ OpenAI 客户端创建成功")
        
        # 发送简单测试消息
        response = client.chat.completions.create(
            model=api_config.get("model", "deepseek-v4-pro"),
            messages=[
                {"role": "user", "content": "你好，请自我介绍一下"}
            ],
            max_tokens=200,
            extra_body={"thinking": {"type": "enabled", "reasoning_effort": api_config.get("reasoning_effort", "max")}} if api_config.get("thinking", True) else None,
        )
        
        print(f"✓ API 调用成功!")
        print(f"\nDeepSeek 回复:")
        print("-" * 50)
        print(response.choices[0].message.content)
        print("-" * 50)
        
        return True
        
    except Exception as e:
        print(f"❌ API 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_geometry_analysis(config):
    """测试智能几何分析功能"""
    print("\n" + "=" * 50)
    print("测试智能几何分析（视图识别 + 尺寸提取 + 建模指令）")
    print("=" * 50)
    
    try:
        from src.intelligent_analyzer import IntelligentEngineeringAnalyzer
        
        api_config = config.get("api", {}).get("deepseek", {})
        api_key = api_config.get("api_key", "")
        
        analyzer = IntelligentEngineeringAnalyzer(api_key, api_config, enable_cache=False)
        
        # 测试数据 - 简单几何图形
        test_data = {
            "entities": [
                {
                    "type": "CIRCLE",
                    "center": [0, 0, 0],
                    "radius": 10,
                    "layer": "0",
                    "color": 256
                },
                {
                    "type": "CIRCLE",
                    "center": [0, 0, 0],
                    "radius": 5,
                    "layer": "0",
                    "color": 256
                }
            ]
        }
        
        print(f"测试数据: 2个同心圆")
        print(f"  - 圆1: 中心(0,0), 半径10")
        print(f"  - 圆2: 中心(0,0), 半径5")
        
        result = analyzer.analyze_full(test_data)
        
        print(f"\n✓ 分析结果:")
        print("-" * 50)
        view_analysis = result.get("view_analysis", {})
        dim_extraction = result.get("dimension_extraction", {})
        modeling = result.get("modeling_instructions", {})
        print(f"视图识别: {len(view_analysis.get('views', []))} 个视图")
        print(f"尺寸提取: {dim_extraction.get('total', 0)} 个尺寸")
        print(f"建模策略: {modeling.get('modeling_strategy', '无')}")
        print(f"分析总结: {modeling.get('analysis_summary', '无')}")
        
        print("-" * 50)
        return True
        
    except Exception as e:
        print(f"❌ 智能分析测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "=" * 50)
    print("DeepSeek API 测试工具")
    print("=" * 50)
    
    # 加载配置
    config = load_config()
    print("\n✓ 配置加载成功")
    
    results = {}
    
    # 测试基本 API 调用
    results["basic_api"] = test_basic_api_call(config)
    
    # 测试几何分析
    if results["basic_api"]:
        results["geometry_analysis"] = test_geometry_analysis(config)
    
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
    
    print("\n测试完成!")


if __name__ == "__main__":
    main()
