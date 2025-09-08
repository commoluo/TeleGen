#!/usr/bin/env python3
"""
优化代码文件组织器
将 optimized_code 目录中的每个 jsx 文件移动到以其文件名（不含扩展名）命名的文件夹中。
"""

import os
import shutil
from pathlib import Path

class OptimizedCodeOrganizer:
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.optimized_code_dir = self.base_dir / "optimized_code"
        
    def organize_files(self):
        """将每个jsx文件移动到以其文件名（不含扩展名）命名的文件夹中"""
        if not self.optimized_code_dir.exists():
            print(f"❌ 源目录不存在: {self.optimized_code_dir}")
            return
        
        print(f"📁 正在处理目录: {self.optimized_code_dir}")
        
        # 获取所有jsx文件
        jsx_files = list(self.optimized_code_dir.glob("*.jsx"))
        print(f"🔍 发现 {len(jsx_files)} 个jsx文件")
        
        if not jsx_files:
            print("❌ 没有找到jsx文件")
            return
        
        processed_count = 0
        failed_count = 0
        
        for jsx_file in jsx_files:
            try:
                # 使用文件名（不含扩展名）作为文件夹名
                folder_name = jsx_file.stem
                project_folder = self.optimized_code_dir / folder_name
                project_folder.mkdir(exist_ok=True)
                
                # 移动文件到新创建的文件夹
                target_file = project_folder / jsx_file.name
                shutil.move(str(jsx_file), str(target_file))
                
                print(f"✅ 已移动 '{jsx_file.name}' -> '{folder_name}/'")
                processed_count += 1
                
            except Exception as e:
                print(f"❌ 处理文件失败 {jsx_file.name}: {e}")
                failed_count += 1
        
        print(f"\n📊 处理完成:")
        print(f"   成功处理: {processed_count}")
        print(f"   失败: {failed_count}")
        print(f"   总文件数: {len(jsx_files)}")
        
        folders = [f for f in self.optimized_code_dir.iterdir() if f.is_dir()]
        print(f"📁 当前目录中共有 {len(folders)} 个文件夹")

def main():
    print("🗂️  优化代码文件组织器")
    print("=" * 50)
    
    organizer = OptimizedCodeOrganizer()
    
    print("1. 组织优化代码文件...")
    organizer.organize_files()
    
    print("\n✅ 组织完成!")

if __name__ == "__main__":
    main()
