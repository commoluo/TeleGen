#!/usr/bin/env python3
"""
代码优化数据读取器
Code Optimization Data Reader

专门用于读取frontend_original.jsx和对应的console_logs.json文件
为后续的代码优化工作提供数据支持
"""

import os
import sys
from pathlib import Path
from typing import Dict, List

# 添加当前目录到路径
sys.path.append(str(Path(__file__).parent))

from console_logs_merger import ConsoleLogsMerger

class CodeOptimizationDataReader:
    """代码优化数据读取器"""
    
    def __init__(self,
                 results_debug_dir: str = None,
                 debug_projects_dir: str = None,
                 merged_logs_dir: str = None):
        self.merger = ConsoleLogsMerger(
            results_debug_dir=results_debug_dir,
            debug_projects_dir=debug_projects_dir,
            output_dir=merged_logs_dir
        )
        self.ensure_merged_data()
    
    def ensure_merged_data(self):
        """确保console logs数据已合并"""
        available = self.merger.list_available_projects()
        
        # 如果没有合并数据，或者合并数据少于原始数据，则重新合并
        if (available['total_merged_projects'] == 0 or 
            available['total_merged_projects'] < available['total_results_projects']):
            print("🔄 正在合并console logs数据...")
            self.merger.merge_all_projects()
    
    def get_project_data(self, project_name: str) -> dict:
        """获取项目的完整数据（frontend代码 + console logs）"""
        return self.merger.read_project_data(project_name)
    
    def get_frontend_code(self, project_name: str) -> str:
        """只获取frontend代码"""
        data = self.get_project_data(project_name)
        return data.get('frontend_original', '')
    
    def get_console_logs(self, project_name: str) -> dict:
        """只获取console logs"""
        data = self.get_project_data(project_name)
        return data.get('console_logs', {})
    
    def get_error_logs_from_console(self, project_name: str) -> list:
        """从console logs中提取错误信息"""
        console_logs = self.get_console_logs(project_name)
        errors = []
        
        if not console_logs or 'console_logs_by_task' not in console_logs:
            return errors
        
        for task_name, task_data in console_logs['console_logs_by_task'].items():
            if 'console_logs' in task_data:
                logs = task_data['console_logs']
                if isinstance(logs, list):
                    for log_entry in logs:
                        if isinstance(log_entry, dict):
                            # 检查是否是错误日志
                            level = log_entry.get('level', '').lower()
                            message = log_entry.get('message', '')
                            
                            if level in ['error', 'warn', 'warning'] or 'error' in message.lower():
                                errors.append({
                                    'task': task_name,
                                    'level': level,
                                    'message': message,
                                    'timestamp': log_entry.get('timestamp'),
                                    'source': log_entry.get('source', 'console')
                                })

            # 额外解析文本日志（如 frontend_npm_install_failure_log.txt）
            for text_log in task_data.get('text_logs', []):
                file_name = text_log.get('file_name', '')
                content_lines = text_log.get('content', [])
                if not isinstance(content_lines, list):
                    continue

                joined = "\n".join(content_lines)
                lower_joined = joined.lower()
                has_failure_file = 'failure_log' in file_name.lower()
                has_text_error = any(
                    keyword in lower_joined
                    for keyword in [
                        'npm err!',
                        'eresolve',
                        'could not resolve dependency',
                        'module not found',
                        'syntaxerror',
                        'typeerror',
                        'referenceerror',
                        'process exited unexpectedly',
                        'build failed',
                        'frontend npm install failed',
                        'backend process exited unexpectedly',
                    ]
                )

                if has_failure_file or has_text_error:
                    headline = ''
                    for line in content_lines:
                        line_lower = str(line).lower()
                        if any(k in line_lower for k in ['npm err!', 'eresolve', 'error message:', 'syntaxerror', 'typeerror', 'referenceerror', 'exited unexpectedly']):
                            headline = str(line).strip()
                            break
                    if not headline:
                        headline = f"文本日志存在失败线索: {file_name}"

                    errors.append({
                        'task': task_name,
                        'level': 'error',
                        'message': headline,
                        'timestamp': None,
                        'source': f'text_log:{file_name}'
                    })
        
        return errors
    
    def analyze_project_issues(self, project_name: str) -> dict:
        """分析项目的主要问题"""
        data = self.get_project_data(project_name)
        errors = self.get_error_logs_from_console(project_name)
        
        analysis = {
            'project_name': project_name,
            'has_frontend_code': bool(data.get('frontend_original')),
            'has_console_logs': bool(data.get('console_logs')),
            'total_error_logs': len(errors),
            'error_types': {},
            'common_issues': [],
            'recommendations': []
        }
        
        # 分析错误类型
        for error in errors:
            level = error.get('level', 'unknown')
            if level not in analysis['error_types']:
                analysis['error_types'][level] = 0
            analysis['error_types'][level] += 1
        
        # 识别常见问题
        error_messages = [error.get('message', '') for error in errors]
        
        # 检查常见的React/JavaScript错误
        common_patterns = {
            'module_not_found': ['module not found', 'cannot resolve module'],
            'syntax_error': ['syntaxerror', 'unexpected token'],
            'type_error': ['typeerror', 'cannot read property'],
            'reference_error': ['referenceerror', 'is not defined'],
            'network_error': ['network error', 'fetch failed', 'cors'],
            'build_error': ['build failed', 'compilation error'],
            'npm_install_error': ['npm err!', 'npm install failed', 'eresolve'],
            'dependency_conflict': ['could not resolve dependency', 'conflicting peer dependency', 'peeroptional typescript']
        }
        
        for issue_type, patterns in common_patterns.items():
            count = 0
            for message in error_messages:
                if any(pattern in message.lower() for pattern in patterns):
                    count += 1
            
            if count > 0:
                analysis['common_issues'].append({
                    'type': issue_type,
                    'count': count,
                    'description': issue_type.replace('_', ' ').title()
                })
        
        # 生成建议
        if analysis['total_error_logs'] == 0:
            analysis['recommendations'].append("✅ 没有发现明显的错误日志")
        else:
            if any(issue['type'] == 'module_not_found' for issue in analysis['common_issues']):
                analysis['recommendations'].append("🔧 检查模块导入和依赖安装")
            
            if any(issue['type'] == 'syntax_error' for issue in analysis['common_issues']):
                analysis['recommendations'].append("🔧 修复JavaScript语法错误")
            
            if any(issue['type'] == 'build_error' for issue in analysis['common_issues']):
                analysis['recommendations'].append("🔧 修复构建配置问题")

            if any(issue['type'] == 'npm_install_error' for issue in analysis['common_issues']):
                analysis['recommendations'].append("🔧 修复 npm 安装失败（优先检查 package.json 依赖冲突）")

            if any(issue['type'] == 'dependency_conflict' for issue in analysis['common_issues']):
                analysis['recommendations'].append("🔧 解决 peer dependency 冲突（如 react-scripts 与 typescript 版本）")
        
        return analysis
    
    def get_optimization_data_for_batch(self, project_names: list) -> dict:
        """批量获取优化数据"""
        batch_data = {
            'total_projects': len(project_names),
            'successful_reads': 0,
            'failed_reads': 0,
            'projects': {}
        }
        
        for project_name in project_names:
            try:
                data = self.get_project_data(project_name)
                analysis = self.analyze_project_issues(project_name)
                
                batch_data['projects'][project_name] = {
                    'data': data,
                    'analysis': analysis,
                    'success': len(data.get('errors', [])) == 0
                }
                
                if batch_data['projects'][project_name]['success']:
                    batch_data['successful_reads'] += 1
                else:
                    batch_data['failed_reads'] += 1
                    
            except Exception as e:
                batch_data['projects'][project_name] = {
                    'error': str(e),
                    'success': False
                }
                batch_data['failed_reads'] += 1
        
        return batch_data

