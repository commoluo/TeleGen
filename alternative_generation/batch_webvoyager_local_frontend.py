#!/usr/bin/env python3
"""
批量测试：按行读取 test.jsonl，每一行调用 test_single_project.py 进行测试。
用法：
  python batch_webvoyager_local_frontend.py           # 自动批量执行
  python batch_webvoyager_local_frontend.py --print   # 只打印命令不执行
  python batch_webvoyager_local_frontend.py --organized # 测试organized_optimized_code
"""
import subprocess
import json
import os
from pathlib import Path
import sys
import re

def main():
    # 检查命令行参数
    print_only = '--print' in sys.argv or '-p' in sys.argv
    use_organized = '--organized' in sys.argv
    use_debug_logged = '--debug_logged' in sys.argv
    use_optimized = '--optimized' in sys.argv
    
    script_dir = Path(__file__).parent
    test_jsonl_path = script_dir.parent / "data" / "test.jsonl"
    single_test_script = script_dir / "test_single_project.py"

    if not test_jsonl_path.exists():
        print(f"❌ 未找到 test.jsonl: {test_jsonl_path}")
        sys.exit(1)
    if not single_test_script.exists():
        print(f"❌ 未找到 test_single_project.py: {single_test_script}")
        sys.exit(1)

    # 从test.jsonl中读取所有任务
    tasks_by_id = {}
    with open(test_jsonl_path, 'r', encoding='utf-8') as fin:
        for line in fin:
            try:
                data = json.loads(line)
                project_id = str(data.get("id", ""))
                if project_id:
                    # 将id格式化为三位数
                    formatted_id = str(int(project_id)).zfill(3)
                    tasks_by_id[formatted_id] = line.strip()
            except Exception as e:
                continue

    if print_only:
        print("🔍 仅打印命令模式（不执行）")
    
    projects_to_test = []
    test_mode_flag = ""
    
    if use_debug_logged:
        print("🚀 测试 debug_logged_projects 项目模式")
        test_mode_flag = "--debug_logged"
        target_dir = script_dir / "debug_logged_projects"
        if not target_dir.exists():
            print(f"❌ 未找到目录: {target_dir}")
            sys.exit(1)
        
        # 获取所有以 "full_run_with_api_doc_" 开头并以 "_runnable" 结尾的项目
        project_pattern = r"full_run_with_api_doc_(\d+)_restructured"
        for item in os.listdir(target_dir):
            if re.match(project_pattern, item):
                projects_to_test.append(item)
        
        # 按项目ID排序
        projects_to_test.sort(key=lambda x: int(re.search(r'(\d+)', x).group(1)))

    elif use_optimized:
        print("🚀 测试 optimized_code 项目模式")
        test_mode_flag = "--optimized"
        target_dir = script_dir / "optimized_code"
        if not target_dir.exists():
            print(f"❌ 未找到目录: {target_dir}")
            sys.exit(1)
        
        # 获取所有以 "full_run_with_api_doc_" 开头并以 "_restructured" 结尾的项目
        project_pattern = r"full_run_with_api_doc_(\d+)_restructured_optimized_restructured"
        for item in os.listdir(target_dir):
            if re.match(project_pattern, item):
                projects_to_test.append(item)
        
        # 按项目ID排序
        projects_to_test.sort(key=lambda x: int(re.search(r'(\d+)', x).group(1)))

    elif use_organized:
        print("🚀 测试 organized_optimized_code 项目模式")
        test_mode_flag = "--organized"
        target_dir = script_dir / "organized_optimized_code"
        if not target_dir.exists():
            print(f"❌ 未找到 organized_optimized_code 目录: {target_dir}")
            sys.exit(1)
        
        # 获取所有 restructured 项目
        for item in os.listdir(target_dir):
            if item.endswith("_simple_project_runnable_restructured"):
                projects_to_test.append(item)
        
        projects_to_test.sort(key=lambda x: int(x.split('_')[0]))

    else:
        print("� 自动批量执行默认模式")
        # 默认模式逻辑，如果需要的话
        with open(test_jsonl_path, 'r', encoding='utf-8') as fin:
            for idx, line in enumerate(fin):
                try:
                    data = json.loads(line)
                    project_id = str(data.get("id", ""))
                    if not project_id:
                        print(f"跳过第{idx+1}行：无id字段")
                        continue
                    # 兼容前导0
                    project_name = f"{project_id}_restructured"
                    projects_to_test.append((project_name, line.strip()))
                except Exception as e:
                    print(f"处理第{idx+1}行时出错: {e}")
                    continue
    
    if use_debug_logged or use_organized or use_optimized:
        for project_name in projects_to_test:
            # 从项目名称中提取ID
            match = re.search(r'(\d+)', project_name)
            if not match:
                print(f"⚠️  无法从 '{project_name}' 中提取ID，跳过")
                continue
            
            project_id_str = str(int(match.group(1))).zfill(3)

            if project_id_str not in tasks_by_id:
                print(f"⚠️  在 test.jsonl 中未找到项目ID {project_id_str} 对应的任务，跳过 {project_name}")
                continue
            
            task_line = tasks_by_id[project_id_str]
            
            cmd = [
                "python",
                str(single_test_script),
                "--test-case-json",
                task_line,
                test_mode_flag,
                "--project-name",
                project_name
            ]
            
            if print_only:
                print(" ".join(cmd))
            else:
                print("-" * 50)
                print(f"▶️  开始测试: {project_name}")
                try:
                    subprocess.run(cmd, check=True)
                    print(f"✅ 测试完成: {project_name}")
                except subprocess.CalledProcessError as e:
                    print(f"❌ 测试失败: {project_name}，错误码: {e.returncode}")
                except KeyboardInterrupt:
                    print("\n🛑 用户中断，测试终止")
                    sys.exit(1)
    else:
        # 默认模式的执行逻辑
        for project_name, task_line in projects_to_test:
            cmd = [
                "python",
                str(single_test_script),
                "--test-case-json",
                task_line
            ]
            
            if print_only:
                print(" ".join(cmd))
            else:
                print("-" * 50)
                print(f"▶️  开始测试: {project_name}")
                try:
                    subprocess.run(cmd, check=True)
                    print(f"✅ 测试完成: {project_name}")
                except subprocess.CalledProcessError as e:
                    print(f"❌ 测试失败: {project_name}，错误码: {e.returncode}")
                except KeyboardInterrupt:
                    print("\n🛑 用户中断，测试终止")
                    sys.exit(1)

if __name__ == "__main__":
    main()
