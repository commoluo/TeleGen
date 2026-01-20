#!/usr/bin/env python3
"""
批量重构最近生成的项目
Batch restructure recently generated projects
"""

import os
import sys
from pathlib import Path
from project_restructurer import ProjectRestructurer
import argparse

def batch_restructure_projects(projects_base_dir: str, suffix: str = None):
    """批量重构项目"""
    
    if not os.path.exists(projects_base_dir):
        print(f"❌ 项目目录不存在: {projects_base_dir}")
        return
    
    print(f"🔄 开始批量重构项目")
    print(f"项目目录: {projects_base_dir}")
    print("=" * 60)
    
    # 获取所有项目目录（支持多种格式）
    all_dirs = [d for d in os.listdir(projects_base_dir) 
                if os.path.isdir(os.path.join(projects_base_dir, d))]

    # 排除已经重构过的目录（例如包含 frontend/ 的目录）
    skipped_dirs = []
    filtered_dirs = []
    for directory in all_dirs:
        project_path = os.path.join(projects_base_dir, directory)
        if os.path.isdir(os.path.join(project_path, "frontend")):
            skipped_dirs.append(directory)
            continue
        filtered_dirs.append(directory)
    if skipped_dirs:
        print(f"🚫 检测到 {len(skipped_dirs)} 个已重构目录，已跳过:")
        for skipped in sorted(skipped_dirs):
            print(f"   • {skipped}")
    all_dirs = filtered_dirs
    
    if suffix and suffix.lower() != 'none':
        projects = [d for d in all_dirs if d.endswith(suffix)]
        print(f"🔍 已应用后缀过滤: '{suffix}'")
    else:
        projects = all_dirs
        print("🔍 未应用后缀过滤，处理所有目录。")

    projects.sort()
    
    if not projects:
        print("❌ 没有找到需要重构的项目")
        return
    
    print(f"📋 找到 {len(projects)} 个项目需要重构")
    
    successful_count = 0
    failed_count = 0
    results = []
    
    for i, project in enumerate(projects, 1):
        project_path = os.path.join(projects_base_dir, project)
        print(f"\n[{i}/{len(projects)}] 重构项目: {project}")
        print("-" * 40)
        
        try:
            # 创建重构器 - 支持新的organized项目结构
            restructurer = ProjectRestructurer(project_path)
            
            # 如果是organized_optimized_code中的项目，需要特殊处理
            if 'organized_optimized_code' in project_path:
                restructurer.is_organized_project = True
            
            # 执行重构
            success = restructurer.restructure_project()
            
            if success:
                successful_count += 1
                restructured_path = restructurer.restructured_path
                print(f"✅ 重构成功: {restructured_path}")
                results.append({
                    'project': project,
                    'success': True,
                    'restructured_path': restructured_path
                })
            else:
                failed_count += 1
                print(f"❌ 重构失败")
                results.append({
                    'project': project,
                    'success': False,
                    'error': 'Restructure failed'
                })
                
        except Exception as e:
            failed_count += 1
            print(f"❌ 重构异常: {e}")
            results.append({
                'project': project,
                'success': False,
                'error': str(e)
            })
    
    # 显示最终统计
    print(f"\n🎉 批量重构完成!")
    print("=" * 60)
    print(f"📊 统计结果:")
    print(f"   ✅ 成功: {successful_count}")
    print(f"   ❌ 失败: {failed_count}")
    print(f"   📈 成功率: {successful_count/(successful_count+failed_count)*100:.1f}%")
    
    # 显示成功的项目路径
    successful_projects = [r for r in results if r['success']]
    if successful_projects:
        print(f"\n📁 重构成功的项目:")
        for result in successful_projects:
            print(f"   • {result['project']} -> {result['restructured_path']}")
    
    return results

def main():
    """主函数"""
    print("🔧 WebGen-Bench 项目批量重构器")
    print("=" * 60)
    
    # 默认项目目录 - 更新为organized_optimized_code
    default_projects_dir = "organized_optimized_code"
    
    # 获取用户输入
    projects_dir = input(f"项目目录 (默认: {default_projects_dir}): ").strip()
    if not projects_dir:
        projects_dir = default_projects_dir
    
    if not os.path.exists(projects_dir):
        print(f"❌ 目录不存在: {projects_dir}")
        return
    
    # 确认操作
    print(f"\n⚠️  将重构目录中的所有项目:")
    print(f"   目录: {projects_dir}")
    
    confirm = input(f"\n确认继续? (y/N): ").strip().lower()
    if confirm != 'y':
        print("操作已取消")
        return
    
    # 开始批量重构
    batch_restructure_projects(projects_dir)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="批量重构 WebGen-Bench 项目")
    
    script_dir = Path(__file__).parent.resolve()
    default_projects_dir = script_dir / "debug_logged_projects"
    
    parser.add_argument(
        "projects_dir", 
        nargs='?', 
        default=str(default_projects_dir), 
        help=f"包含项目的目录路径 (默认: {default_projects_dir})"
    )
    parser.add_argument(
        "--suffix", 
        type=str, 
        default=None, 
        help="用于过滤项目目录的后缀 (例如, '_optimized')。如果为 'none' 或不提供, 则不进行过滤。"
    )

    args = parser.parse_args()

    projects_dir = Path(args.projects_dir).resolve()

    # 确保路径存在
    if not os.path.isdir(projects_dir):
        print(f"❌ 错误: 目录 '{projects_dir}' 不存在。")
        print("请确认该目录是否已正确创建。")
        sys.exit(1)
        
    batch_restructure_projects(str(projects_dir), args.suffix)

if __name__ == "__main__":
    main()
