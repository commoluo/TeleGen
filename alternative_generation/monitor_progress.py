#!/usr/bin/env python3
"""
监控WebVoyager批量测试进度
"""

import os
import time
from pathlib import Path

def monitor_results():
    """监控测试结果目录"""
    webvoyager_results = Path("../webvoyager/webvoyager_results")
    
    if not webvoyager_results.exists():
        print("❌ 结果目录不存在")
        return
    
    while True:
        # 获取所有结果目录
        result_dirs = [d for d in webvoyager_results.iterdir() if d.is_dir()]
        
        print(f"\n🔍 当前测试进度: {len(result_dirs)} 个项目已完成测试")
        print("=" * 60)
        
        # 按项目编号排序显示
        sorted_dirs = sorted(result_dirs, key=lambda x: x.name)
        
        for result_dir in sorted_dirs[-10:]:  # 只显示最近10个
            project_name = result_dir.name
            tasks = [d for d in result_dir.iterdir() if d.is_dir()]
            print(f"✅ {project_name}: {len(tasks)} 个任务")
        
        if len(sorted_dirs) > 10:
            print(f"... 和其他 {len(sorted_dirs) - 10} 个已完成的项目")
        
        print("=" * 60)
        print("按 Ctrl+C 退出监控")
        
        time.sleep(30)  # 每30秒检查一次

if __name__ == "__main__":
    try:
        monitor_results()
    except KeyboardInterrupt:
        print("\n👋 监控已停止")
