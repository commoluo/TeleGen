#!/usr/bin/env python3
"""
分析WebVoyager测试结果
使用方法: python analyze_results.py [结果目录路径]
"""

import os
import json
import sys
from pathlib import Path

def analyze_test_results(results_dir):
    """分析测试结果"""
    
    if not os.path.exists(results_dir):
        print(f"❌ 结果目录不存在: {results_dir}")
        return
    
    print(f"📊 分析WebVoyager测试结果")
    print(f"结果目录: {results_dir}")
    print("="*60)
    
    # 获取所有项目
    projects = [d for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))]
    projects.sort()
    
    if not projects:
        print("❌ 没有找到测试结果")
        return
    
    total_tasks = 0
    successful_tasks = 0
    partial_tasks = 0
    failed_tasks = 0
    
    for project in projects:
        print(f"\n🔍 项目: {project}")
        print("-" * 40)
        
        project_dir = os.path.join(results_dir, project)
        tasks = [d for d in os.listdir(project_dir) if os.path.isdir(os.path.join(project_dir, d))]
        
        project_success = 0
        project_partial = 0
        project_total = len(tasks)
        total_tasks += project_total
        
        for task in tasks:
            task_dir = os.path.join(project_dir, task)
            
            # 检查是否有interact_messages.json
            messages_file = os.path.join(task_dir, "interact_messages.json")
            agent_log = os.path.join(task_dir, "agent.log")
            
            task_status = "❓"
            task_result = "未知"
            
            if os.path.exists(messages_file):
                try:
                    with open(messages_file, 'r', encoding='utf-8') as f:
                        messages = json.load(f)
                    
                    if messages:
                        # 检查最后的消息是否包含ANSWER或完成标志
                        last_message = messages[-1] if messages else {}
                        assistant_content = last_message.get('content', '')
                        
                        # 处理content可能是列表的情况
                        if isinstance(assistant_content, list):
                            text_parts = []
                            for item in assistant_content:
                                if isinstance(item, dict) and 'text' in item:
                                    text_parts.append(item['text'])
                                elif isinstance(item, str):
                                    text_parts.append(item)
                            assistant_content = ' '.join(text_parts)
                        
                        content_upper = assistant_content.upper()
                        
                        if 'ANSWER' in content_upper or '任务完成' in assistant_content:
                            # 检查具体的答案类型
                            if 'YES' in content_upper:
                                task_status = "✅"
                                task_result = "完全成功"
                                project_success += 1
                                successful_tasks += 1
                            elif 'PARTIAL' in content_upper:
                                task_status = "🟡"
                                task_result = "部分成功"
                                project_partial += 1
                                partial_tasks += 1
                            elif 'NO' in content_upper:
                                task_status = "❌"
                                task_result = "任务失败(明确否定)"
                                failed_tasks += 1
                            else:
                                # 检查答案内容是否表示成功 (向后兼容)
                                negative_keywords = [
                                    'NOT', 'FAILED', 'ERROR', 'MISSING', 'INCORRECT', 
                                    'WRONG', 'ISSUE', 'PROBLEM', 'UNABLE', 'CANNOT', 'DOES NOT',
                                    'DOESN\'T', 'ISN\'T', 'AREN\'T', 'WASN\'T', 'WEREN\'T',
                                    'BLANK', 'EMPTY', 'UNAVAILABLE', 'BROKEN', 'INVALID'
                                ]
                                
                                contains_negative = any(keyword in content_upper for keyword in negative_keywords)
                                
                                if contains_negative:
                                    task_status = "❌"
                                    task_result = "任务失败(答案为否定)"
                                    failed_tasks += 1
                                else:
                                    task_status = "✅"
                                    task_result = "成功完成"
                                    project_success += 1
                                    successful_tasks += 1
                        else:
                            task_status = "❌"
                            task_result = f"未完成({len(messages)}条消息)"
                            failed_tasks += 1
                    else:
                        task_status = "❌"
                        task_result = "无消息记录"
                        failed_tasks += 1
                        
                except Exception as e:
                    task_status = "⚠️"
                    task_result = f"解析messages失败: {e}"
                    failed_tasks += 1
            else:
                task_status = "❓"
                task_result = "无结果文件"
                failed_tasks += 1
            
            print(f"  {task_status} {task}: {task_result}")
        
        success_rate = (project_success / project_total * 100) if project_total > 0 else 0
        partial_rate = (project_partial / project_total * 100) if project_total > 0 else 0
        combined_rate = ((project_success + project_partial) / project_total * 100) if project_total > 0 else 0
        
        print(f"  📈 项目统计: 成功{project_success}/{project_total} ({success_rate:.1f}%), 部分成功{project_partial} ({partial_rate:.1f}%), 合计{project_success + project_partial} ({combined_rate:.1f}%)")
    
    # 总体统计
    print("\n" + "="*60)
    print("📈 总体统计")
    print("="*60)
    print(f"测试项目数: {len(projects)}")
    print(f"测试任务数: {total_tasks}")
    print(f"完全成功任务: {successful_tasks}")
    print(f"部分成功任务: {partial_tasks}")
    print(f"失败任务数: {failed_tasks}")
    
    overall_success_rate = (successful_tasks / total_tasks * 100) if total_tasks > 0 else 0
    overall_partial_rate = (partial_tasks / total_tasks * 100) if total_tasks > 0 else 0
    overall_combined_rate = ((successful_tasks + partial_tasks) / total_tasks * 100) if total_tasks > 0 else 0
    
    print(f"完全成功率: {successful_tasks}/{total_tasks} ({overall_success_rate:.1f}%)")
    print(f"部分成功率: {partial_tasks}/{total_tasks} ({overall_partial_rate:.1f}%)")
    print(f"总体成功率(含部分): {successful_tasks + partial_tasks}/{total_tasks} ({overall_combined_rate:.1f}%)")
    
    # 计算项目覆盖率
    print(f"\n🎯 项目覆盖率分析:")
    expected_projects = 98  # 总共应该有98个项目 (1-101, 排除47和91)
    tested_projects = len(projects)
    coverage_rate = (tested_projects / expected_projects * 100) if expected_projects > 0 else 0
    print(f"已测试项目: {tested_projects}/{expected_projects} ({coverage_rate:.1f}%)")
    
    # 找出未测试的项目
    all_project_nums = set()
    for i in range(1, 102):
        if i != 47 and i != 91:  # 排除不存在的项目
            all_project_nums.add(f"{i:03d}")
    
    tested_project_nums = set()
    for project in projects:
        if len(project) >= 3 and project[:3].isdigit():  # 提取项目编号
            num = project[:3]
            tested_project_nums.add(num)
    
    untested_nums = sorted(all_project_nums - tested_project_nums)
    if untested_nums:
        print(f"\n🚫 未测试的项目编号 ({len(untested_nums)}个):")
        for i, num in enumerate(untested_nums):
            if i % 15 == 0:
                print(f"\n   ", end="")
            print(f"{num} ", end="")
        print()

