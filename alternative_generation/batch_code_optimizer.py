#!/usr/bin/env python3
"""
批量代码优化器
Batch Code Optimizer

功能：
1. 使用console_logs_merger读取所有项目的JSX代码和console logs
2. 批量调用GPT-4对代码进行优化
3. 保存优化结果和处理记录
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# 导入现有的工具
sys.path.append(str(Path(__file__).parent))
from code_optimization_reader import CodeOptimizationDataReader
from api_client import UniversityAPIClient

class BatchCodeOptimizer:
    """批量代码优化器"""
    
    def __init__(self, 
                 output_dir: str = "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/optimized_code",
                 log_dir: str = "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/optimization_logs"):
        
        # 初始化工具
        self.reader = CodeOptimizationDataReader()
        self.api_client = UniversityAPIClient()
        
        # 设置输出目录
        self.output_dir = Path(output_dir)
        self.log_dir = Path(log_dir)
        
        # 创建目录
        self.output_dir.mkdir(exist_ok=True)
        self.log_dir.mkdir(exist_ok=True)
        
        # 处理状态
        self.processed_projects = set()
        self.failed_projects = set()
        self.optimization_results = {}
        
        # 加载之前的进度
        self._load_progress()
        
        print(f"📁 输出目录: {self.output_dir}")
        print(f"📁 日志目录: {self.log_dir}")
    
    def _load_progress(self):
        """加载之前的处理进度"""
        progress_file = self.log_dir / "optimization_progress.json"
        
        if progress_file.exists():
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
                
                self.processed_projects = set(progress.get('processed_projects', []))
                self.failed_projects = set(progress.get('failed_projects', []))
                self.optimization_results = progress.get('optimization_results', {})
                
                print(f"📂 加载进度: 已处理 {len(self.processed_projects)} 个项目")
                print(f"📂 失败项目: {len(self.failed_projects)} 个")
                
            except Exception as e:
                print(f"⚠️  加载进度失败: {e}")
    
    def _save_progress(self):
        """保存当前处理进度"""
        progress_file = self.log_dir / "optimization_progress.json"
        
        progress = {
            'timestamp': datetime.now().isoformat(),
            'processed_projects': list(self.processed_projects),
            'failed_projects': list(self.failed_projects),
            'optimization_results': self.optimization_results,
            'total_processed': len(self.processed_projects),
            'total_failed': len(self.failed_projects)
        }
        
        try:
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, indent=2, ensure_ascii=False)
            
            print(f"💾 进度已保存")
            
        except Exception as e:
            print(f"❌ 保存进度失败: {e}")
    
    def _create_optimization_prompt(self, project_name: str, frontend_code: str, console_logs: dict, error_analysis: dict) -> str:
        prompt = f"""

                    frontend jsx code:
                    ```jsx
                    {frontend_code}
                    ```

                    console_logs.json file:

                    ```json
                    {console_logs}
                    ```
                    """
        return prompt.strip()
    
    def _create_messages(self, prompt: str) -> List[Dict]:
        """
        创建GPT-4消息格式（留空，用户填充）
        
        Args:
            prompt: 优化提示词
        
        Returns:
            消息列表
        """
        # TODO: 用户需要在此处补全消息格式
        messages = [
            {
                "role": "system",
                "content": """You are an expert React developer specializing in JSX validation and debugging. Your task is to analyze JSX files against console logs to ensure complete functional alignment.

## Core Objectives:
1. **Validate** JSX functionality against recorded console logs
2. **Identify** discrepancies between expected behavior (logs) and actual implementation
3. **Repair** any bugs to achieve perfect alignment with console logs

## Analysis Process:

### Step 1: JSX Structure Analysis
- Verify React component structure and JSX syntax
- Validate all interactive elements (buttons, forms, inputs, etc.)
- Check element props, state variables, and refs referenced in logs
- Ensure proper component hierarchy and React patterns

### Step 2: Console Log Analysis  
- Parse console_logs.json to understand interaction sequence and timing
- Map each logged event to corresponding JSX elements or functions
- Identify required behaviors: state changes, function calls, renders, effects, error messages
- Note any dynamic content, prop changes, or lifecycle events

### Step 3: Bug Detection
Compare JSX implementation against console logs to identify:
- Missing state variables or incorrect state management
- Absent or faulty event handlers and functions
- Incorrect prop handling or component logic
- Missing useEffect hooks or lifecycle methods
- Broken component workflows or state updates

