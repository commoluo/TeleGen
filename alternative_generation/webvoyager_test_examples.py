#!/usr/bin/env python3
"""
WebVoyager改进测试的使用示例
"""

import os
import sys
from improved_webvoyager_test import RateLimitedWebVoyagerTester
from webvoyager_config import PRESET_CONFIGS, RATE_LIMIT_CONFIG

def run_conservative_test():
    """运行保守模式测试"""
    print("=== 保守模式测试 ===")
    config = PRESET_CONFIGS['conservative']
    
    tester = RateLimitedWebVoyagerTester(
        test_file='data/test.jsonl',
        max_concurrent_tasks=config['max_concurrent_tasks'],
        delay_between_tasks=config['delay_between_tasks'],
        max_retries=config['max_retries'],
        retry_delay=config['retry_delay']
    )
    
    # 仅测试前3个任务
    tasks = tester.load_tasks()[:3]
    print(f"将测试 {len(tasks)} 个任务")
    
    tester.run_all_tasks(tasks)

def run_balanced_test():
    """运行平衡模式测试"""
    print("=== 平衡模式测试 ===")
    config = PRESET_CONFIGS['balanced']
    
    tester = RateLimitedWebVoyagerTester(
        test_file='data/test.jsonl',
        max_concurrent_tasks=config['max_concurrent_tasks'],
        delay_between_tasks=config['delay_between_tasks'],
        max_retries=config['max_retries'],
        retry_delay=config['retry_delay']
    )
    
    # 测试前5个任务
    tasks = tester.load_tasks()[:5]
    print(f"将测试 {len(tasks)} 个任务")
    
    tester.run_all_tasks(tasks)

def run_single_task_test():
    """运行单任务测试"""
    print("=== 单任务测试 ===")
    
    tester = RateLimitedWebVoyagerTester(
        test_file='data/test.jsonl',
        max_concurrent_tasks=1,
        delay_between_tasks=0,  # 单任务不需要延迟
        max_retries=3,
        retry_delay=60.0
    )
    
    # 仅测试第一个任务
    tasks = tester.load_tasks()[:1]
    print(f"将测试 {len(tasks)} 个任务")
    
    tester.run_all_tasks(tasks)

def show_configurations():
    """显示所有可用配置"""
    print("\n可用的预设配置:")
    print("=" * 60)
    
    for name, config in PRESET_CONFIGS.items():
        print(f"\n{name.upper()}:")
        print(f"  描述: {config['description']}")
        print(f"  最大并发: {config['max_concurrent_tasks']}")
        print(f"  任务间延迟: {config['delay_between_tasks']}秒")
        print(f"  最大重试: {config['max_retries']}")
        print(f"  重试延迟: {config['retry_delay']}秒")

def main():
    """主函数"""
    if not os.getenv('OPENAI_API_KEY'):
        print("错误: 请设置 OPENAI_API_KEY 环境变量")
        print("例如: export OPENAI_API_KEY='your-api-key-here'")
        sys.exit(1)
    
    print("WebVoyager改进测试工具")
    print("=" * 40)
    
    while True:
        print("\n请选择测试模式:")
        print("1. 单任务测试（最安全）")
        print("2. 保守模式测试（3个任务）")
        print("3. 平衡模式测试（5个任务）")
        print("4. 查看配置说明")
        print("5. 退出")
        
        choice = input("\n请输入选择 (1-5): ").strip()
        
        try:
            if choice == '1':
                run_single_task_test()
            elif choice == '2':
                run_conservative_test()
            elif choice == '3':
                run_balanced_test()
            elif choice == '4':
                show_configurations()
            elif choice == '5':
                print("退出测试工具")
                break
            else:
                print("无效选择，请重新输入")
                
        except KeyboardInterrupt:
            print("\n测试被用户中断")
            break
        except Exception as e:
            print(f"测试过程中发生错误: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
