#!/usr/bin/env python3
"""
批量优化 fullstack 项目的 frontend.jsx 文件
用法：python optimize_fullstack_projects.py [options]
"""
import os
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime
import sys

# Import API clients
from api_client import UniversityAPIClient
from multi_api_client import MultiAPIClient
from api_config import get_best_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('debug_logging_projects.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ProjectOptimizer:
    """fullstack 项目优化器"""
    
    def __init__(self, base_dir: str, output_dir: str = None, optimization_prompt: str = None, use_multi_api: bool = False):
        self.base_dir = Path(base_dir)
        self.output_dir = Path(output_dir) if output_dir else self.base_dir / "debug_logged_projects"
        self.processed_projects = []
        self.failed_projects = []
        self.optimization_prompt = optimization_prompt
        self.use_multi_api = use_multi_api
        
        # 初始化 AI 客户端 - 默认使用学校API
        if use_multi_api:
            try:
                self.ai_client = MultiAPIClient()
                logger.info("使用多API客户端")
            except Exception as e:
                logger.warning(f"多API客户端初始化失败，回退到大学API客户端: {e}")
                self.ai_client = UniversityAPIClient()
        else:
            self.ai_client = UniversityAPIClient()
            logger.info("使用大学API客户端")
        
    def find_fullstack_projects(self) -> List[Path]:
        """扫描并找到所有 fullstack 项目目录"""
        projects = []
        
        # 查找 organized_runs 目录
        organized_runs_dir = self.base_dir / "generated_websites"  / "organized_runs"
        
        if organized_runs_dir.exists() and organized_runs_dir.is_dir():
            logger.info(f"扫描目录: {organized_runs_dir}")
            for project_dir in organized_runs_dir.iterdir():
                if project_dir.is_dir() and self.is_valid_project(project_dir):
                    projects.append(project_dir)
                    logger.debug(f"找到有效项目: {project_dir}")
        else:
            logger.warning(f"目录不存在或不是一个目录: {organized_runs_dir}")
        
        logger.info(f"找到 {len(projects)} 个有效项目")
        return sorted(projects)
    
    def is_valid_project(self, project_dir: Path) -> bool:
        """检查是否为有效的项目目录"""
        frontend_file = project_dir / "frontend.jsx"
        return frontend_file.exists()
    
    def read_frontend_content(self, project_dir: Path) -> Optional[str]:
        """读取项目的 frontend.jsx 文件内容"""
        frontend_file = project_dir / "frontend.jsx"
        try:
            with open(frontend_file, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.debug(f"成功读取 {project_dir.name}/frontend.jsx")
            return content
        except Exception as e:
            logger.error(f"读取 {frontend_file} 失败: {e}")
            return None
    
    def analyze_project_structure(self, content: str) -> Dict[str, Any]:
        """分析项目结构和组件"""
        analysis = {
            'has_package_json': 'package.json' in content,
            'has_components': 'components/' in content,
            'has_styles': 'styles/' in content or '.css' in content,
            'has_api_calls': 'axios' in content or 'fetch' in content,
            'react_version': self.extract_react_version(content),
            'dependencies': self.extract_dependencies(content),
            'components_count': content.count('const ') + content.count('function '),
            'lines_count': len(content.split('\n')),
            'file_size_kb': len(content.encode('utf-8')) / 1024
        }
        return analysis
    
    def extract_react_version(self, content: str) -> str:
        """提取 React 版本信息"""
        import re
        version_match = re.search(r'"react":\s*"([^"]+)"', content)
        return version_match.group(1) if version_match else "unknown"
    
    def extract_dependencies(self, content: str) -> List[str]:
        """提取项目依赖"""
        import re
        # 从 package.json 部分提取依赖
        deps_match = re.search(r'"dependencies":\s*{([^}]+)}', content)
        if deps_match:
            deps_text = deps_match.group(1)
            deps = re.findall(r'"([^"]+)":', deps_text)
            return deps
        return []
    
    def optimize_with_ai(self, content: str, project_name: str, analysis: Dict[str, Any]) -> str:
        """使用大模型优化代码"""
        logger.info(f"开始优化项目: {project_name}")
        
        try:
            # 构建优化提示
            messages = [
                {
                    "role": "system",
                    "content": """You are a web development expert (HTML/CSS/JS/React). Your job is to instrument Javascript/JSX code with console.log statements.
                                The provided file content contains multiple distinct blocks, such as package.json, HTML, CSS, and Javascript/JSX.
                                Your task is to add console.log statements ONLY to the Javascript/JSX code blocks and return the ENTIRE file content, including all original, unmodified blocks (package.json, HTML, CSS, etc.).

                                Follow these global rules strictly:
                                1) Preserve the original file structure and all code blocks. Do NOT remove or alter the package.json, HTML, or CSS sections.
                                2) In the Javascript/JSX sections, add logs for every interactive element (incl. backend API interactions), page load/unload, important DOM ops (show/hide, style/content updates), and possible errors.
                                3) Each log has a clear tag prefix (provided by user).
                                4) Do NOT log objects; if multiple variables, print them as strings: "[TAG] key1=", v1, " key2=", v2.
                                5) Do not change behavior, imports, props, state, or event semantics; do not add dependencies.
                                6) Return the complete, full file content with only the required console.log statements added. Do not add any explanations or markdown.
                                If constraints conflict, preserving the original file structure and behavior is the highest priority.
                                """
                },
                {
                    "role": "user",
                    "content": f"""Instrument the provided file content. 
                                Use tag prefix: [TRACE]. The main interactive points are: click handlers, form submissions, route changes, 
                                and calls to /api/*. Ensure before/after state (selected ids, input values, visibility flags) is logged where applicable. 
                                Apply the logging rules defined in the system prompt. Return the complete modified file content with the console.log statements inserted, preserving all original functionality and structure.
                                
                                Here is the content:
                                {content}
                                """
                }

            ]
            
            # 调用 AI API
            if hasattr(self.ai_client, 'chat_completion'):
                # 使用 UniversityAPIClient
                response = self.ai_client.chat_completion(
                    messages=messages,
                    max_tokens=8000,
                    temperature=0.3
                )
                
                if "error" in response:
                    logger.error(f"AI API 调用失败: {response['error']['message']}")
                    return self.apply_basic_optimizations(content, analysis)
                
                if "choices" in response and len(response["choices"]) > 0:
                    optimized_content = response["choices"][0].get("message", {}).get("content", "")
                    if optimized_content.strip():
                        logger.info(f"项目 {project_name} AI优化完成")
                        return optimized_content
                    else:
                        logger.warning(f"AI返回空内容，使用基础优化")
                        return self.apply_basic_optimizations(content, analysis)
                
            elif hasattr(self.ai_client, 'client'):
                # 使用 MultiAPIClient
                response = self.ai_client.client.chat.completions.create(
                    model=self.ai_client.model,
                    messages=messages,
                    max_tokens=8000,
                    temperature=0.3
                )
                
                if response.choices and len(response.choices) > 0:
                    optimized_content = response.choices[0].message.content
                    if optimized_content and optimized_content.strip():
                        logger.info(f"项目 {project_name} AI优化完成")
                        return optimized_content
                    else:
                        logger.warning(f"AI返回空内容，使用基础优化")
                        return self.apply_basic_optimizations(content, analysis)
            
            logger.warning(f"未知的AI客户端类型，使用基础优化")
            return self.apply_basic_optimizations(content, analysis)
            
        except Exception as e:
            logger.error(f"AI优化过程中出现错误: {str(e)}")
            logger.info(f"回退到基础优化策略")
            return self.apply_basic_optimizations(content, analysis)
    
    def apply_basic_optimizations(self, content: str, analysis: Dict[str, Any]) -> str:
        """应用基础优化（不依赖大模型的预处理）"""
        # 基础优化示例：
        # 1. 添加缺失的 PropTypes
        # 2. 统一代码格式
        # 3. 添加基本的错误边界
        
        optimized = content
        
        # 示例：确保有错误处理
        if 'catch' not in content:
            logger.info("添加基础错误处理")
            # 这里可以添加一些基础的错误处理代码
        
        return optimized
    
    def save_optimized_project(self, project_name: str, original_content: str, 
                             optimized_content: str, analysis: Dict[str, Any]) -> bool:
        """保存优化后的项目"""
        try:
            # 创建输出目录
            output_project_dir = self.output_dir / project_name
            output_project_dir.mkdir(parents=True, exist_ok=True)
            
            # 保存优化后的文件
            optimized_file = output_project_dir / "frontend_with_debug_logs.jsx"
            with open(optimized_file, 'w', encoding='utf-8') as f:
                f.write(optimized_content)
            
            # 保存原始文件作为对比
            original_file = output_project_dir / "frontend_original.jsx"
            with open(original_file, 'w', encoding='utf-8') as f:
                f.write(original_content)
            
            # 保存分析报告
            analysis_file = output_project_dir / "analysis_report.json"
            with open(analysis_file, 'w', encoding='utf-8') as f:
                json.dump(analysis, f, indent=2, ensure_ascii=False)
            
            logger.info(f"项目 {project_name} 保存完成: {output_project_dir}")
            return True
            
        except Exception as e:
            logger.error(f"保存项目 {project_name} 失败: {e}")
            return False
    
    def process_single_project(self, project_dir: Path) -> Dict[str, Any]:
        """处理单个项目"""
        project_name = project_dir.name
        result = {
            'project_name': project_name,
            'project_path': str(project_dir),
            'status': 'unknown',
            'error': None,
            'analysis': None,
            'optimized': False
        }
        
        try:
            # 读取文件内容
            content = self.read_frontend_content(project_dir)
            if not content:
                result['status'] = 'read_failed'
                result['error'] = 'Failed to read frontend.jsx'
                return result
            
            # 分析项目
            analysis = self.analyze_project_structure(content)
            analysis['project_name'] = project_name
            analysis['original_path'] = str(project_dir)
            result['analysis'] = analysis
            
            # 使用 AI 优化
            optimized_content = self.optimize_with_ai(content, project_name, analysis)
            
            # 保存结果
            if self.save_optimized_project(project_name, content, optimized_content, analysis):
                result['status'] = 'success'
                result['optimized'] = True
                self.processed_projects.append(result)
            else:
                result['status'] = 'save_failed'
                self.failed_projects.append(result)
                
        except Exception as e:
            logger.error(f"处理项目 {project_name} 时出错: {e}")
            result['status'] = 'error'
            result['error'] = str(e)
            self.failed_projects.append(result)
        
        return result
    
    def process_all_projects(self) -> Dict[str, Any]:
        """批量处理所有项目"""
        logger.info("开始批量处理项目...")
        
        projects = self.find_fullstack_projects()
        if not projects:
            logger.warning("未找到任何有效项目")
            return {'total': 0, 'processed': 0, 'failed': 0}
        
        total_projects = len(projects)
        logger.info(f"准备处理 {total_projects} 个项目")
        
        # 处理每个项目
        for i, project_dir in enumerate(projects, 1):
            logger.info(f"处理进度: {i}/{total_projects} - {project_dir.name}")
            self.process_single_project(project_dir)
        
        # 生成总结报告
        summary = self.generate_summary_report()
        logger.info(f"批量处理完成: 成功 {len(self.processed_projects)}, 失败 {len(self.failed_projects)}")
        
        return summary
    
    def generate_summary_report(self) -> Dict[str, Any]:
        """生成总结报告"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        summary = {
            'timestamp': timestamp,
            'total_projects': len(self.processed_projects) + len(self.failed_projects),
            'successful_projects': len(self.processed_projects),
            'failed_projects': len(self.failed_projects),
            'success_rate': len(self.processed_projects) / (len(self.processed_projects) + len(self.failed_projects)) * 100 if (len(self.processed_projects) + len(self.failed_projects)) > 0 else 0,
            'processed_details': self.processed_projects,
            'failed_details': self.failed_projects
        }
        
        # 保存总结报告
        summary_file = self.output_dir / f"debug_logging_summary_{timestamp}.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        logger.info(f"总结报告已保存: {summary_file}")
        return summary

def main():
    parser = argparse.ArgumentParser(description="批量为 fullstack 项目添加调试日志")
    parser.add_argument("--base_dir", type=str, 
                       default="/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation",
                       help="项目根目录")
    parser.add_argument("--output_dir", type=str, 
                       help="处理后项目输出目录")
    parser.add_argument("--project_filter", type=str, 
                       help="项目名称过滤器（正则表达式）")
    parser.add_argument("--use_multi_api", action="store_true", default=False,
                       help="使用多API客户端")
    parser.add_argument("--use_university_api", action="store_true", default=True,
                       help="使用大学API客户端（默认启用）")
    parser.add_argument("--dry_run", action="store_true",
                       help="试运行模式，只分析不处理")
    parser.add_argument("--verbose", action="store_true",
                       help="详细输出模式")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 决定使用哪个API客户端 - 默认使用大学API
    use_multi_api = args.use_multi_api and not args.use_university_api
    
    # 创建优化器
    optimizer = ProjectOptimizer(
        args.base_dir, 
        args.output_dir, 
        optimization_prompt=None,  # 不再使用外部提示词
        use_multi_api=use_multi_api
    )
    
    if args.dry_run:
        logger.info("试运行模式 - 只进行项目扫描和分析")
        projects = optimizer.find_fullstack_projects()
        print(f"\n找到 {len(projects)} 个项目:")
        for project in projects:
            content = optimizer.read_frontend_content(project)
            if content:
                analysis = optimizer.analyze_project_structure(content)
                print(f"\n项目: {project.name}")
                print(f"  - React版本: {analysis['react_version']}")
                print(f"  - 依赖数量: {len(analysis['dependencies'])}")
                print(f"  - 组件数量: {analysis['components_count']}")
                print(f"  - 文件大小: {analysis['file_size_kb']:.2f} KB")
    else:
        # 执行批量调试日志添加
        logger.info(f"开始批量添加调试日志，使用{'多API客户端' if use_multi_api else '大学API客户端'}")
        
        summary = optimizer.process_all_projects()
        
        print(f"\n🎉 批量处理完成!")
        print(f"📊 总项目数: {summary['total_projects']}")
        print(f"✅ 成功: {summary['successful_projects']}")
        print(f"❌ 失败: {summary['failed_projects']}")
        print(f"📈 成功率: {summary['success_rate']:.1f}%")

if __name__ == "__main__":
    main()
