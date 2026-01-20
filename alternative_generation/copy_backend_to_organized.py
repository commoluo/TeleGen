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
        
    def find_source_project_folder_names(self, optimized_folder_name):
        """从优化后的文件夹名推断可能的源项目文件夹名列表"""
        candidates = []

        # e.g. full_run_with_api_doc_001_restructured_optimized
        if optimized_folder_name.endswith('_restructured_optimized'):
            base = optimized_folder_name[:-len('_optimized')]  # -> ..._restructured
            candidates.append(base)
            if base.endswith('_restructured'):
                candidates.append(base[:-len('_restructured')])

        # e.g. full_run_with_api_doc_001_runnable_optimized
        if optimized_folder_name.endswith('_runnable_optimized'):
            base = optimized_folder_name[:-len('_optimized')]  # -> ..._runnable
            candidates.append(base)
            if base.endswith('_runnable'):
                candidates.append(base[:-len('_runnable')])

        # 默认也尝试直接去掉 _optimized 后缀
        if optimized_folder_name.endswith('_optimized'):
            candidates.append(optimized_folder_name[:-len('_optimized')])

        # 去重保持顺序
        unique_candidates = []
        for name in candidates:
            if name and name not in unique_candidates:
                unique_candidates.append(name)

        return unique_candidates
    
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
                candidate_names = self.find_source_project_folder_names(project_folder.name)

                if not candidate_names:
                    print(f"⚠️  无法推断源文件夹名: {project_folder.name}")
                    failed_count += 1
                    continue

                debug_folder = None
                backend_file = None
                for candidate in candidate_names:
                    possible_folder = self.debug_projects_dir / candidate
                    possible_backend = possible_folder / "backend.js"
                    if possible_backend.exists():
                        debug_folder = possible_folder
                        backend_file = possible_backend
                        break

                if not debug_folder:
                    # 检查是否至少存在对应的debug项目目录
                    for candidate in candidate_names:
                        possible_folder = self.debug_projects_dir / candidate
                        if possible_folder.exists():
                            print(f"❌ 在 '{possible_folder.name}' 中未找到 backend.js")
                            missing_backend_count += 1
                            break
                    else:
                        print(f"❌ 未找到源文件夹: {self.debug_projects_dir / candidate_names[0]}")
                        missing_debug_folder_count += 1
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
