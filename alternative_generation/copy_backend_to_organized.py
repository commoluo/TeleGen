#!/usr/bin/env python3
"""
后端文件复制器
将debug_logged_projects中的backend.js文件复制到optimized_code对应的项目文件夹中
"""

import os
import shutil
from pathlib import Path

class BackendFileCopier:
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.debug_projects_dir = self.base_dir / "debug_logged_projects"
        self.optimized_code_dir = self.base_dir / "optimized_code"
        
    def find_source_project_folder_name(self, optimized_folder_name):
        """从优化后的文件夹名中推断出原始项目文件夹名"""
        # 例如: from 'full_run_with_api_doc_001_runnable_optimized' to 'full_run_with_api_doc_001'
        if optimized_folder_name.endswith('_runnable_optimized'):
            return optimized_folder_name.replace('_runnable_optimized', '')
        return None
    
    def copy_backend_files(self):
        """复制所有backend.js文件"""
        if not self.optimized_code_dir.exists():
            print(f"❌ 目标目录不存在: {self.optimized_code_dir}")
            return
        
        if not self.debug_projects_dir.exists():
            print(f"❌ 源目录不存在: {self.debug_projects_dir}")
            return
        
        # 获取所有 organized 项目文件夹
        project_folders = [f for f in self.optimized_code_dir.iterdir() if f.is_dir()]
        
        print(f"🔍 在 '{self.optimized_code_dir.name}' 中发现 {len(project_folders)} 个项目文件夹")
        
        copied_count = 0
        failed_count = 0
        missing_backend_count = 0
        missing_debug_folder_count = 0
        
        for project_folder in sorted(project_folders):
            try:
                source_folder_name = self.find_source_project_folder_name(project_folder.name)
                
                if not source_folder_name:
                    print(f"⚠️  无法推断源文件夹名: {project_folder.name}")
                    failed_count += 1
                    continue
                
                # 查找对应的debug项目文件夹
                debug_folder = self.debug_projects_dir / source_folder_name
                
                if not debug_folder.exists():
                    print(f"❌ 未找到源文件夹: {debug_folder}")
                    missing_debug_folder_count += 1
                    continue
                
                # 查找backend.js文件
                backend_file = debug_folder / "backend.js"
                
                if not backend_file.exists():
                    print(f"❌ 在 '{debug_folder.name}' 中未找到 backend.js")
                    missing_backend_count += 1
                    continue
                
                # 复制backend.js到目标文件夹
                target_file = project_folder / "backend.js"
                shutil.copy2(backend_file, target_file)
                
                print(f"✅ {debug_folder.name}/backend.js -> {project_folder.name}/backend.js")
                copied_count += 1
                
            except Exception as e:
                print(f"❌ 处理失败 {project_folder.name}: {e}")
                failed_count += 1
        
        print(f"\n📊 复制完成:")
        print(f"   成功复制: {copied_count}")
        print(f"   源文件夹未找到: {missing_debug_folder_count}")
        print(f"   backend.js 未找到: {missing_backend_count}")
        print(f"   处理失败: {failed_count}")
        print(f"   总计: {len(project_folders)}")

def main():
    print("🔄 后端文件复制器")
    print("=" * 50)
    
    copier = BackendFileCopier()
    
    print("1. 复制backend.js文件...")
    copier.copy_backend_files()
    
    print("\n✅ 复制完成!")

if __name__ == "__main__":
    main()
