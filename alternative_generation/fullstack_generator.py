"""
Full-stack code generation pipeline
专门用于生成完整的前后台代码
"""
import os
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from api_client import UniversityAPIClient
from config import DEFAULT_MODEL, OUTPUT_DIR
from fixed_improved_prompts import (
    create_structured_frontend_prompt,
    create_structured_backend_prompt, 
    create_structured_database_prompt,
    create_structured_deployment_prompt
)

class FullStackGenerator:
    """全栈代码生成器"""
    
    def __init__(self, model: str = DEFAULT_MODEL, custom_output_dir: str = None):
        self.client = UniversityAPIClient(model)
        if custom_output_dir:
            self.output_dir = Path(custom_output_dir)
            self.fullstack_dir = self.output_dir
        else:
            self.output_dir = Path(OUTPUT_DIR)
            self.fullstack_dir = self.output_dir / "fullstack_projects"
        self.ensure_directories()
    
    def ensure_directories(self):
        """创建必要的目录结构"""
        self.output_dir.mkdir(exist_ok=True)
        self.fullstack_dir.mkdir(exist_ok=True)
    
    def create_frontend_prompt(self, instruction: str, tech_stack: str = "React", api_documentation: Optional[str] = None) -> str:
        """Create frontend code generation prompt with structured output"""
        return create_structured_frontend_prompt(instruction, tech_stack, api_documentation)

    def create_backend_prompt(self, instruction: str, tech_stack: str = "Node.js", api_documentation: Optional[str] = None) -> str:
        """Create backend code generation prompt with structured output"""
        return create_structured_backend_prompt(instruction, tech_stack, api_documentation)

    def create_database_prompt(self, instruction: str, db_type: str = "MongoDB") -> str:
        """Create database design prompt with structured output"""
        return create_structured_database_prompt(instruction, db_type)

    def create_deployment_prompt(self, instruction: str, platform: str = "Docker") -> str:
        """Create deployment configuration prompt with structured output"""
        return create_structured_deployment_prompt(instruction, platform)

    def generate_component(
        self, 
        instruction: str, 
        component_type: str,
        tech_stack: str,
        max_tokens: int = 8000,
        api_documentation: Optional[str] = None
    ) -> Dict[str, Any]:
        """生成单个组件代码"""
        
        prompts = {
            "frontend": self.create_frontend_prompt(instruction, tech_stack, api_documentation),
            "backend": self.create_backend_prompt(instruction, tech_stack, api_documentation),
            "database": self.create_database_prompt(instruction, tech_stack),
            "deployment": self.create_deployment_prompt(instruction, tech_stack)
        }
        
        if component_type not in prompts:
            return {
                "success": False,
                "error": f"Unknown component type: {component_type}"
            }
        
        print(f"🔧 生成{component_type}代码...")
        
        messages = [
            {
                "role": "system",
                "content": f"You are a professional {component_type} developer specialized in generating high-quality {component_type} code."
            },
            {
                "role": "user",
                "content": prompts[component_type]
            }
        ]
        
        start_time = time.time()
        response = self.client.chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7
        )
        generation_time = time.time() - start_time
        
        if "error" in response:
            return {
                "success": False,
                "error": response["error"],
                "component_type": component_type,
                "generation_time": generation_time
            }
        
        if "choices" not in response or len(response["choices"]) == 0:
            return {
                "success": False,
                "error": "No response generated",
                "component_type": component_type,
                "generation_time": generation_time
            }
        
        generated_content = response["choices"][0].get("message", {}).get("content", "")
        
        if not generated_content.strip():
            return {
                "success": False,
                "error": "Empty content generated",
                "component_type": component_type,
                "generation_time": generation_time
            }
        
        return {
            "success": True,
            "component_type": component_type,
            "content": generated_content,
            "generation_time": generation_time,
            "content_length": len(generated_content),
            "timestamp": datetime.now().isoformat(),
            "tech_stack": tech_stack,
            "api_response": response.get("usage", {})
        }

    def generate_fullstack_project(
        self,
        instruction: str,
        project_name: Optional[str] = None,
        frontend_tech: str = "React",
        backend_tech: str = "Node.js",
        database_tech: str = "MongoDB",
        deployment_tech: str = "Docker",
        include_database: bool = False,  # 添加这个参数，默认不包含数据库
        include_deployment: bool = False,  # 添加这个参数，默认不包含部署文件
        api_documentation: Optional[str] = None
    ) -> Dict[str, Any]:
        """生成完整的全栈项目"""
        
        if not project_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_name = f"fullstack_project_{timestamp}"
        
        print(f"\n🚀 开始生成全栈项目: {project_name}")
        print(f"前端技术栈: {frontend_tech}")
        print(f"后端技术栈: {backend_tech}")
        if include_database:
            print(f"数据库: {database_tech}")
        else:
            print("数据库: 跳过 (使用模拟数据)")
        if include_deployment:
            print(f"部署: {deployment_tech}")
        else:
            print("部署: 跳过")
        print("=" * 60)
        
        project_dir = self.fullstack_dir / project_name
        project_dir.mkdir(exist_ok=True)
        
        # 生成各个组件
        components = [
            ("frontend", frontend_tech),
            ("backend", backend_tech)
        ]
        
        # 只有在明确要求时才包含数据库
        if include_database:
            components.append(("database", database_tech))
            
        # 只有在明确要求时才包含部署文件
        if include_deployment:
            components.append(("deployment", deployment_tech))
        
        results = {}
        total_start_time = time.time()
        
        for component_type, tech_stack in components:
            print(f"\n📝 生成 {component_type} ({tech_stack})...")
            
            # For frontend and backend, pass the api_documentation
            component_api_doc = None
            if component_type in ["frontend", "backend"]:
                component_api_doc = api_documentation

            result = self.generate_component(
                instruction, 
                component_type, 
                tech_stack,
                api_documentation=component_api_doc
            )
            
            results[component_type] = result
            
            if result["success"]:
                # 保存代码文件
                file_extension = {
                    "frontend": "jsx" if "React" in tech_stack else "html",
                    "backend": "js" if "Node" in tech_stack else "py",
                    "database": "sql" if "SQL" in tech_stack else "js",
                    "deployment": "yml"
                }.get(component_type, "txt")
                
                code_file = project_dir / f"{component_type}.{file_extension}"
                with open(code_file, 'w', encoding='utf-8') as f:
                    f.write(result["content"])
                
                # 保存元数据
                metadata_file = project_dir / f"{component_type}_metadata.json"
                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                
                print(f"✅ {component_type} 生成成功 ({result['content_length']} 字符)")
                print(f"   文件保存至: {code_file}")
                
            else:
                print(f"❌ {component_type} 生成失败: {result.get('error', 'Unknown error')}")
            
            # 添加延迟避免API限制
            time.sleep(2)
        
        total_time = time.time() - total_start_time
        
        # 创建项目总结
        successful_components = [k for k, v in results.items() if v.get("success", False)]
        
        # 创建技术栈信息
        tech_stacks = {
            "frontend": frontend_tech,
            "backend": backend_tech
        }
        
        if include_database:
            tech_stacks["database"] = database_tech
        if include_deployment:
            tech_stacks["deployment"] = deployment_tech
        
        project_summary = {
            "project_name": project_name,
            "instruction": instruction,
            "tech_stacks": tech_stacks,
            "components": results,
            "successful_components": successful_components,
            "total_components": len(components),
            "success_rate": len(successful_components) / len(components),
            "total_generation_time": total_time,
            "project_directory": str(project_dir),
            "timestamp": datetime.now().isoformat()
        }
        
        # 保存项目总结
        summary_file = project_dir / "project_summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(project_summary, f, indent=2, ensure_ascii=False)
        
        # 创建README文件
        self.create_project_readme(project_dir, project_summary)
        
        print(f"\n📊 项目生成完成!")
        print(f"   项目名称: {project_name}")
        print(f"   成功组件: {len(successful_components)}/{len(components)}")
        print(f"   总耗时: {total_time:.2f}秒")
        print(f"   项目目录: {project_dir}")
        
        return project_summary

    def create_project_readme(self, project_dir: Path, summary: Dict[str, Any]):
        """创建项目README文件"""
        # 构建技术栈描述
        tech_stack_lines = []
        tech_stack_lines.append(f"- **前端**: {summary['tech_stacks']['frontend']}")
        tech_stack_lines.append(f"- **后端**: {summary['tech_stacks']['backend']}")
        
        if 'database' in summary['tech_stacks']:
            tech_stack_lines.append(f"- **数据库**: {summary['tech_stacks']['database']}")
        if 'deployment' in summary['tech_stacks']:
            tech_stack_lines.append(f"- **部署**: {summary['tech_stacks']['deployment']}")
        
        tech_stack_text = '\n'.join(tech_stack_lines)
        
        # 构建项目结构描述
        structure_lines = []
        structure_lines.append(f"{summary['project_name']}/")
        structure_lines.append(f"├── frontend.{self.get_file_extension('frontend', summary['tech_stacks']['frontend'])}      # 前端代码")
        structure_lines.append(f"├── backend.{self.get_file_extension('backend', summary['tech_stacks']['backend'])}       # 后端代码")
        
        if 'database' in summary['tech_stacks']:
            structure_lines.append(f"├── database.{self.get_file_extension('database', summary['tech_stacks']['database'])}     # 数据库设计")
        if 'deployment' in summary['tech_stacks']:
            structure_lines.append(f"├── deployment.yml   # 部署配置")
        
        structure_lines.append(f"├── project_summary.json  # 项目元数据")
        structure_lines.append(f"└── README.md        # 本文件")
        
        structure_text = '\n'.join(structure_lines)
        
        readme_content = f"""# {summary['project_name']}

## 项目描述
{summary['instruction']}

## 技术栈
{tech_stack_text}

## 项目结构
```
{structure_text}
```

## 生成统计
- 生成时间: {summary['timestamp']}
- 总耗时: {summary['total_generation_time']:.2f}秒
- 成功率: {summary['success_rate']:.1%}

## 使用说明
1. 查看各个组件的代码文件
2. 根据部署配置进行环境搭建
3. 按照技术栈要求安装依赖
4. 运行和测试项目

## 文件说明
"""
        
        for component in summary['successful_components']:
            readme_content += f"- **{component}**: 包含完整的{component}实现代码\n"
        
        readme_file = project_dir / "README.md"
        with open(readme_file, 'w', encoding='utf-8') as f:
            f.write(readme_content)
    
    def get_file_extension(self, component_type: str, tech_stack: str) -> str:
        """获取文件扩展名"""
        extensions = {
            "frontend": "jsx" if "React" in tech_stack else "html",
            "backend": "js" if "Node" in tech_stack else "py",
            "database": "sql" if "SQL" in tech_stack else "js",
            "deployment": "yml"
        }
        return extensions.get(component_type, "txt")

    def generate_batch_projects(
        self,
        instructions: List[str],
        base_name: str = "project",
        api_docs_dir: str = "api_docs"
    ) -> List[Dict[str, Any]]:
        """批量生成多个全栈项目"""
        
        print(f"\n🚀 开始批量生成 {len(instructions)} 个全栈项目")
        
        results = []
        
        for i, instruction in enumerate(instructions):
            project_name = f"{base_name}_{i+1:03d}"
            print(f"\n--- 项目 {i+1}/{len(instructions)}: {project_name} ---")

            # 读取对应的API文档
            # 修正：API文档是输入，路径不应依赖于输出目录
            api_doc_path = Path("api_docs") / f"api_doc_{i+1:06d}.md"
            api_documentation = None
            if api_doc_path.exists():
                try:
                    with open(api_doc_path, 'r', encoding='utf-8') as f:
                        api_documentation = f.read()
                    print(f"   成功读取API文档: {api_doc_path}")
                except Exception as e:
                    print(f"   ⚠️ 读取API文档失败: {e}")
            else:
                print(f"   ℹ️ 未找到API文档: {api_doc_path}，将不使用API文档进行生成。")
            
            try:
                result = self.generate_fullstack_project(
                    instruction=instruction,
                    project_name=project_name,
                    api_documentation=api_documentation
                )
                results.append(result)
                
            except Exception as e:
                print(f"❌ 项目 {project_name} 生成失败: {str(e)}")
                results.append({
                    "project_name": project_name,
                    "instruction": instruction,
                    "success": False,
                    "error": str(e)
                })
        
        # 创建批量总结
        batch_summary = {
            "total_projects": len(instructions),
            "successful_projects": len([r for r in results if r.get("success_rate", 0) > 0]),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        
        batch_file = self.fullstack_dir / f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(batch_file, 'w', encoding='utf-8') as f:
            json.dump(batch_summary, f, indent=2, ensure_ascii=False)
        
        print(f"\n📊 批量生成完成!")
        print(f"   总项目数: {batch_summary['total_projects']}")
        print(f"   成功项目数: {batch_summary['successful_projects']}")
        print(f"   批量总结: {batch_file}")
        
        return results

    def generate_simple_fullstack_project(
        self,
        instruction: str,
        project_name: Optional[str] = None,
        frontend_tech: str = "React",
        backend_tech: str = "Node.js",
        api_documentation: Optional[str] = None
    ) -> Dict[str, Any]:
        """生成简化的全栈项目（不包含数据库和部署文件）"""
        
        return self.generate_fullstack_project(
            instruction=instruction,
            project_name=project_name,
            frontend_tech=frontend_tech,
            backend_tech=backend_tech,
            database_tech="None",
            deployment_tech="None",
            include_database=False,
            include_deployment=False,
            api_documentation=api_documentation
        )

    def generate_batch_simple_projects(
        self,
        instructions: List[str],
        base_name: str = "simple_project",
        api_docs_dir: str = "api_docs"
    ) -> List[Dict[str, Any]]:
        """批量生成多个简化全栈项目（不包含数据库）"""
        
        print(f"\n🚀 开始批量生成 {len(instructions)} 个简化全栈项目（无数据库）")
        
        results = []
        
        for i, instruction in enumerate(instructions):
            project_name = f"{base_name}_{i+1:03d}"
            print(f"\n--- 项目 {i+1}/{len(instructions)}: {project_name} ---")

            # 读取对应的API文档
            # 修正：API文档是输入，路径不应依赖于输出目录
            api_doc_path = Path("api_docs") / f"api_doc_{i+1:06d}.md"
            api_documentation = None
            if api_doc_path.exists():
                try:
                    with open(api_doc_path, 'r', encoding='utf-8') as f:
                        api_documentation = f.read()
                    print(f"   成功读取API文档: {api_doc_path}")
                except Exception as e:
                    print(f"   ⚠️ 读取API文档失败: {e}")
            else:
                print(f"   ℹ️ 未找到API文档: {api_doc_path}，将不使用API文档进行生成。")
            
            try:
                result = self.generate_simple_fullstack_project(
                    instruction=instruction,
                    project_name=project_name,
                    api_documentation=api_documentation
                )
                results.append(result)
                
            except Exception as e:
                print(f"❌ 项目 {project_name} 生成失败: {str(e)}")
                results.append({
                    "project_name": project_name,
                    "instruction": instruction,
                    "success": False,
                    "error": str(e)
                })
        
        # 创建批量总结
        batch_summary = {
            "total_projects": len(instructions),
            "successful_projects": len([r for r in results if r.get("success_rate", 0) > 0]),
            "results": results,
            "project_type": "simple_fullstack_no_database",
            "timestamp": datetime.now().isoformat()
        }
        
        batch_file = self.fullstack_dir / f"simple_batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(batch_file, 'w', encoding='utf-8') as f:
            json.dump(batch_summary, f, indent=2, ensure_ascii=False)
        
        print(f"\n📊 简化批量生成完成!")
        print(f"   总项目数: {batch_summary['total_projects']}")
        print(f"   成功项目数: {batch_summary['successful_projects']}")
        print(f"   批量总结: {batch_file}")
        
        return results
