#!/usr/bin/env python3
"""
详细分析WebVoyager测试结果的评估指标
"""

import os
import json
import sys
from pathlib import Path
import re

def parse_evaluation_result(content):
    """解析WebVoyager的最终评估结果"""
    content = content.strip().upper()
    
    # 直接匹配YES/NO/PARTIAL
    if content == "YES":
        return "YES", "完全成功"
    elif content == "NO":
        return "NO", "完全失败"
    elif content == "PARTIAL":
        return "PARTIAL", "部分成功"
    
    # 如果包含ANSWER，尝试从中提取评估
    if "ANSWER" in content:
        # 查找ANSWER后的内容
        answer_match = re.search(r'ANSWER[;\s]*([^\n]*)', content)
        if answer_match:
            answer_content = answer_match.group(1).strip()
            if "YES" in answer_content:
                return "YES", "完全成功"
            elif "NO" in answer_content:
                return "NO", "完全失败" 
            elif "PARTIAL" in answer_content:
                return "PARTIAL", "部分成功"
            else:
                return "ANSWER", f"任务完成: {answer_content[:50]}..."
    
    return "UNKNOWN", "未知状态"

def detailed_analysis():
    """详细分析WebVoyager测试结果"""
    results_dir = "/Users/luoyujia/Downloads/WebGen-Bench-main/webvoyager/webvoyager_results"
    
    if not os.path.exists(results_dir):
        print(f"❌ 结果目录不存在: {results_dir}")
        return
    
    print(f"📊 WebVoyager测试结果详细分析")
    print("="*80)
    
    # 获取所有项目
    projects = [d for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))]
    projects.sort()
    
    # 统计各种结果
    stats = {
        "YES": 0,      # 完全成功
        "NO": 0,       # 完全失败
        "PARTIAL": 0,  # 部分成功
        "ANSWER": 0,   # 有答案但不是YES/NO/PARTIAL
        "UNKNOWN": 0   # 未知状态
    }
    
    task_details = []
    
    for project in projects:
        project_dir = os.path.join(results_dir, project)
        tasks = [d for d in os.listdir(project_dir) if os.path.isdir(os.path.join(project_dir, d))]
        
        for task in tasks:
            task_dir = os.path.join(project_dir, task)
            messages_file = os.path.join(task_dir, "interact_messages.json")
            
            if os.path.exists(messages_file):
                try:
                    with open(messages_file, 'r', encoding='utf-8') as f:
                        messages = json.load(f)
                    
                    if messages:
                        last_message = messages[-1]
                        content = last_message.get('content', '')
                        evaluation, description = parse_evaluation_result(content)
                        
                        stats[evaluation] += 1
                        task_details.append({
                            "project": project,
                            "task": task,
                            "evaluation": evaluation,
                            "description": description,
                            "content": content[:100] + "..." if len(content) > 100 else content
                        })
                    else:
                        stats["UNKNOWN"] += 1
                        task_details.append({
                            "project": project,
                            "task": task,
                            "evaluation": "UNKNOWN",
                            "description": "空消息文件",
                            "content": ""
                        })
                        
                except Exception as e:
                    stats["UNKNOWN"] += 1
                    task_details.append({
                        "project": project,
                        "task": task,
                        "evaluation": "UNKNOWN", 
                        "description": f"解析错误: {e}",
                        "content": ""
                    })
    
    # 显示统计结果
    total_tasks = sum(stats.values())
    print(f"📈 评估结果统计 (总任务数: {total_tasks})")
    print("-" * 50)
    
    for eval_type, count in stats.items():
        percentage = (count / total_tasks * 100) if total_tasks > 0 else 0
        emoji = {
            "YES": "✅",
            "NO": "❌", 
            "PARTIAL": "⚡",
            "ANSWER": "📝",
            "UNKNOWN": "❓"
        }
        print(f"{emoji[eval_type]} {eval_type}: {count} ({percentage:.1f}%)")
    
    # 成功率计算
    success_rate = (stats["YES"] / total_tasks * 100) if total_tasks > 0 else 0
    partial_success_rate = ((stats["YES"] + stats["PARTIAL"]) / total_tasks * 100) if total_tasks > 0 else 0
    
    print(f"\\n🎯 核心指标:")
    print(f"   完全成功率: {success_rate:.1f}%")
    print(f"   部分以上成功率: {partial_success_rate:.1f}%")
    
    # 按项目分类显示
    print(f"\\n📋 按项目分类:")
    print("-" * 50)
    
    project_stats = {}
    for detail in task_details:
        project = detail["project"]
        if project not in project_stats:
            project_stats[project] = {"YES": 0, "NO": 0, "PARTIAL": 0, "ANSWER": 0, "UNKNOWN": 0}
        project_stats[project][detail["evaluation"]] += 1
    
    for project in sorted(project_stats.keys()):
        pstats = project_stats[project]
        total = sum(pstats.values())
        success_count = pstats["YES"] + pstats["PARTIAL"]
        project_success_rate = (success_count / total * 100) if total > 0 else 0
        print(f"  {project}: {success_count}/{total} ({project_success_rate:.1f}%) [YES:{pstats['YES']}, PARTIAL:{pstats['PARTIAL']}, NO:{pstats['NO']}]")
    
    # 显示失败任务的详细信息
    print(f"\\n❌ 失败任务详情:")
    print("-" * 50)
    failed_tasks = [d for d in task_details if d["evaluation"] == "NO"]
    for task in failed_tasks[:10]:  # 只显示前10个
        print(f"  {task['project']} - {task['task']}: {task['description']}")
    
    if len(failed_tasks) > 10:
        print(f"  ... 还有 {len(failed_tasks) - 10} 个失败任务")

if __name__ == "__main__":
    detailed_analysis()
