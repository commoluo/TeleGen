#!/usr/bin/env python3
"""
验证改进的WebVoyager测试工具是否正常工作
"""

import sys
import os
import json
from pathlib import Path

def test_import():
    """测试导入"""
    try:
        from improved_webvoyager_test import RateLimitedWebVoyagerTester
        from webvoyager_config import PRESET_CONFIGS, RATE_LIMIT_CONFIG
        print("✅ 所有模块导入成功")
        return True
    except ImportError as e:
        print(f"❌ 模块导入失败: {e}")
        return False

def test_config():
    """测试配置"""
    try:
        from webvoyager_config import PRESET_CONFIGS
        
        required_configs = ['conservative', 'balanced', 'aggressive', 'testing']
        for config_name in required_configs:
            if config_name not in PRESET_CONFIGS:
                print(f"❌ 缺少配置: {config_name}")
                return False
        
        print("✅ 所有配置检查通过")
        return True
    except Exception as e:
        print(f"❌ 配置检查失败: {e}")
        return False

def test_test_file():
    """测试测试文件是否存在"""
    test_file = Path("../data/test.jsonl")
    if not test_file.exists():
        print(f"❌ 测试文件不存在: {test_file}")
        return False
    
    try:
        with open(test_file, 'r') as f:
            lines = f.readlines()
            if len(lines) == 0:
                print("❌ 测试文件为空")
                return False
            
            # 验证第一行是否为有效JSON
            first_task = json.loads(lines[0])
            if 'id' not in first_task:
                print("❌ 测试文件格式错误：缺少id字段")
                return False
        
        print(f"✅ 测试文件检查通过 ({len(lines)} 个任务)")
        return True
    except Exception as e:
        print(f"❌ 测试文件检查失败: {e}")
        return False

def test_api_key():
    """测试API密钥"""
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("❌ OPENAI_API_KEY 环境变量未设置")
        return False
    
    if api_key == 'key' or len(api_key) < 10:
        print("❌ OPENAI_API_KEY 似乎无效")
        return False
    
    print("✅ API密钥检查通过")
    return True

def test_tester_creation():
    """测试测试器创建"""
    try:
        from improved_webvoyager_test import RateLimitedWebVoyagerTester
        
        tester = RateLimitedWebVoyagerTester(
            test_file="../data/test.jsonl",
            max_concurrent_tasks=1,
            delay_between_tasks=10.0,
            max_retries=1,
            retry_delay=30.0
        )
        
        print("✅ 测试器创建成功")
        return True
    except Exception as e:
        print(f"❌ 测试器创建失败: {e}")
        return False

def test_task_loading():
    """测试任务加载"""
    try:
        from improved_webvoyager_test import RateLimitedWebVoyagerTester
        
        tester = RateLimitedWebVoyagerTester(
            test_file="../data/test.jsonl",
            max_concurrent_tasks=1,
            delay_between_tasks=10.0,
            max_retries=1,
            retry_delay=30.0
        )
        
        tasks = tester.load_tasks()
        if not tasks:
            print("❌ 未加载到任务")
            return False
        
        print(f"✅ 任务加载成功 ({len(tasks)} 个任务)")
        return True
    except Exception as e:
        print(f"❌ 任务加载失败: {e}")
        return False

def main():
    """主函数"""
    print("WebVoyager改进测试工具验证")
    print("=" * 50)
    
    tests = [
        ("导入测试", test_import),
        ("配置测试", test_config),
        ("测试文件检查", test_test_file),
        ("API密钥检查", test_api_key),
        ("测试器创建", test_tester_creation),
        ("任务加载测试", test_task_loading),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        if test_func():
            passed += 1
        else:
            failed += 1
    
    print("\n" + "=" * 50)
    print(f"验证完成: {passed} 通过, {failed} 失败")
    
    if failed == 0:
        print("🎉 所有测试都通过！可以开始使用改进的测试工具了。")
        print("\n建议的下一步:")
        print("1. 运行单任务测试: python improved_webvoyager_test.py --limit 1")
        print("2. 运行交互式测试: python webvoyager_test_examples.py")
        print("3. 查看详细指南: cat WEBVOYAGER_IMPROVED_TESTING_GUIDE.md")
    else:
        print("❌ 有些测试失败了，请检查上面的错误信息。")
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
