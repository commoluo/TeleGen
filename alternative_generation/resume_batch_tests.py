#!/usr/bin/env python3
"""
继续批量测试脚本
Resume Batch Testing
"""

import os
import sys
import subprocess
from pathlib import Path

def main():
    """主函数"""
    # 切换到脚本所在目录
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    print("🚀 继续批量测试...")
    print("=" * 50)
    
    # 检查进度文件
    progress_file = Path("/tmp/sequential_logs/progress.json")
    start_index = 1
    
    if progress_file.exists():
        import json
        try:
            with open(progress_file, 'r') as f:
                progress = json.load(f)
            start_index = progress.get('current_index', 1) + 1
            print(f"📍 从项目 {start_index} 继续...")
        except:
            print("⚠️  无法读取进度文件，从第1个项目开始")
    
    # 确认继续
    try:
        response = input(f"\n从项目 {start_index} 开始继续测试？(y/N): ").strip().lower()
        if response not in ['y', 'yes']:
            print("取消测试")
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n取消测试")
        sys.exit(0)
    
    # 运行批量测试，传递起始索引
    print(f"\n🎯 从项目 {start_index} 继续批量测试...")
    try:
        result = subprocess.run([
            sys.executable, 
            "sequential_project_manager.py",
            "--start", str(start_index)
        ], check=True)
        
        print("\n✅ 批量测试完成！")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 批量测试失败: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 测试被用户中断")
        sys.exit(0)

if __name__ == "__main__":
    main()
