#!/usr/bin/env python3
"""
批量测试启动脚本
Batch Test Launcher
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
    
    print("🚀 开始批量测试100个全栈项目...")
    print("=" * 50)
    
    # 检查sequential_project_manager.py是否存在
    manager_script = script_dir / "sequential_project_manager.py"
    if not manager_script.exists():
        print("❌ sequential_project_manager.py 不存在")
        sys.exit(1)
    
    # 检查项目目录是否存在
    projects_dir = script_dir / "generated_websites" / "fullstack_projects"
    if not projects_dir.exists():
        print("❌ 项目目录不存在")
        sys.exit(1)
    
    # 统计项目数量
    project_count = len([p for p in projects_dir.iterdir() 
                        if p.is_dir() and p.name.endswith("_simple_project_restructured")])
    
    print(f"📊 发现 {project_count} 个项目")
    
    if project_count == 0:
        print("❌ 没有找到可测试的项目")
        sys.exit(1)
    
    # 提示用户
    print("\n⚠️  注意：批量测试可能需要很长时间")
    print("   - 每个项目包含：依赖安装、启动、测试、关闭")
    print("   - 预计总时间：2-5分钟/项目")
    print("   - 可以随时按 Ctrl+C 中断")
    
    # 确认继续
    try:
        response = input("\n是否继续？(y/N): ").strip().lower()
        if response not in ['y', 'yes']:
            print("取消测试")
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n取消测试")
        sys.exit(0)
    
    # 运行批量测试
    print("\n🎯 启动批量测试...")
    try:
        result = subprocess.run([
            sys.executable, 
            str(manager_script)
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
