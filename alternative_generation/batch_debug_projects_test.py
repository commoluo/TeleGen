#!/usr/bin/env python3
"""
批量测试debug_logged_projects：按行读取 test.jsonl，每一行调用 test_single_debug_project.py 进行测试。
用法：
  python batch_debug_projects_test.py           # 自动批量执行
  python batch_debug_projects_test.py --print   # 只打印命令不执行
"""
import subprocess
import json
from pathlib import Path
import sys

def main():
    # 检查命令行参数
    print_only = '--print' in sys.argv or '-p' in sys.argv
    
    script_dir = Path(__file__).parent
    test_jsonl_path = script_dir.parent / "data" / "test.jsonl"
    single_test_script = script_dir / "test_single_debug_project.py"

    if not test_jsonl_path.exists():
        print(f"❌ 未找到 test.jsonl: {test_jsonl_path}")
        sys.exit(1)
    if not single_test_script.exists():
        print(f"❌ 未找到 test_single_debug_project.py: {single_test_script}")
        sys.exit(1)

    # 检查debug_logged_projects目录
    debug_projects_dir = script_dir / "debug_logged_projects"
    if not debug_projects_dir.exists():
        print(f"❌ 未找到 debug_logged_projects 目录: {debug_projects_dir}")
        sys.exit(1)

    if print_only:
        print("🔍 仅打印命令模式（不执行）")
    else:
        print("🚀 自动批量执行模式 - 测试 debug_logged_projects")

    print(f"📁 测试目录: {debug_projects_dir}")
    print(f"📄 测试数据: {test_jsonl_path}")
    print(f"🔧 测试脚本: {single_test_script}")
    print(f"📊 结果保存位置: {script_dir.parent}/webvoyager/results_debug/")
    print("-" * 80)

    success_count = 0
    fail_count = 0
    total_count = 0

    with open(test_jsonl_path, 'r', encoding='utf-8') as fin:
        for idx, line in enumerate(fin):
            try:
                data = json.loads(line)
                project_id = str(data.get("id", ""))
                if not project_id:
                    print(f"跳过第{idx+1}行：无id字段")
                    continue
                
                # 构建debug项目名称: 001_simple_project_runnable
                # 将6位ID转换为3位: 000001 -> 001
                project_num = str(int(project_id)).zfill(3)
                project_name = f"{project_num}_simple_project_runnable"
                project_path = debug_projects_dir / project_name
                
                # 检查项目是否存在
                if not project_path.exists():
                    print(f"⚠️ 跳过第{idx+1}行：项目不存在 {project_name}")
                    continue
                
                total_count += 1
                print(f"\n==== 批量测试第{idx+1}个项目 [{total_count}]: {project_name} ====")
                print(f"📁 项目路径: {project_path}")
                
                cmd_str = f"python {single_test_script} {project_name} --json_line '{line.strip()}'"
                
                if print_only:
                    # 只打印命令，不执行
                    print(f"请在终端执行：\n{cmd_str}\n")
                else:
                    # 自动执行
                    cmd = [sys.executable, str(single_test_script), project_name, '--json_line', line.strip()]
                    print(f"执行命令: {cmd_str}")
                    
                    try:
                        result = subprocess.run(cmd, text=True, timeout=600)  # 10分钟超时
                        if result.returncode == 0:
                            print(f"✅ {project_name} 测试成功")
                            success_count += 1
                        else:
                            print(f"❌ {project_name} 测试失败，返回码: {result.returncode}")
                            fail_count += 1
                    except subprocess.TimeoutExpired:
                        print(f"⏰ {project_name} 测试超时（10分钟）")
                        fail_count += 1
                    except Exception as e:
                        print(f"❌ {project_name} 执行出错: {e}")
                        fail_count += 1
                    
                    print(f"📊 当前进度: 成功 {success_count}, 失败 {fail_count}, 总计 {total_count}")
                    print("-" * 60)
            except Exception as e:
                print(f"跳过第{idx+1}行，解析或测试出错: {e}")

    # 最终统计
    if not print_only:
        print("\n" + "=" * 80)
        print("🎯 批量测试完成统计:")
        print(f"   📊 总测试项目数: {total_count}")
        print(f"   ✅ 成功项目数: {success_count}")
        print(f"   ❌ 失败项目数: {fail_count}")
        if total_count > 0:
            success_rate = (success_count / total_count) * 100
            print(f"   📈 成功率: {success_rate:.1f}%")
        print(f"   📁 详细结果保存在: {script_dir.parent}/webvoyager/results_debug/")
        print("=" * 80)

if __name__ == "__main__":
    main()
