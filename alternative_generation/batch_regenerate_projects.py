#!/usr/bin/env python3
"""
批量重新生成所有项目 - 使用Simple无数据库模式
Batch regenerate all projects using Simple (no database) mode
"""

import os
import sys
import json
import shutil
from pathlib import Path
from fullstack_generator import FullStackGenerator
from project_restructurer import ProjectRestructurer
from datetime import datetime

def load_instructions_from_jsonl(file_path: str, limit: int = None):
    """从JSONL文件加载指令"""
    instructions = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if limit and len(instructions) >= limit:
                    break
                    
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        instruction = data.get('instruction', '')
                        if instruction:
                            instructions.append({
                                'id': data.get('id', f'item_{line_num}'),
                                'instruction': instruction,
                                'category': data.get('Category', {}),
                                'line_num': line_num
                            })
                        else:
                            print(f"警告: 第{line_num}行没有instruction字段")
                    except json.JSONDecodeError as e:
                        print(f"警告: 第{line_num}行JSON解析失败: {e}")
                        
    except FileNotFoundError:
        print(f"错误: 找不到文件 {file_path}")
        return []
    except Exception as e:
        print(f"错误: 读取文件时发生异常: {e}")
        return []
    
    return instructions

def backup_existing_projects(projects_dir: str):
    """备份现有项目"""
    if not os.path.exists(projects_dir):
        print(f"项目目录不存在: {projects_dir}")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"{projects_dir}_backup_{timestamp}"
    
    print(f"🔄 备份现有项目到: {backup_dir}")
    try:
        shutil.copytree(projects_dir, backup_dir)
        print(f"✅ 备份完成")
        return backup_dir
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return None

def clear_existing_projects(projects_dir: str):
    """清理现有项目"""
    if os.path.exists(projects_dir):
        print(f"🧹 清理现有项目目录: {projects_dir}")
        try:
            shutil.rmtree(projects_dir)
            print(f"✅ 清理完成")
        except Exception as e:
            print(f"❌ 清理失败: {e}")

def regenerate_all_projects(data_file: str, limit: int = None, start_from: int = 1):
    """重新生成所有项目"""
    print(f"🚀 开始批量重新生成项目")
    print(f"数据文件: {data_file}")
    print(f"生成限制: {limit if limit else '无限制'}")
    print(f"开始位置: {start_from}")
    print("=" * 60)
    
    # 加载指令
    instructions = load_instructions_from_jsonl(data_file, limit)
    if not instructions:
        print("❌ 没有加载到有效的指令")
        return
    
    # 如果指定了开始位置，跳过前面的项目
    if start_from > 1:
        instructions = instructions[start_from-1:]
        print(f"⏭️  跳过前 {start_from-1} 个项目")
    
    print(f"📋 将生成 {len(instructions)} 个项目")
    
    # 创建带时间戳的项目目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    projects_dir = f"generated_websites/fullstack_projects_{timestamp}"
    print(f"📁 项目将生成到: {projects_dir}")
    
    # 确保目录存在
    os.makedirs(projects_dir, exist_ok=True)
    
    # 创建生成器，使用自定义目录
    generator = FullStackGenerator(custom_output_dir=projects_dir)
    
    # 生成统计
    successful_count = 0
    failed_count = 0
    results = []
    
    # 批量生成项目
    for i, item in enumerate(instructions, start_from):
        print(f"\n[{i}/{start_from + len(instructions) - 1}] 生成项目: {item['id']}")
        print(f"指令: {item['instruction'][:100]}...")
        
        # 显示类别信息
        category = item.get('category', {})
        if category:
            primary_category = category.get('primary_category', '')
            subcategories = category.get('subcategories', [])
            print(f"主要类别: {primary_category}")
            if subcategories:
                print(f"子类别: {', '.join(subcategories)}")
        
        print("-" * 50)
        
        try:
            # 生成项目名称
            project_name = f"{i:03d}_simple_project"
            
            # 整合category信息到指令中
            enhanced_instruction = item['instruction']
            category = item.get('category', {})
            if category:
                primary_category = category.get('primary_category', '')
                subcategories = category.get('subcategories', [])
                
                category_context = f"\n\n[项目技术指导]\n"
                if primary_category:
                    category_context += f"主要功能类别: {primary_category}\n"
                if subcategories:
                    category_context += f"技术要求: {', '.join(subcategories)}\n"
                category_context += "请根据上述类别选择合适的技术栈和架构模式。"
                
                enhanced_instruction = enhanced_instruction + category_context
            
            # 生成项目
            result = generator.generate_simple_fullstack_project(
                instruction=enhanced_instruction,
                project_name=project_name
            )
            
            if result.get("success_rate", 0) > 0:
                # 重构项目结构
                project_dir = result.get("project_directory")
                if project_dir and os.path.exists(project_dir):
                    print(f"🔧 重构项目结构...")
                    try:
                        restructurer = ProjectRestructurer(project_dir)
                        restructure_success = restructurer.restructure_project()
                        
                        if restructure_success:
                            successful_count += 1
                            restructured_path = restructurer.restructured_path
                            print(f"✅ 生成并重构成功: {restructured_path}")
                            print(f"成功率: {result['success_rate']:.1%}")
                        else:
                            failed_count += 1
                            print(f"❌ 重构失败")
                    except Exception as e:
                        failed_count += 1
                        print(f"❌ 重构异常: {e}")
                else:
                    failed_count += 1
                    print(f"❌ 项目目录不存在: {project_dir}")
            else:
                failed_count += 1
                print(f"❌ 生成失败")
            
            results.append({
                'id': item['id'],
                'project_name': project_name,
                'category': item.get('category', {}),
                'success': result.get("success_rate", 0) > 0,
                'result': result
            })
            
        except Exception as e:
            failed_count += 1
            print(f"❌ 生成异常: {e}")
            results.append({
                'id': item['id'],
                'project_name': f"{i:03d}_simple_project",
                'category': item.get('category', {}),
                'success': False,
                'error': str(e)
            })
    
    # 生成报告
    print(f"\n🎉 批量生成完成!")
    print("=" * 60)
    print(f"📊 统计结果:")
    print(f"   ✅ 成功: {successful_count}")
    print(f"   ❌ 失败: {failed_count}")
    print(f"   📈 成功率: {successful_count/(successful_count+failed_count)*100:.1f}%")
    print(f"📁 项目位置: {projects_dir}")
    
    # 保存报告
    save_generation_report(results, successful_count, failed_count)
    
    return results