def main():
    """演示使用方法"""
    print("🚀 代码优化数据读取器")
    print("=" * 50)
    
    reader = CodeOptimizationDataReader()
    
    # 演示读取单个项目
    project_name = "001_simple_project_runnable"
    print(f"\n📖 读取项目: {project_name}")
    
    # 获取完整数据
    data = reader.get_project_data(project_name)
    print(f"✅ Frontend代码: {len(data.get('frontend_original', ''))} 字符")
    print(f"✅ Console logs: {bool(data.get('console_logs'))}")
    
    # 分析问题
    analysis = reader.analyze_project_issues(project_name)
    print(f"\n📊 问题分析:")
    print(f"   错误日志数: {analysis['total_error_logs']}")
    print(f"   常见问题: {len(analysis['common_issues'])}")
    
    for issue in analysis['common_issues']:
        print(f"     - {issue['description']}: {issue['count']} 次")
    
    print(f"\n💡 建议:")
    for recommendation in analysis['recommendations']:
        print(f"   {recommendation}")
    
    # 演示批量处理
    print(f"\n📦 批量处理示例:")
    projects = ["001_simple_project_runnable", "002_simple_project_runnable", "003_simple_project_runnable"]
    batch_data = reader.get_optimization_data_for_batch(projects)
    
    print(f"   总项目数: {batch_data['total_projects']}")
    print(f"   成功读取: {batch_data['successful_reads']}")
    print(f"   失败读取: {batch_data['failed_reads']}")

if __name__ == "__main__":
    main()