### Step 4: Bug Resolution
- Fix identified issues while preserving original component design
- Ensure all logged behaviors work exactly as recorded
- Maintain existing functionality not covered in logs
- Validate fixes don't introduce new issues

## Output Requirements:
- Return ONLY the JSX file (complete, functional code)
- **CRITICAL**: Maintain the exact same format as the input JSX file
- Modify ONLY the content and code logic, never the file structure or formatting
- Include ALL fixes needed for console log alignment
- If no bugs found, return original JSX unchanged  
- NO explanatory text, comments, or additional content
- File must be complete and ready for use

## Critical Constraints:
- Output must be a valid, complete JSX file
- Empty responses are not acceptable
- **DO NOT change the file format or structure - only modify code content**
- Preserve original formatting, indentation, and file organization
- Focus on functional accuracy to match console logs exactly"""
            },
            {
                "role": "user", 
                "content": prompt
            }
        ]
        
        return messages
    
    def optimize_single_project(self, project_name: str) -> Dict:
        """优化单个项目"""
        print(f"\n🎯 优化项目: {project_name}")
        print("-" * 50)
        
        result = {
            'project_name': project_name,
            'success': False,
            'original_code': None,
            'optimized_code': None,
            'console_logs': None,
            'error_analysis': None,
            'api_response': None,
            'errors': [],
            'start_time': datetime.now().isoformat(),
            'end_time': None
        }
        
        try:
            # 1. 读取项目数据
            print("📖 读取项目数据...")
            project_data = self.reader.get_project_data(project_name)
            
            if project_data.get('errors'):
                result['errors'].extend(project_data['errors'])
                print(f"❌ 读取数据时出错: {project_data['errors']}")
                return result
            
            frontend_code = project_data.get('frontend_original', '')
            console_logs = project_data.get('console_logs', {})
            
            if not frontend_code:
                error_msg = "未找到frontend代码"
                result['errors'].append(error_msg)
                print(f"❌ {error_msg}")
                return result
            
            if not console_logs:
                error_msg = "未找到console logs"
                result['errors'].append(error_msg)
                print(f"❌ {error_msg}")
                return result
            
            # 2. 分析项目问题
            print("📊 分析项目问题...")
            error_analysis = self.reader.analyze_project_issues(project_name)
            
            result['original_code'] = frontend_code
            result['console_logs'] = console_logs
            result['error_analysis'] = error_analysis
            
            print(f"✅ 代码长度: {len(frontend_code)} 字符")
            print(f"✅ 错误数量: {error_analysis.get('total_error_logs', 0)}")
            print(f"✅ 问题类型: {len(error_analysis.get('common_issues', []))}")
            
            # 3. 创建优化提示词
            print("💭 创建优化提示词...")
            prompt = self._create_optimization_prompt(
                project_name, frontend_code, console_logs, error_analysis
            )
            
            # 4. 创建消息格式
            messages = self._create_messages(prompt)
            
            # 5. 调用GPT-4进行优化
            print("🤖 调用GPT-4进行代码优化...")
            api_response = self.api_client.chat_completion(
                messages=messages,
                max_tokens=4000,
                temperature=0.1,
                top_p=0.9
            )
            
            result['api_response'] = api_response
            
            if api_response and 'choices' in api_response and api_response['choices']:
                optimized_code = api_response['choices'][0]['message']['content']
                result['optimized_code'] = optimized_code
                result['success'] = True
                
                print(f"✅ 优化完成，输出长度: {len(optimized_code)} 字符")
                
                # 6. 保存优化结果
                self._save_optimization_result(project_name, result)
                
            else:
                error_msg = "API响应格式异常"
                result['errors'].append(error_msg)
                print(f"❌ {error_msg}")
            
        except Exception as e:
            error_msg = f"优化过程异常: {str(e)}"
            result['errors'].append(error_msg)
            print(f"❌ {error_msg}")
        
        finally:
            result['end_time'] = datetime.now().isoformat()
        
        return result
    
    def _save_optimization_result(self, project_name: str, result: Dict):
        """保存单个项目的优化结果"""
        # 保存优化后的代码
        if result.get('optimized_code'):
            optimized_file = self.output_dir / f"{project_name}_optimized.jsx"
            try:
                with open(optimized_file, 'w', encoding='utf-8') as f:
                    f.write(result['optimized_code'])
                print(f"💾 优化代码已保存: {optimized_file}")
            except Exception as e:
                print(f"❌ 保存优化代码失败: {e}")
        
        # 保存详细结果
        result_file = self.log_dir / f"{project_name}_optimization_result.json"
        try:
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"💾 优化结果已保存: {result_file}")
        except Exception as e:
            print(f"❌ 保存优化结果失败: {e}")
    
    def batch_optimize_all_projects(self, 
                                   start_from: int = None, 
                                   max_projects: int = None,
                                   skip_existing: bool = True) -> Dict:
        """批量优化所有项目"""
        print("🚀 开始批量代码优化")
        print("=" * 60)
        
        # 获取所有可用项目
        available = self.reader.merger.list_available_projects()
        all_projects = available['results_debug_projects']
        
        # 过滤已处理的项目
        if skip_existing:
            remaining_projects = [p for p in all_projects if p not in self.processed_projects]
            print(f"📋 剩余待处理项目: {len(remaining_projects)}")
        else:
            remaining_projects = all_projects
            print(f"📋 总项目数: {len(remaining_projects)}")
        
        # 确定处理范围
        if start_from is not None:
            remaining_projects = remaining_projects[start_from-1:]
        
        if max_projects is not None:
            remaining_projects = remaining_projects[:max_projects]
        
        print(f"🎯 本次处理项目数: {len(remaining_projects)}")
        
        # 批量处理统计
        batch_stats = {
            'total_projects': len(remaining_projects),
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'results': {}
        }
        
        # 逐个处理项目
        for i, project_name in enumerate(remaining_projects, 1):
            print(f"\n{'='*60}")
            print(f"处理进度: [{i}/{len(remaining_projects)}] - {project_name}")
            print(f"{'='*60}")
            
            # 检查是否已处理过
            if project_name in self.processed_projects and skip_existing:
                print(f"⏭️  跳过已处理项目: {project_name}")
                batch_stats['skipped'] += 1
                continue
            
            # 优化单个项目
            result = self.optimize_single_project(project_name)
            batch_stats['results'][project_name] = result
            
            if result['success']:
                print(f"✅ 项目 {project_name} 优化成功")
                self.processed_projects.add(project_name)
                batch_stats['successful'] += 1
            else:
                print(f"❌ 项目 {project_name} 优化失败")
                self.failed_projects.add(project_name)
                batch_stats['failed'] += 1
            
            # 保存进度
            self.optimization_results[project_name] = result
            self._save_progress()
            
            # 添加延迟避免API限制
            if i < len(remaining_projects):
                print("⏳ 等待2秒...")
                time.sleep(2)
        
        # 完成统计
        batch_stats['end_time'] = datetime.now().isoformat()
        
        print(f"\n🎉 批量优化完成!")
        print("=" * 60)
        print(f"📊 处理统计:")
        print(f"   📝 总项目数: {batch_stats['total_projects']}")
        print(f"   ✅ 成功: {batch_stats['successful']}")
        print(f"   ❌ 失败: {batch_stats['failed']}")
        print(f"   ⏭️  跳过: {batch_stats['skipped']}")
        print(f"   📈 成功率: {batch_stats['successful']/batch_stats['total_projects']*100:.1f}%")
        
        # 保存批量处理结果
        batch_file = self.log_dir / f"batch_optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(batch_file, 'w', encoding='utf-8') as f:
                json.dump(batch_stats, f, indent=2, ensure_ascii=False)
            print(f"📄 批量结果已保存: {batch_file}")
        except Exception as e:
            print(f"❌ 保存批量结果失败: {e}")
        
        return batch_stats
    
    def get_optimization_summary(self) -> Dict:
        """获取优化工作总结"""
        return {
            'total_processed': len(self.processed_projects),
            'total_failed': len(self.failed_projects),
            'success_rate': len(self.processed_projects) / (len(self.processed_projects) + len(self.failed_projects)) * 100 if (len(self.processed_projects) + len(self.failed_projects)) > 0 else 0,
            'processed_projects': list(self.processed_projects),
            'failed_projects': list(self.failed_projects),
            'output_directory': str(self.output_dir),
            'log_directory': str(self.log_dir)
        }
    
    def retry_failed_projects(self) -> Dict:
        """重试失败的项目"""
        if not self.failed_projects:
            print("🎉 没有失败的项目需要重试")
            return {'message': 'No failed projects to retry'}
        
        print(f"🔄 重试 {len(self.failed_projects)} 个失败的项目")
        
        failed_list = list(self.failed_projects)
        self.failed_projects.clear()  # 清空失败列表，重新尝试
        
        return self.batch_optimize_all_projects(skip_existing=False)

def main():
    """主函数 - 演示用法"""
    print("🚀 批量代码优化器")
    print("=" * 60)
    
    # 创建优化器
    optimizer = BatchCodeOptimizer()
    
    # 显示当前状态
    summary = optimizer.get_optimization_summary()
    print(f"\n📊 当前状态:")
    print(f"   已处理项目: {summary['total_processed']}")
    print(f"   失败项目: {summary['total_failed']}")
    if summary['total_processed'] + summary['total_failed'] > 0:
        print(f"   成功率: {summary['success_rate']:.1f}%")
    
    # 询问用户操作
    print(f"\n请选择操作:")
    print(f"1. 批量优化所有项目")
    print(f"2. 优化单个项目")
    print(f"3. 重试失败的项目")
    print(f"4. 查看优化总结")
    print(f"5. 测试单个项目（不调用API）")
    
    choice = input("\n请输入选择 (1-5): ").strip()
    
    if choice == "1":
        # 批量优化
        start_from = input("从第几个项目开始（回车跳过）: ").strip()
        start_from = int(start_from) if start_from else None
        
        max_projects = input("最多处理几个项目（回车为全部）: ").strip()
        max_projects = int(max_projects) if max_projects else None
        
        optimizer.batch_optimize_all_projects(
            start_from=start_from,
            max_projects=max_projects
        )
    
    elif choice == "2":
        # 单个项目优化
        project_name = input("请输入项目名称 (如: 001_simple_project_runnable): ").strip()
        if project_name:
            result = optimizer.optimize_single_project(project_name)
            print(f"\n📊 优化结果:")
            print(f"   成功: {'✅' if result['success'] else '❌'}")
            if result['errors']:
                print(f"   错误: {result['errors']}")
        else:
            print("❌ 请输入项目名称")
    
    elif choice == "3":
        # 重试失败项目
        optimizer.retry_failed_projects()
    
    elif choice == "4":
        # 查看总结
        summary = optimizer.get_optimization_summary()
        print(f"\n📊 优化工作总结:")
        print(f"   已处理: {summary['total_processed']} 个项目")
        print(f"   失败: {summary['total_failed']} 个项目")
        print(f"   成功率: {summary['success_rate']:.1f}%")
        print(f"   输出目录: {summary['output_directory']}")
        print(f"   日志目录: {summary['log_directory']}")
        
        if summary['failed_projects']:
            print(f"\n❌ 失败项目:")
            for project in summary['failed_projects'][:10]:
                print(f"     - {project}")
            if len(summary['failed_projects']) > 10:
                print(f"     ... 还有 {len(summary['failed_projects']) - 10} 个")
    
    elif choice == "5":
        # 测试单个项目（不调用API）
        project_name = input("请输入项目名称 (如: 001_simple_project_runnable): ").strip()
        if project_name:
            print(f"\n🧪 测试项目: {project_name}")
            
            # 读取数据
            project_data = optimizer.reader.get_project_data(project_name)
            error_analysis = optimizer.reader.analyze_project_issues(project_name)
            
            # 创建提示词
            if project_data.get('frontend_original') and project_data.get('console_logs'):
                prompt = optimizer._create_optimization_prompt(
                    project_name,
                    project_data['frontend_original'],
                    project_data['console_logs'],
                    error_analysis
                )
                
                print(f"\n📝 生成的提示词:")
                print("-" * 50)
                print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
                print("-" * 50)
                
                messages = optimizer._create_messages(prompt)
                print(f"\n💬 消息格式:")
                print(f"   消息数量: {len(messages)}")
                print(f"   系统提示长度: {len(messages[0]['content'])}")
                print(f"   用户提示长度: {len(messages[1]['content'])}")
            else:
                print("❌ 无法读取项目数据")
        else:
            print("❌ 请输入项目名称")
    
    else:
        print("❌ 无效选择")

if __name__ == "__main__":
    main()
