#!/usr/bin/env python3
"""
WebVoyager批量测试最终综合报告
"""

import os
import json
from pathlib import Path

def generate_final_report():
    """生成最终综合报告"""
    results_dir = "/Users/luoyujia/Downloads/WebGen-Bench-main/webvoyager/webvoyager_results"
    
    print("🎯 WebVoyager批量测试最终综合报告")
    print("="*80)
    
    # 1. 项目覆盖情况
    print("\n📊 项目覆盖情况:")
    print("-" * 50)
    
    completed_projects = [d for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))]
    completed_count = len(completed_projects)
    
    # 应测试的项目总数 (002-100, 跳过001_simple_stock_report_restructured)
    expected_projects = 99
    coverage_rate = (completed_count / expected_projects * 100)
    
    print(f"✅ 已完成测试: {completed_count}/{expected_projects} 个项目")
    print(f"📈 项目覆盖率: {coverage_rate:.1f}%")
    
    # 找出缺失项目
    missing_projects = []
    for i in range(2, 101):
        project_name = f"{i:03d}_simple_project_restructured"
        if project_name not in completed_projects:
            missing_projects.append(project_name)
    
    if missing_projects:
        print(f"\n❌ 缺失项目 ({len(missing_projects)}个):")
        for project in missing_projects:
            print(f"   - {project}")
    
    # 2. 任务执行统计
    print(f"\n📋 任务执行统计:")
    print("-" * 50)
    
    total_tasks = 0
    task_stats = {"YES": 0, "NO": 0, "PARTIAL": 0, "ANSWER": 0, "UNKNOWN": 0}
    
    for project in completed_projects:
        project_dir = os.path.join(results_dir, project)
        tasks = [d for d in os.listdir(project_dir) if os.path.isdir(os.path.join(project_dir, d))]
        total_tasks += len(tasks)
        
        for task in tasks:
            task_dir = os.path.join(project_dir, task)
            messages_file = os.path.join(task_dir, "interact_messages.json")
            
            if os.path.exists(messages_file):
                try:
                    with open(messages_file, 'r', encoding='utf-8') as f:
                        messages = json.load(f)
                    
                    if messages:
                        last_message = messages[-1]
                        content = last_message.get('content', '').strip().upper()
                        
                        if content == "YES":
                            task_stats["YES"] += 1
                        elif content == "NO":
                            task_stats["NO"] += 1
                        elif content == "PARTIAL":
                            task_stats["PARTIAL"] += 1
                        elif "ANSWER" in content:
                            task_stats["ANSWER"] += 1
                        else:
                            task_stats["UNKNOWN"] += 1
                    else:
                        task_stats["UNKNOWN"] += 1
                except:
                    task_stats["UNKNOWN"] += 1
            else:
                task_stats["UNKNOWN"] += 1
    
    print(f"总任务数: {total_tasks}")
    print(f"预期任务数: {completed_count * 3} (每项目3个任务)")
    task_completion_rate = (total_tasks / (completed_count * 3) * 100) if completed_count > 0 else 0
    print(f"任务完成率: {task_completion_rate:.1f}%")
    
    # 3. 评估结果分析
    print(f"\n🎯 评估结果分析:")
    print("-" * 50)
    
    for eval_type, count in task_stats.items():
        percentage = (count / total_tasks * 100) if total_tasks > 0 else 0
        emoji = {"YES": "✅", "NO": "❌", "PARTIAL": "⚡", "ANSWER": "📝", "UNKNOWN": "❓"}
        print(f"{emoji[eval_type]} {eval_type}: {count} ({percentage:.1f}%)")
    
    # 4. 核心指标
    print(f"\n🏆 核心性能指标:")
    print("-" * 50)
    
    success_rate = (task_stats["YES"] / total_tasks * 100) if total_tasks > 0 else 0
    partial_success_rate = ((task_stats["YES"] + task_stats["PARTIAL"]) / total_tasks * 100) if total_tasks > 0 else 0
    failure_rate = (task_stats["NO"] / total_tasks * 100) if total_tasks > 0 else 0
    
    print(f"🎯 完全成功率: {success_rate:.1f}%")
    print(f"⚡ 部分以上成功率: {partial_success_rate:.1f}%")
    print(f"❌ 明确失败率: {failure_rate:.1f}%")
    print(f"❓ 未知状态率: {task_stats['UNKNOWN']/total_tasks*100:.1f}%" if total_tasks > 0 else "❓ 未知状态率: 0%")
    
    # 5. 系统表现总结
    print(f"\n📝 系统表现总结:")
    print("-" * 50)
    
    if success_rate == 0:
        performance_level = "需要改进"
        performance_desc = "没有项目完全成功，生成的网站在UI自动化测试中表现不佳"
    elif success_rate < 10:
        performance_level = "初级水平"
        performance_desc = "少数项目表现良好，大部分需要优化"
    elif success_rate < 30:
        performance_level = "中等水平"
        performance_desc = "部分项目表现良好，仍有较大改进空间"
    elif success_rate < 70:
        performance_level = "良好水平"
        performance_desc = "多数项目表现良好，达到基本可用标准"
    else:
        performance_level = "优秀水平"
        performance_desc = "大部分项目表现优秀，达到高质量标准"
    
    print(f"🏅 总体评级: {performance_level}")
    print(f"📖 表现描述: {performance_desc}")
    
    # 6. 改进建议
    print(f"\n💡 改进建议:")
    print("-" * 50)
    
    suggestions = []
    
    if task_stats["UNKNOWN"] > total_tasks * 0.3:
        suggestions.append("优化测试稳定性，减少未知状态的任务")
    
    if task_stats["NO"] > total_tasks * 0.2:
        suggestions.append("改进生成的网站质量，减少明确失败的情况")
    
    if coverage_rate < 95:
        suggestions.append("完成剩余项目的测试，提高测试覆盖率")
    
    if success_rate < 10:
        suggestions.append("重点改进网站的基础功能实现")
        suggestions.append("加强登录、导航、交互等核心功能的生成质量")
    
    if len(suggestions) == 0:
        suggestions.append("继续保持当前质量水平")
    
    for i, suggestion in enumerate(suggestions, 1):
        print(f"{i}. {suggestion}")
    
    print(f"\n" + "="*80)
    print("📊 报告生成完成")

if __name__ == "__main__":
    generate_final_report()
