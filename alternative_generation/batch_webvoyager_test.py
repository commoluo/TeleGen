#!/usr/bin/env python3
"""
批量测试 WebVoyager 项目
Batch test WebVoyager projects
"""

import os
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime

def test_single_project(project_name, port=3000, max_retries=3):
    """测试单个项目"""
    print(f"\n🧪 测试项目: {project_name}")
    print(f"   端口: {port}")
    print("-" * 50)
    
    for attempt in range(max_retries):
        try:
            # 构建测试命令
            cmd = [
                "python", "test_single_project.py", 
                project_name, str(port)
            ]
            
            # 运行测试
            result = subprocess.run(
                cmd,
                cwd="/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation",
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )
            
            if result.returncode == 0:
                print(f"✅ 项目 {project_name} 测试成功")
                return True
            else:
                print(f"❌ 项目 {project_name} 测试失败 (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    print(f"   等待 5 秒后重试...")
                    time.sleep(5)
                else:
                    print(f"   STDOUT: {result.stdout}")
                    print(f"   STDERR: {result.stderr}")
                    
        except subprocess.TimeoutExpired:
            print(f"⏰ 项目 {project_name} 测试超时 (尝试 {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                print(f"   等待 5 秒后重试...")
                time.sleep(5)
        except Exception as e:
            print(f"❌ 项目 {project_name} 测试异常: {str(e)}")
            if attempt < max_retries - 1:
                print(f"   等待 5 秒后重试...")
                time.sleep(5)
    
    return False

def batch_test_projects(projects_dir, start_from=1, limit=None):
    """批量测试项目"""
    print("🚀 开始批量测试 WebVoyager 项目")
    print(f"项目目录: {projects_dir}")
    print(f"开始位置: {start_from}")
    print(f"测试限制: {limit if limit else '无限制'}")
    print("=" * 60)
    
    # 检查项目目录
    if not os.path.exists(projects_dir):
        print(f"❌ 项目目录不存在: {projects_dir}")
        return
    
    # 获取所有重构项目
    projects = []
    for item in os.listdir(projects_dir):
        if item.endswith("_simple_project_restructured"):
            projects.append(item)
    
    projects.sort()
    
    # 应用开始位置和限制
    if start_from > 1:
        projects = projects[start_from-1:]
    
    if limit:
        projects = projects[:limit]
    
    print(f"📋 找到 {len(projects)} 个项目需要测试")
    
    # 开始测试
    successful_count = 0
    failed_count = 0
    base_port = 3000
    
    start_time = time.time()
    
    for i, project in enumerate(projects):
        print(f"\n[{i+1}/{len(projects)}] 测试项目: {project}")
        
        # 使用不同端口避免冲突
        port = base_port + i
        
        if test_single_project(project, port):
            successful_count += 1
        else:
            failed_count += 1
        
        # 添加间隔避免资源冲突
        if i < len(projects) - 1:
            print("⏳ 等待 3 秒...")
            time.sleep(3)
    
    # 生成报告
    end_time = time.time()
    total_time = end_time - start_time
    
    print("\n" + "=" * 60)
    print("🎉 批量测试完成!")
    print(f"📊 统计结果:")
    print(f"   ✅ 成功: {successful_count} 个项目")
    print(f"   ❌ 失败: {failed_count} 个项目")
    print(f"   📈 成功率: {successful_count/(successful_count+failed_count)*100:.1f}%")
    print(f"   ⏱️  总耗时: {total_time/60:.1f} 分钟")
    
    # 检查结果目录
    results_dir = "/Users/luoyujia/Downloads/WebGen-Bench-main/webvoyager/webvoyager_results"
    if os.path.exists(results_dir):
        result_folders = [f for f in os.listdir(results_dir) if f.endswith("_simple_project_restructured")]
        print(f"   📁 测试结果: {len(result_folders)} 个项目的结果已保存")
        print(f"   📂 结果位置: {results_dir}")

def main():
    """主函数"""
    projects_dir = "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/generated_websites/fullstack_projects_20250717_174459"
    
    print("🔬 WebVoyager 批量测试工具")
    print("=" * 60)
    
    # 获取测试参数
    start_input = input("开始测试项目编号 (默认: 1): ").strip()
    start_from = 1
    if start_input.isdigit():
        start_from = int(start_input)
    
    limit_input = input("测试项目数量限制 (留空测试全部): ").strip()
    limit = None
    if limit_input.isdigit():
        limit = int(limit_input)
    
    # 确认测试
    print(f"\n⚠️  即将开始测试:")
    print(f"   📁 项目目录: {projects_dir}")
    print(f"   🏁 开始位置: 第 {start_from} 个项目")
    print(f"   🔢 测试数量: {limit if limit else '全部'}")
    print(f"   ⏱️  预计耗时: 约 {(limit or 101) * 2} 分钟")
    
    confirm = input(f"\n确认开始测试? (y/N): ").strip().lower()
    if confirm != 'y':
        print("测试已取消")
        return
    
    # 开始批量测试
    batch_test_projects(projects_dir, start_from, limit)

if __name__ == "__main__":
    main()
