#!/usr/bin/env python3
"""
详细统计 webvoyager_results 目录的测试结果
用法：python detailed_webvoyager_stats.py webvoyager_results
生成每个任务的详细执行情况报告
"""
import os
import json
import argparse
import csv
from datetime import datetime
from pathlib import Path

def load_json(in_file):
    try:
        with open(in_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data, None
    except Exception as e:
        return None, str(e)

def load_jsonl(in_file):
    datas = []
    with open(in_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line)
                data['_line_number'] = line_num
                datas.append(data)
            except Exception as e:
                print(f"⚠️ 解析 test.jsonl 第{line_num}行失败: {e}")
    return datas

def analyze_task_result(task_path, project_id, task_name):
    """分析单个任务的执行结果"""
    result = {
        'project_id': project_id,
        'task_name': task_name,
        'task_path': task_path,
        'status': 'UNKNOWN',
        'ai_response': '',
        'error_message': '',
        'total_interactions': 0,
        'screenshots_count': 0,
        'has_console_logs': False,
        'has_driver_logs': False,
        'console_errors': 0,
        'console_warnings': 0,
        'file_size_mb': 0,
        'execution_time': 'unknown'
    }
    
    # 检查任务目录是否存在
    if not os.path.exists(task_path):
        result['status'] = 'TASK_DIR_MISSING'
        result['error_message'] = '任务目录不存在'
        return result
    
    # 计算目录大小
    try:
        total_size = sum(os.path.getsize(os.path.join(dirpath, filename))
                        for dirpath, dirnames, filenames in os.walk(task_path)
                        for filename in filenames)
        result['file_size_mb'] = round(total_size / (1024 * 1024), 2)
    except:
        pass
    
    # 统计截图数量
    screenshots = [f for f in os.listdir(task_path) if f.startswith('screenshot') and f.endswith('.png')]
    result['screenshots_count'] = len(screenshots)
    
    # 检查日志文件
    console_log_path = os.path.join(task_path, 'console_logs.json')
    driver_log_path = os.path.join(task_path, 'driver_logs.json')
    
    result['has_console_logs'] = os.path.exists(console_log_path)
    result['has_driver_logs'] = os.path.exists(driver_log_path)
    
    # 分析 console 日志
    if result['has_console_logs']:
        console_data, error = load_json(console_log_path)
        if console_data:
            for log_entry in console_data:
                level = log_entry.get('level', '').upper()
                if level == 'SEVERE':
                    result['console_errors'] += 1
                elif level == 'WARNING':
                    result['console_warnings'] += 1
    
    # 分析主要的交互记录
    interact_file = os.path.join(task_path, "interact_messages.json")
    
    if not os.path.exists(interact_file):
        result['status'] = 'START_FAILED'
        result['error_message'] = 'interact_messages.json 文件不存在，可能是启动失败'
        return result
    
    # 解析交互记录
    interact_data, error = load_json(interact_file)
    if interact_data is None:
        result['status'] = 'JSON_PARSE_ERROR'
        result['error_message'] = f'JSON解析失败: {error}'
        return result
    
    result['total_interactions'] = len(interact_data)
    
    # 找到最后的 AI 回复
    last_assistant_message = ""
    for message in reversed(interact_data):
        if message.get("role") == "assistant":
            last_assistant_message = message.get("content", "")
            break
    
    result['ai_response'] = last_assistant_message[:200] + '...' if len(last_assistant_message) > 200 else last_assistant_message
    
    # 判断执行结果
    upper_response = last_assistant_message.upper()
    if "YES" in upper_response:
        result['status'] = 'SUCCESS'
    elif "PARTIAL" in upper_response:
        result['status'] = 'PARTIAL'
    elif "NO" in upper_response:
        result['status'] = 'FAILED'
    else:
        result['status'] = 'NO_FINAL_ANSWER'
        result['error_message'] = 'AI 未给出明确的 YES/PARTIAL/NO 回答'
    
    # 尝试从日志中获取执行时间
    agent_log_path = os.path.join(task_path, 'agent.log')
    if os.path.exists(agent_log_path):
        try:
            with open(agent_log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) > 1:
                    first_line = lines[0]
                    last_line = lines[-1]
                    # 简单的时间估算（如果日志有时间戳）
                    result['execution_time'] = f'{len(lines)} log entries'
        except:
            pass
    
    return result

def get_task_info_from_test_data(test_datas, project_id, task_index):
    """从 test.jsonl 获取任务的详细信息"""
    try:
        project_index = int(project_id) - 1  # 假设 project_id 从1开始
        if 0 <= project_index < len(test_datas):
            project_data = test_datas[project_index]
            if 0 <= task_index < len(project_data.get('ui_instruct', [])):
                task_data = project_data['ui_instruct'][task_index]
                return {
                    'task_description': task_data.get('instruction', ''),
                    'expected_result': task_data.get('expected_result', ''),
                    'category': task_data.get('task_category', {}).get('primary_category', ''),
                    'web_url': project_data.get('web', ''),
                    'project_category': project_data.get('Category', {}).get('primary_category', '')
                }
    except:
        pass
    return {
        'task_description': 'Unknown',
        'expected_result': 'Unknown',
        'category': 'Unknown',
        'web_url': 'Unknown',
        'project_category': 'Unknown'
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("in_dir", type=str, help="webvoyager_results 目录路径")
    parser.add_argument("--output", type=str, default="detailed_stats", help="输出文件前缀")
    args = parser.parse_args()
    
    if not os.path.exists(args.in_dir):
        print(f"❌ 目录不存在: {args.in_dir}")
        return
    
    # 找到 test.jsonl 文件
    test_file = None
    possible_paths = [
        "data/test.jsonl",
        "../data/test.jsonl", 
        "../../data/test.jsonl"
    ]
    for path in possible_paths:
        if os.path.exists(path):
            test_file = path
            break
    
    test_datas = []
    if test_file:
        print(f"📄 使用测试文件: {test_file}")
        test_datas = load_jsonl(test_file)
    else:
        print("⚠️ 未找到 test.jsonl 文件，将无法显示任务详情")
    
    # 收集所有任务结果
    all_results = []
    
    # 遍历所有项目目录
    project_dirs = [d for d in os.listdir(args.in_dir) if os.path.isdir(os.path.join(args.in_dir, d))]
    project_dirs.sort()
    
    print(f"🔍 找到 {len(project_dirs)} 个项目目录")
    print("📊 开始详细分析...")
    
    for i, project_dir in enumerate(project_dirs):
        print(f"分析项目 {i+1}/{len(project_dirs)}: {project_dir}")
        project_path = os.path.join(args.in_dir, project_dir)
        
        # 提取项目ID
        project_id = project_dir.replace('_restructured', '').replace('000', '')
        
        # 遍历项目下的任务目录
        task_dirs = [d for d in os.listdir(project_path) if d.startswith('task')]
        task_dirs.sort()
        
        for task_dir in task_dirs:
            task_path = os.path.join(project_path, task_dir)
            
            # 提取任务索引
            task_index = 0
            try:
                parts = task_dir.split('--')
                if len(parts) > 1:
                    task_index = int(parts[1]) - 1  # 从1开始计数，转换为0开始的索引
            except:
                pass
            
            # 分析任务结果
            result = analyze_task_result(task_path, project_id, task_dir)
            
            # 添加来自 test.jsonl 的信息
            task_info = get_task_info_from_test_data(test_datas, project_id, task_index)
            result.update(task_info)
            
            all_results.append(result)
    
    # 生成统计报告
    generate_reports(all_results, args.in_dir, args.output)

def generate_reports(all_results, output_dir, output_prefix):
    """生成多种格式的详细报告"""
    
    # 统计数据
    total_tasks = len(all_results)
    status_counts = {}
    category_stats = {}
    
    for result in all_results:
        status = result['status']
        category = result['category']
        
        status_counts[status] = status_counts.get(status, 0) + 1
        
        if category not in category_stats:
            category_stats[category] = {'total': 0, 'success': 0, 'partial': 0, 'failed': 0, 'start_failed': 0}
        
        category_stats[category]['total'] += 1
        if status == 'SUCCESS':
            category_stats[category]['success'] += 1
        elif status == 'PARTIAL':
            category_stats[category]['partial'] += 1
        elif status == 'FAILED':
            category_stats[category]['failed'] += 1
        else:
            category_stats[category]['start_failed'] += 1
    
    # 1. 生成 CSV 详细报告
    csv_file = os.path.join(output_dir, f"{output_prefix}_detailed.csv")
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Project ID', 'Task Name', 'Status', 'Category', 'Project Category',
            'Task Description', 'Expected Result', 'AI Response',
            'Total Interactions', 'Screenshots', 'Console Errors', 'Console Warnings',
            'File Size (MB)', 'Has Console Logs', 'Has Driver Logs', 'Error Message'
        ])
        
        for result in all_results:
            writer.writerow([
                result['project_id'],
                result['task_name'],
                result['status'],
                result['category'],
                result['project_category'],
                result['task_description'],
                result['expected_result'],
                result['ai_response'],
                result['total_interactions'],
                result['screenshots_count'],
                result['console_errors'],
                result['console_warnings'],
                result['file_size_mb'],
                result['has_console_logs'],
                result['has_driver_logs'],
                result['error_message']
            ])
    
    # 2. 生成 Markdown 汇总报告
    md_file = os.path.join(output_dir, f"{output_prefix}_summary.md")
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(f"# WebVoyager 详细测试结果报告\n\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # 总体统计
        f.write(f"## 总体统计\n\n")
        f.write(f"- 总任务数: {total_tasks}\n")
        f.write(f"- 成功任务: {status_counts.get('SUCCESS', 0)} ({status_counts.get('SUCCESS', 0)/total_tasks*100:.1f}%)\n")
        f.write(f"- 部分成功: {status_counts.get('PARTIAL', 0)} ({status_counts.get('PARTIAL', 0)/total_tasks*100:.1f}%)\n")
        f.write(f"- 失败任务: {status_counts.get('FAILED', 0)} ({status_counts.get('FAILED', 0)/total_tasks*100:.1f}%)\n")
        f.write(f"- 启动失败: {status_counts.get('START_FAILED', 0)} ({status_counts.get('START_FAILED', 0)/total_tasks*100:.1f}%)\n")
        f.write(f"- 其他问题: {total_tasks - sum(status_counts.values())}\n\n")
        
        success_rate = (status_counts.get('SUCCESS', 0) + status_counts.get('PARTIAL', 0) * 0.5) / total_tasks * 100
        f.write(f"**总体成功率: {success_rate:.1f}%**\n\n")
        
        # 按状态统计
        f.write(f"## 按执行状态统计\n\n")
        f.write(f"| 状态 | 数量 | 百分比 |\n")
        f.write(f"|------|------|--------|\n")
        for status, count in sorted(status_counts.items()):
            f.write(f"| {status} | {count} | {count/total_tasks*100:.1f}% |\n")
        f.write(f"\n")
        
        # 按类别统计
        f.write(f"## 按任务类别统计\n\n")
        f.write(f"| 类别 | 总数 | 成功 | 部分成功 | 失败 | 启动失败 | 成功率 |\n")
        f.write(f"|------|------|------|----------|------|----------|--------|\n")
        for category, stats in sorted(category_stats.items()):
            if stats['total'] > 0:
                success_rate = (stats['success'] + stats['partial'] * 0.5) / stats['total'] * 100
                f.write(f"| {category} | {stats['total']} | {stats['success']} | {stats['partial']} | {stats['failed']} | {stats['start_failed']} | {success_rate:.1f}% |\n")
        f.write(f"\n")
        
        # 失败任务详情
        failed_tasks = [r for r in all_results if r['status'] in ['START_FAILED', 'NO_FINAL_ANSWER', 'JSON_PARSE_ERROR']]
        if failed_tasks:
            f.write(f"## 失败任务详情 ({len(failed_tasks)} 个)\n\n")
            for task in failed_tasks:
                f.write(f"### {task['project_id']} - {task['task_name']}\n")
                f.write(f"- **状态**: {task['status']}\n")
                f.write(f"- **错误**: {task['error_message']}\n")
                f.write(f"- **类别**: {task['category']}\n")
                f.write(f"- **描述**: {task['task_description'][:100]}...\n\n")
        
        # 控制台错误统计
        error_tasks = [r for r in all_results if r['console_errors'] > 0]
        if error_tasks:
            f.write(f"## 存在控制台错误的任务 ({len(error_tasks)} 个)\n\n")
            f.write(f"| 项目ID | 任务名 | 错误数 | 警告数 | 状态 |\n")
            f.write(f"|--------|--------|--------|--------|---------|\n")
            for task in error_tasks:
                f.write(f"| {task['project_id']} | {task['task_name']} | {task['console_errors']} | {task['console_warnings']} | {task['status']} |\n")
            f.write(f"\n")
    
    # 3. 生成失败任务的 JSON 详情
    failed_details = [r for r in all_results if r['status'] != 'SUCCESS']
    json_file = os.path.join(output_dir, f"{output_prefix}_failed_details.json")
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(failed_details, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 详细统计报告已生成:")
    print(f"📊 CSV详细数据: {csv_file}")
    print(f"📋 Markdown汇总: {md_file}")
    print(f"🔍 失败任务详情: {json_file}")
    print(f"\n📈 总体成功率: {success_rate:.1f}% ({status_counts.get('SUCCESS', 0) + status_counts.get('PARTIAL', 0)}/{total_tasks})")

if __name__ == "__main__":
    main()
