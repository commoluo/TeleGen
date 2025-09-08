#!/usr/bin/env python3
"""
修复项目package.json脚本
Fix project package.json scripts
"""

import os
import json
from pathlib import Path

def fix_package_json(package_json_path: Path, is_backend: bool = True):
    """修复package.json文件，添加缺失的scripts"""
    
    if not package_json_path.exists():
        print(f"⚠️  package.json 不存在: {package_json_path}")
        return False
    
    try:
        # 读取现有package.json
        with open(package_json_path, 'r', encoding='utf-8') as f:
            package_data = json.load(f)
        
        # 确保有scripts字段
        if 'scripts' not in package_data:
            package_data['scripts'] = {}
        
        # 为后端添加脚本
        if is_backend:
            if 'start' not in package_data['scripts']:
                package_data['scripts']['start'] = 'node app.js'
            if 'dev' not in package_data['scripts']:
                package_data['scripts']['dev'] = 'nodemon app.js'
        else:
            # 为前端添加脚本
            if 'start' not in package_data['scripts']:
                package_data['scripts']['start'] = 'npm run serve'
            if 'serve' not in package_data['scripts']:
                package_data['scripts']['serve'] = 'python -m http.server 8080'
            if 'dev' not in package_data['scripts']:
                package_data['scripts']['dev'] = 'python -m http.server 8080'
        
        # 写回文件
        with open(package_json_path, 'w', encoding='utf-8') as f:
            json.dump(package_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 修复 {package_json_path}")
        return True
        
    except Exception as e:
        print(f"❌ 修复失败 {package_json_path}: {e}")
        return False

def main():
    """主函数"""
    projects_dir = Path("generated_websites/fullstack_projects")
    
    if not projects_dir.exists():
        print("❌ 项目目录不存在")
        return
    
    fixed_count = 0
    total_count = 0
    
    # 遍历所有项目
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir() or not project_dir.name.endswith("_simple_project_restructured"):
            continue
        
        print(f"\n🔧 修复项目: {project_dir.name}")
        
        # 修复后端package.json
        backend_package = project_dir / "backend" / "package.json"
        if backend_package.exists():
            total_count += 1
            if fix_package_json(backend_package, is_backend=True):
                fixed_count += 1
        
        # 修复前端package.json
        frontend_package = project_dir / "frontend" / "package.json"
        if frontend_package.exists():
            total_count += 1
            if fix_package_json(frontend_package, is_backend=False):
                fixed_count += 1
    
    print(f"\n📊 修复完成:")
    print(f"   - 总文件数: {total_count}")
    print(f"   - 修复成功: {fixed_count}")
    print(f"   - 修复失败: {total_count - fixed_count}")

if __name__ == "__main__":
    # 切换到脚本目录
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    main()