def show_task_details(results_dir, project_name, task_name=None):
    """显示具体任务的详细信息"""
    project_dir = os.path.join(results_dir, project_name)
    
    if not os.path.exists(project_dir):
        print(f"❌ 项目结果不存在: {project_name}")
        return
    
    if task_name:
        # 显示具体任务
        task_dir = os.path.join(project_dir, task_name)
        if not os.path.exists(task_dir):
            print(f"❌ 任务结果不存在: {task_name}")
            return
        
        print(f"📋 任务详情: {project_name}/{task_name}")
        print("="*60)
        
        # 显示日志
        agent_log = os.path.join(task_dir, "agent.log")
        if os.path.exists(agent_log):
            print("🗂️  Agent日志:")
            with open(agent_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in lines[-20:]:  # 显示最后20行
                    print(f"  {line.strip()}")
        
        # 显示交互消息
        messages_file = os.path.join(task_dir, "interact_messages.json")
        if os.path.exists(messages_file):
            print("\n💬 最后的交互消息:")
            with open(messages_file, 'r', encoding='utf-8') as f:
                messages = json.load(f)
                if messages:
                    last_msg = messages[-1]
                    print(f"  角色: {last_msg.get('role', 'unknown')}")
                    content = str(last_msg.get('content', ''))[:200]
                    print(f"  内容: {content}...")
    else:
        # 显示项目所有任务
        tasks = [d for d in os.listdir(project_dir) if os.path.isdir(os.path.join(project_dir, d))]
        print(f"📋 项目: {project_name}")
        print(f"任务列表:")
        for task in sorted(tasks):
            print(f"  - {task}")

def main():
    # 默认结果目录
    default_dir = "/Users/luoyujia/Downloads/WebGen-Bench-main/webvoyager/webvoyager_results"
    
    if len(sys.argv) == 1:
        # 使用默认目录分析所有结果
        analyze_test_results(default_dir)
    elif len(sys.argv) == 2:
        # 指定目录或显示项目任务列表
        arg = sys.argv[1]
        if os.path.isdir(arg):
            # 如果是目录，分析该目录
            analyze_test_results(arg)
        else:
            # 如果不是目录，当作项目名显示任务列表
            show_task_details(default_dir, arg)
    elif len(sys.argv) == 3:
        # 显示指定任务的详细信息
        show_task_details(default_dir, sys.argv[1], sys.argv[2])
    else:
        print("使用方法:")
        print("  python analyze_results.py                      # 使用默认目录显示所有结果统计")
        print("  python analyze_results.py <目录路径>           # 分析指定目录的结果")
        print("  python analyze_results.py <项目名>             # 显示项目任务列表")
        print("  python analyze_results.py <项目名> <任务名>     # 显示任务详情")

if __name__ == "__main__":
    main()