def save_generation_report(results: list, successful: int, failed: int):
    """保存生成报告"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"generation_report_{timestamp}.json"
    
    report = {
        'timestamp': timestamp,
        'summary': {
            'total': len(results),
            'successful': successful,
            'failed': failed,
            'success_rate': successful/(successful+failed)*100 if (successful+failed) > 0 else 0
        },
        'results': results
    }
    
    try:
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"📄 报告已保存: {report_file}")
    except Exception as e:
        print(f"❌ 保存报告失败: {e}")

def main():
    """主函数"""
    print("🔄 WebGen-Bench 项目批量重新生成器")
    print("=" * 60)
    
    # 默认配置
    default_data_file = "../data/test.jsonl"
    
    # 获取用户输入
    data_file = input(f"数据文件路径 (默认: {default_data_file}): ").strip()
    if not data_file:
        data_file = default_data_file
    
    if not os.path.exists(data_file):
        print(f"❌ 文件不存在: {data_file}")
        return
    
    limit_input = input("生成数量限制 (留空生成全部): ").strip()
    limit = None
    if limit_input.isdigit():
        limit = int(limit_input)
    
    start_input = input("开始位置 (默认: 1): ").strip()
    start_from = 1
    if start_input.isdigit():
        start_from = int(start_input)
    
    # 确认操作
    print(f"\n⚠️  注意: 此操作将:")
    print(f"   1. 创建新的项目目录 (带时间戳)")
    print(f"   2. 重新生成所有项目 (无数据库和部署模式)")
    print(f"   3. 数据文件: {data_file}")
    print(f"   4. 生成限制: {limit if limit else '无限制'}")
    print(f"   5. 开始位置: {start_from}")
    print(f"   6. 目标目录: generated_websites/fullstack_projects_{{timestamp}}")
    
    confirm = input(f"\n确认继续? (y/N): ").strip().lower()
    if confirm != 'y':
        print("操作已取消")
        return
    
    # 开始重新生成
    regenerate_all_projects(data_file, limit, start_from)

if __name__ == "__main__":
    main()
