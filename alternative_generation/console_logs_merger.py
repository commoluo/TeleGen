#!/usr/bin/env python3
"""
Console Logs 合并器和读取器
Console Logs Merger and Reader

功能：
1. 读取webvoyager/results_for_1/results_debug中的所有内容
2. 将单个项目中所有task的console_logs.json合并为一个文件
3. 提供读取debug_logged_projects中的frontend_original.jsx和合并后的console_logs.json的功能
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

class ConsoleLogsMerger:
    """Console日志合并器"""
    
    def __init__(self, 
                 results_debug_dir: str = "/Users/luoyujia/Downloads/WebGen-Bench-main/webvoyager/webvoyager_results",
                 debug_projects_dir: str = "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/debug_logged_projects",
                 output_dir: str = "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/merged_console_logs"):
        
        self.results_debug_dir = Path(results_debug_dir)
        self.debug_projects_dir = Path(debug_projects_dir)
        self.output_dir = Path(output_dir)
        
        # 创建输出目录
        self.output_dir.mkdir(exist_ok=True)
        
        print(f"📁 Results Debug目录: {self.results_debug_dir}")
        print(f"📁 Debug Projects目录: {self.debug_projects_dir}")
        print(f"📁 输出目录: {self.output_dir}")
    
    def discover_projects(self) -> List[str]:
        """发现所有可用的项目"""
        projects = []
        
        if not self.results_debug_dir.exists():
            print(f"❌ Results debug目录不存在: {self.results_debug_dir}")
            return projects
        
        for item in sorted(self.results_debug_dir.iterdir()):
            if item.is_dir() and item.name.endswith("_runnable"):
                projects.append(item.name)
        
        print(f"🔍 发现 {len(projects)} 个项目")
        return projects
    
    def merge_console_logs_for_project(self, project_name: str) -> bool:
        """合并单个项目的所有console_logs.json文件"""
        project_path = self.results_debug_dir / project_name
        
        if not project_path.exists():
            print(f"❌ 项目目录不存在: {project_path}")
            return False
        
        # 收集所有任务的console_logs.json
        all_console_logs = {}
        task_count = 0
        
        for task_dir in sorted(project_path.iterdir()):
            if not task_dir.is_dir():
                continue
            
            console_log_file = task_dir / "console_logs.json"
            if console_log_file.exists():
                try:
                    with open(console_log_file, 'r', encoding='utf-8') as f:
                        console_data = json.load(f)
                    
                    all_console_logs[task_dir.name] = {
                        'task_name': task_dir.name,
                        'console_logs': console_data,
                        'log_count': len(console_data) if isinstance(console_data, list) else 1,
                        'merge_timestamp': datetime.now().isoformat()
                    }
                    task_count += 1
                    
                except Exception as e:
                    print(f"⚠️  读取失败 {console_log_file}: {e}")
                    all_console_logs[task_dir.name] = {
                        'task_name': task_dir.name,
                        'error': str(e),
                        'merge_timestamp': datetime.now().isoformat()
                    }
        
        if not all_console_logs:
            print(f"❌ 项目 {project_name} 没有找到console_logs.json文件")
            return False
        
        # 创建合并后的数据结构
        merged_data = {
            'project_name': project_name,
            'merge_timestamp': datetime.now().isoformat(),
            'total_tasks': task_count,
            'tasks_with_logs': len([t for t in all_console_logs.values() if 'console_logs' in t]),
            'tasks_with_errors': len([t for t in all_console_logs.values() if 'error' in t]),
            'console_logs_by_task': all_console_logs,
            'summary': {
                'total_log_entries': sum(
                    task.get('log_count', 0) for task in all_console_logs.values()
                ),
                'available_tasks': list(all_console_logs.keys())
            }
        }
        
        # 保存合并后的文件
        output_file = self.output_dir / f"{project_name}_merged_console_logs.json"
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(merged_data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 合并完成: {project_name}")
            print(f"   📝 任务数: {task_count}")
            print(f"   📄 输出文件: {output_file}")
            return True
            
        except Exception as e:
            print(f"❌ 保存失败 {output_file}: {e}")
            return False
    
    def merge_all_projects(self) -> Dict[str, bool]:
        """合并所有项目的console logs"""
        projects = self.discover_projects()
        results = {}
        
        print(f"\n🚀 开始合并所有项目的console logs")
        print("=" * 60)
        
        for i, project in enumerate(projects, 1):
            print(f"\n[{i}/{len(projects)}] 处理项目: {project}")
            results[project] = self.merge_console_logs_for_project(project)
        
        # 统计结果
        successful = len([r for r in results.values() if r])
        failed = len(results) - successful
        
        print(f"\n📊 合并完成统计:")
        print(f"   ✅ 成功: {successful}")
        print(f"   ❌ 失败: {failed}")
        print(f"   📁 输出目录: {self.output_dir}")
        
        return results
    
    def read_project_data(self, project_name: str) -> Optional[Dict]:
        """读取项目的frontend_original.jsx和合并后的console_logs.json"""
        
        # 标准化项目名称（移除后缀）
        if project_name.endswith("_simple_project_runnable"):
            base_project_name = project_name.replace("_simple_project_runnable", "_simple_project")
        elif project_name.endswith("_runnable"):
            base_project_name = project_name.replace("_runnable", "")
        else:
            base_project_name = project_name
        
        # 读取frontend_original.jsx
        frontend_file = self.debug_projects_dir / base_project_name / "frontend_original.jsx"
        console_logs_file = self.output_dir / f"{project_name}_merged_console_logs.json"
        
        result = {
            'project_name': project_name,
            'base_project_name': base_project_name,
            'frontend_original': None,
            'console_logs': None,
            'errors': []
        }
        
        # 读取frontend_original.jsx
        if frontend_file.exists():
            try:
                with open(frontend_file, 'r', encoding='utf-8') as f:
                    result['frontend_original'] = f.read()
                print(f"✅ 读取frontend文件: {frontend_file}")
            except Exception as e:
                error_msg = f"读取frontend文件失败: {e}"
                result['errors'].append(error_msg)
                print(f"❌ {error_msg}")
        else:
            error_msg = f"Frontend文件不存在: {frontend_file}"
            result['errors'].append(error_msg)
            print(f"❌ {error_msg}")
        
        # 读取合并后的console_logs.json
        if console_logs_file.exists():
            try:
                with open(console_logs_file, 'r', encoding='utf-8') as f:
                    result['console_logs'] = json.load(f)
                print(f"✅ 读取console logs文件: {console_logs_file}")
            except Exception as e:
                error_msg = f"读取console logs文件失败: {e}"
                result['errors'].append(error_msg)
                print(f"❌ {error_msg}")
        else:
            error_msg = f"Console logs文件不存在: {console_logs_file}"
            result['errors'].append(error_msg)
            print(f"❌ {error_msg}")
            
            # 如果合并文件不存在，尝试先合并
            print(f"🔄 尝试为项目 {project_name} 合并console logs...")
            if self.merge_console_logs_for_project(project_name):
                # 重新尝试读取
                try:
                    with open(console_logs_file, 'r', encoding='utf-8') as f:
                        result['console_logs'] = json.load(f)
                    print(f"✅ 重新读取成功: {console_logs_file}")
                    # 移除之前的错误信息
                    result['errors'] = [e for e in result['errors'] if 'Console logs文件不存在' not in e]
                except Exception as e:
                    result['errors'].append(f"重新读取console logs失败: {e}")
        
        return result
    
    def get_console_logs_summary(self, project_name: str) -> Optional[Dict]:
        """获取项目console logs的摘要信息"""
        console_logs_file = self.output_dir / f"{project_name}_merged_console_logs.json"
        
        if not console_logs_file.exists():
            return None
        
        try:
            with open(console_logs_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            summary = {
                'project_name': data.get('project_name'),
                'total_tasks': data.get('total_tasks', 0),
                'tasks_with_logs': data.get('tasks_with_logs', 0),
                'tasks_with_errors': data.get('tasks_with_errors', 0),
                'total_log_entries': data.get('summary', {}).get('total_log_entries', 0),
                'available_tasks': data.get('summary', {}).get('available_tasks', []),
                'merge_timestamp': data.get('merge_timestamp')
            }
            
            return summary
            
        except Exception as e:
            print(f"❌ 读取摘要失败: {e}")
            return None
    
    def list_available_projects(self) -> List[str]:
        """列出所有可用的项目"""
        # 从results_debug目录获取项目列表
        results_projects = self.discover_projects()
        
        # 从已合并的文件获取项目列表
        merged_projects = []
        if self.output_dir.exists():
            for file in self.output_dir.glob("*_merged_console_logs.json"):
                project_name = file.name.replace("_merged_console_logs.json", "")
                merged_projects.append(project_name)
        
        return {
            'results_debug_projects': results_projects,
            'merged_projects': sorted(merged_projects),
            'total_results_projects': len(results_projects),
            'total_merged_projects': len(merged_projects)
        }

def main():
    """主函数 - 演示用法"""
    print("🚀 Console Logs 合并器和读取器")
    print("=" * 60)
    
    # 创建合并器实例
    merger = ConsoleLogsMerger()
    
    # 显示可用项目
    available = merger.list_available_projects()
    print(f"\n📋 可用项目统计:")
    print(f"   Results debug中的项目: {available['total_results_projects']}")
    print(f"   已合并的项目: {available['total_merged_projects']}")
    
    # 询问用户操作
    print(f"\n请选择操作:")
    print(f"1. 合并所有项目的console logs")
    print(f"2. 合并单个项目的console logs")
    print(f"3. 读取项目数据 (frontend + console logs)")
    print(f"4. 查看项目console logs摘要")
    print(f"5. 列出所有可用项目")
    
    choice = input("\n请输入选择 (1-5): ").strip()
    
    if choice == "1":
        # 合并所有项目
        merger.merge_all_projects()
        
    elif choice == "2":
        # 合并单个项目
        projects = merger.discover_projects()
        if projects:
            print(f"\n可用项目:")
            for i, project in enumerate(projects, 1):
                print(f"  {i}. {project}")
            
            try:
                idx = int(input(f"\n请选择项目 (1-{len(projects)}): ")) - 1
                if 0 <= idx < len(projects):
                    merger.merge_console_logs_for_project(projects[idx])
                else:
                    print("❌ 无效选择")
            except ValueError:
                print("❌ 请输入有效数字")
        else:
            print("❌ 没有找到可用项目")
    
    elif choice == "3":
        # 读取项目数据
        project_name = input("\n请输入项目名称 (如: 001_simple_project_runnable): ").strip()
        if project_name:
            data = merger.read_project_data(project_name)
            print(f"\n📊 项目数据读取结果:")
            print(f"   项目名称: {data['project_name']}")
            print(f"   基础项目名: {data['base_project_name']}")
            print(f"   Frontend文件: {'✅' if data['frontend_original'] else '❌'}")
            print(f"   Console logs: {'✅' if data['console_logs'] else '❌'}")
            if data['errors']:
                print(f"   错误: {len(data['errors'])}")
                for error in data['errors']:
                    print(f"     - {error}")
        else:
            print("❌ 请输入项目名称")
    
    elif choice == "4":
        # 查看摘要
        project_name = input("\n请输入项目名称 (如: 001_simple_project_runnable): ").strip()
        if project_name:
            summary = merger.get_console_logs_summary(project_name)
            if summary:
                print(f"\n📊 Console Logs 摘要:")
                print(f"   项目名称: {summary['project_name']}")
                print(f"   总任务数: {summary['total_tasks']}")
                print(f"   有日志的任务: {summary['tasks_with_logs']}")
                print(f"   有错误的任务: {summary['tasks_with_errors']}")
                print(f"   总日志条目: {summary['total_log_entries']}")
                print(f"   合并时间: {summary['merge_timestamp']}")
                print(f"   可用任务: {', '.join(summary['available_tasks'][:5])}{'...' if len(summary['available_tasks']) > 5 else ''}")
            else:
                print("❌ 未找到项目摘要")
        else:
            print("❌ 请输入项目名称")
    
    elif choice == "5":
        # 列出所有项目
        available = merger.list_available_projects()
        print(f"\n📋 Results Debug项目:")
        for project in available['results_debug_projects'][:10]:
            print(f"   - {project}")
        if len(available['results_debug_projects']) > 10:
            print(f"   ... 还有 {len(available['results_debug_projects']) - 10} 个项目")
        
        print(f"\n📋 已合并项目:")
        for project in available['merged_projects'][:10]:
            print(f"   - {project}")
        if len(available['merged_projects']) > 10:
            print(f"   ... 还有 {len(available['merged_projects']) - 10} 个项目")
    
    else:
        print("❌ 无效选择")

if __name__ == "__main__":
    main()
