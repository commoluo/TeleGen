#!/usr/bin/env python3
"""
统计 webvoyager_results 目录的测试结果
用法：python compute_webvoyager_acc.py webvoyager_results
"""
import os
from tqdm import tqdm
import json
import argparse

def load_json(in_file):
    with open(in_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def load_jsonl(in_file):
    datas = []
    with open(in_file, "r", encoding="utf-8") as f:
        for line in tqdm(f):
            datas.append(json.loads(line))
    return datas

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("in_dir", type=str, help="webvoyager_results 目录路径")
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
    
    if not test_file:
        print("❌ 未找到 test.jsonl 文件")
        return
    
    print(f"📄 使用测试文件: {test_file}")
    test_datas = load_jsonl(test_file)
    
    # 统计结果
    total_tasks = 0
    completed_tasks = 0
    yes_count = 0
    partial_count = 0
    no_count = 0
    failed_count = 0
    
    # 遍历所有项目目录
    project_dirs = [d for d in os.listdir(args.in_dir) if os.path.isdir(os.path.join(args.in_dir, d))]
    project_dirs.sort()
    
    print(f"🔍 找到 {len(project_dirs)} 个项目目录")
    
    for project_dir in tqdm(project_dirs, desc="分析项目结果"):
        project_path = os.path.join(args.in_dir, project_dir)
        
        # 遍历项目下的任务目录
        task_dirs = [d for d in os.listdir(project_path) if d.startswith('task')]
        
        for task_dir in task_dirs:
            task_path = os.path.join(project_path, task_dir)
            interact_file = os.path.join(task_path, "interact_messages.json")
            
            total_tasks += 1
            
            if not os.path.exists(interact_file):
                failed_count += 1
                continue
            
            completed_tasks += 1
            
            # 分析最后的回复
            try:
                data = load_json(interact_file)
                last_assistant_message = ""
                
                # 从后往前找最后一个 assistant 消息
                for message in reversed(data):
                    if message.get("role") == "assistant":
                        last_assistant_message = message.get("content", "")
                        break
                
                # 判断结果
                if "YES" in last_assistant_message.upper():
                    yes_count += 1
                elif "PARTIAL" in last_assistant_message.upper():
                    partial_count += 1
                elif "NO" in last_assistant_message.upper():
                    no_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                print(f"⚠️ 解析失败 {task_path}: {e}")
                failed_count += 1
    
    # 计算统计数据
    if total_tasks == 0:
        print("❌ 未找到任何任务")
        return
    
    success_rate = (yes_count + partial_count * 0.5) / total_tasks * 100
    completion_rate = completed_tasks / total_tasks * 100
    
    # 输出结果
    print("\n" + "="*60)
    print("📊 WebVoyager 测试结果统计")
    print("="*60)
    print(f"总任务数:     {total_tasks}")
    print(f"完成任务数:   {completed_tasks} ({completion_rate:.1f}%)")
    print(f"启动失败:     {failed_count} ({failed_count/total_tasks*100:.1f}%)")
    print("-"*60)
    print(f"YES (成功):   {yes_count} ({yes_count/total_tasks*100:.1f}%)")
    print(f"PARTIAL:      {partial_count} ({partial_count/total_tasks*100:.1f}%)")
    print(f"NO (失败):    {no_count} ({no_count/total_tasks*100:.1f}%)")
    print("-"*60)
    print(f"总体成功率:   {success_rate:.1f}%")
    
    # 生成 Markdown 表格
    table = f"""
| 指标 | 数量 | 百分比 |
|------|------|--------|
| 总任务数 | {total_tasks} | 100.0% |
| 完成任务 | {completed_tasks} | {completion_rate:.1f}% |
| 启动失败 | {failed_count} | {failed_count/total_tasks*100:.1f}% |
| YES (成功) | {yes_count} | {yes_count/total_tasks*100:.1f}% |
| PARTIAL (部分成功) | {partial_count} | {partial_count/total_tasks*100:.1f}% |
| NO (失败) | {no_count} | {no_count/total_tasks*100:.1f}% |
| **总体成功率** | **{yes_count + partial_count * 0.5:.1f}** | **{success_rate:.1f}%** |
"""
    
    # 保存结果
    output_file = os.path.join(args.in_dir, "webvoyager_stats.md")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# WebVoyager 测试结果统计\n\n")
        f.write(f"生成时间: {os.popen('date').read().strip()}\n\n")
        f.write(table)
    
    print(f"\n📄 详细结果已保存到: {output_file}")

if __name__ == "__main__":
    main()
