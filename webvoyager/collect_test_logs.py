#!/usr/bin/env python3
"""
WebVoyager 测试日志收集器
收集所有已完成测试的日志信息，按照页面ID_操作ID分类整理
"""

import os
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
from collections import defaultdict
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TestLogCollector:
    """测试日志收集器"""
    
    def __init__(self, results_dir: str = "webvoyager_results"):
        self.results_dir = Path(results_dir)
        self.collected_logs = defaultdict(dict)
        self.summary_stats = {
            'total_tasks': 0,
            'tasks_with_console_logs': 0,
            'tasks_with_interaction_logs': 0,
            'tasks_with_screenshots': 0,
            'total_console_errors': 0,
            'total_interactions': 0
        }
        
    def collect_all_logs(self) -> Dict[str, Any]:
        """收集所有测试日志"""
        logger.info(f"开始收集测试日志，扫描目录: {self.results_dir}")
        
        if not self.results_dir.exists():
            logger.error(f"结果目录不存在: {self.results_dir}")
            return {}
        
        # 遍历所有项目目录
        for project_dir in sorted(self.results_dir.iterdir()):
            if not project_dir.is_dir() or project_dir.name.startswith('.'):
                continue
                
            logger.info(f"处理项目: {project_dir.name}")
            self._process_project(project_dir)
        
        # 生成汇总统计
        self._generate_summary()
        
        return self.collected_logs
    
    def _process_project(self, project_dir: Path):
        """处理单个项目目录"""
        for task_dir in sorted(project_dir.iterdir()):
            if not task_dir.is_dir():
                continue
                
            task_id = f"{project_dir.name}_{task_dir.name}"
            logger.debug(f"处理任务: {task_id}")
            
            self.summary_stats['total_tasks'] += 1
            
            # 收集该任务的所有日志
            task_logs = self._collect_task_logs(task_dir, task_id)
            if task_logs:
                self.collected_logs[task_id] = task_logs
    
    def _collect_task_logs(self, task_dir: Path, task_id: str) -> Dict[str, Any]:
        """收集单个任务的所有日志"""
        task_logs = {
            'task_id': task_id,
            'project_dir': task_dir.parent.name,
            'task_dir': task_dir.name,
            'console_logs': [],
            'interaction_logs': [],
            'screenshots': [],
            'other_files': [],
            'metadata': {}
        }
        
        # 收集控制台日志
        console_log_file = task_dir / "console_logs.json"
        if console_log_file.exists():
            try:
                with open(console_log_file, 'r', encoding='utf-8') as f:
                    console_logs = json.load(f)
                    task_logs['console_logs'] = console_logs
                    self.summary_stats['tasks_with_console_logs'] += 1
                    self.summary_stats['total_console_errors'] += len(console_logs)
            except Exception as e:
                logger.warning(f"读取控制台日志失败 {console_log_file}: {e}")
        
        # 收集交互日志
        interaction_log_file = task_dir / "interaction_logs.json"
        if interaction_log_file.exists():
            try:
                with open(interaction_log_file, 'r', encoding='utf-8') as f:
                    interaction_logs = json.load(f)
                    task_logs['interaction_logs'] = interaction_logs
                    self.summary_stats['tasks_with_interaction_logs'] += 1
                    if isinstance(interaction_logs, list):
                        self.summary_stats['total_interactions'] += len(interaction_logs)
            except Exception as e:
                logger.warning(f"读取交互日志失败 {interaction_log_file}: {e}")
        
        # 收集截图文件
        for screenshot_file in task_dir.glob("screenshot_*.png"):
            task_logs['screenshots'].append({
                'filename': screenshot_file.name,
                'path': str(screenshot_file),
                'size': screenshot_file.stat().st_size if screenshot_file.exists() else 0
            })
        
        if task_logs['screenshots']:
            self.summary_stats['tasks_with_screenshots'] += 1
        
        # 收集其他文件
        for other_file in task_dir.iterdir():
            if other_file.is_file() and other_file.suffix not in ['.json', '.png']:
                task_logs['other_files'].append({
                    'filename': other_file.name,
                    'path': str(other_file),
                    'size': other_file.stat().st_size
                })
        
        # 添加元数据
        task_logs['metadata'] = {
            'collected_at': datetime.now().isoformat(),
            'console_log_count': len(task_logs['console_logs']),
            'interaction_count': len(task_logs['interaction_logs']),
            'screenshot_count': len(task_logs['screenshots']),
            'other_file_count': len(task_logs['other_files'])
        }
        
        return task_logs
    
    def _generate_summary(self):
        """生成汇总统计"""
        logger.info("生成汇总统计...")
        
        # 按错误类型统计
        error_categories = defaultdict(int)
        interaction_types = defaultdict(int)
        
        for task_id, task_logs in self.collected_logs.items():
            # 统计控制台错误类型
            for log_entry in task_logs['console_logs']:
                error_type = self._categorize_console_error(log_entry.get('message', ''))
                error_categories[error_type] += 1
            
            # 统计交互类型
            for interaction in task_logs['interaction_logs']:
                if isinstance(interaction, dict):
                    action_type = interaction.get('type', 'unknown')
                    interaction_types[action_type] += 1
        
        self.summary_stats['error_categories'] = dict(error_categories)
        self.summary_stats['interaction_types'] = dict(interaction_types)
    
    def _categorize_console_error(self, message: str) -> str:
        """分类控制台错误"""
        message_lower = message.lower()
        
        if 'failed to load resource' in message_lower:
            if '404' in message:
                return "404_资源未找到"
            elif '500' in message:
                return "500_服务器错误"
            else:
                return "网络加载失败"
        elif 'reactdom.render' in message_lower and 'no longer supported' in message_lower:
            return "React18兼容性警告"
        elif 'cors' in message_lower:
            return "跨域错误"
        elif any(err in message_lower for err in ['syntaxerror', 'referenceerror', 'typeerror']):
            return "JavaScript错误"
        elif 'warning' in message_lower:
            return "警告信息"
        else:
            return "其他错误"
    
    def save_collected_logs(self, output_file: str = None):
        """保存收集的日志到文件"""
        if not output_file:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"collected_test_logs_{timestamp}.json"
        
        output_path = self.results_dir / output_file
        
        # 准备输出数据
        output_data = {
            'collection_info': {
                'collected_at': datetime.now().isoformat(),
                'total_tasks_found': len(self.collected_logs),
                'collection_summary': self.summary_stats
            },
            'logs_by_task': self.collected_logs
        }
        
        # 保存 JSON 格式
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"收集的日志已保存到: {output_path}")
        
        # 同时保存 CSV 格式的摘要
        self._save_csv_summary(output_path.with_suffix('.csv'))
        
        return output_path
    
    def _save_csv_summary(self, csv_path: Path):
        """保存CSV格式的摘要"""
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入表头
            writer.writerow([
                'Task_ID', 'Project', 'Task_Name', 
                'Console_Logs_Count', 'Interaction_Logs_Count', 'Screenshots_Count',
                'Main_Error_Types', 'Has_Network_Errors', 'Has_React_Warnings'
            ])
            
            # 写入数据
            for task_id, task_logs in self.collected_logs.items():
                console_count = len(task_logs['console_logs'])
                interaction_count = len(task_logs['interaction_logs'])
                screenshot_count = len(task_logs['screenshots'])
                
                # 分析主要错误类型
                error_types = set()
                has_network_errors = False
                has_react_warnings = False
                
                for log_entry in task_logs['console_logs']:
                    message = log_entry.get('message', '').lower()
                    error_type = self._categorize_console_error(message)
                    error_types.add(error_type)
                    
                    if 'failed to load resource' in message or '404' in message:
                        has_network_errors = True
                    if 'reactdom.render' in message and 'no longer supported' in message:
                        has_react_warnings = True
                
                writer.writerow([
                    task_id,
                    task_logs['project_dir'],
                    task_logs['task_dir'],
                    console_count,
                    interaction_count,
                    screenshot_count,
                    '; '.join(sorted(error_types)),
                    'Yes' if has_network_errors else 'No',
                    'Yes' if has_react_warnings else 'No'
                ])
        
        logger.info(f"CSV摘要已保存到: {csv_path}")
    
    def print_summary(self):
        """打印收集摘要"""
        print(f"\n📊 测试日志收集摘要")
        print(f"{'='*50}")
        print(f"总任务数: {self.summary_stats['total_tasks']}")
        print(f"包含控制台日志的任务: {self.summary_stats['tasks_with_console_logs']}")
        print(f"包含交互日志的任务: {self.summary_stats['tasks_with_interaction_logs']}")
        print(f"包含截图的任务: {self.summary_stats['tasks_with_screenshots']}")
        print(f"总控制台错误数: {self.summary_stats['total_console_errors']}")
        print(f"总交互次数: {self.summary_stats['total_interactions']}")
        
        if 'error_categories' in self.summary_stats:
            print(f"\n🔥 错误类型分布:")
            for error_type, count in sorted(self.summary_stats['error_categories'].items(), 
                                          key=lambda x: x[1], reverse=True):
                print(f"  {error_type}: {count}")
        
        if 'interaction_types' in self.summary_stats:
            print(f"\n🖱️ 交互类型分布:")
            for interaction_type, count in sorted(self.summary_stats['interaction_types'].items(), 
                                                key=lambda x: x[1], reverse=True):
                print(f"  {interaction_type}: {count}")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="收集WebVoyager测试日志")
    parser.add_argument("--results_dir", type=str, default="webvoyager_results",
                       help="测试结果目录路径")
    parser.add_argument("--output_file", type=str,
                       help="输出文件名（默认自动生成时间戳）")
    parser.add_argument("--verbose", action="store_true",
                       help="详细输出")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 创建收集器并执行收集
    collector = TestLogCollector(args.results_dir)
    collected_logs = collector.collect_all_logs()
    
    # 保存结果
    output_path = collector.save_collected_logs(args.output_file)
    
    # 打印摘要
    collector.print_summary()
    
    print(f"\n✅ 日志收集完成！")
    print(f"📁 结果文件: {output_path}")
    print(f"📄 CSV摘要: {output_path.with_suffix('.csv')}")

if __name__ == "__main__":
    main()
