#!/usr/bin/env python3
"""
测试文件解析功能
"""
import re
from pathlib import Path

def clean_code_content(content: str) -> str:
    """清理代码内容，移除markdown标记和多余的格式"""
    # 移除开头的多重代码块标记
    content = re.sub(r'^````[\w\s]*\n', '', content, flags=re.MULTILINE)
    content = re.sub(r'^```[\w\s]*\n', '', content, flags=re.MULTILINE)
    
    # 移除结尾的代码块标记
    content = re.sub(r'\n````$', '', content, flags=re.MULTILINE)
    content = re.sub(r'\n```$', '', content, flags=re.MULTILINE)
    
    # 处理嵌套的代码块标记（文件内容开头可能还有```jsx）
    lines = content.split('\n')
    cleaned_lines = []
    
    for i, line in enumerate(lines):
        # 跳过代码块开始标记
        if re.match(r'^```[\w]*$', line.strip()):
            continue
        # 跳过代码块结束标记
        elif line.strip() == '```':
            continue
        # 跳过代码块结束标记（在文件末尾）
        elif re.match(r'^```$', line.strip()):
            continue
        else:
            cleaned_lines.append(line)
    
    content = '\n'.join(cleaned_lines)
    
    # 移除文件路径注释
    content = re.sub(r'^// filepath:.*?\n', '', content, flags=re.MULTILINE)
    
    return content.strip()

def extract_files_from_frontend(content: str):
    """从前端内容中提取单独的文件"""
    files = {}
    
    # 清理代码内容
    content = clean_code_content(content)
    
    print("=== 清理后的内容 ===")
    print(content[:500])
    print("=== 内容结束 ===")
    
    # 使用 // FILE: filename 格式提取文件
    pattern = r'// FILE: ([^\n]+)\n(.*?)(?=\n// FILE: |\Z)'
    matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
    
    for match in matches:
        filename = match.group(1).strip()
        file_content = match.group(2).strip()
        
        # 清理内容：移除代码块标记
        file_content = re.sub(r'^```\w*\n', '', file_content, flags=re.MULTILINE)
        file_content = re.sub(r'\n```$', '', file_content, flags=re.MULTILINE)
        
        if file_content.strip():
            files[filename] = file_content.strip()
            print(f"📄 提取前端文件: {filename} ({len(file_content)} 字符)")
    
    return files

if __name__ == "__main__":
    # 读取测试文件
    frontend_file = Path("debug_logged_projects/001_simple_project/frontend_with_debug_logs.jsx")
    with open(frontend_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("原始内容前100字符:")
    print(repr(content[:100]))
    print()
    
    files = extract_files_from_frontend(content)
    print(f"提取的文件数量: {len(files)}")
    for filename in files.keys():
        print(f"  - {filename}")
