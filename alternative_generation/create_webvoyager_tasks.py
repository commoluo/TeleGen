#!/usr/bin/env python3
"""
为生成的fullstack项目创建WebVoyager测试任务
"""

import os
import json
import glob

def get_project_info(project_path):
    """从项目文件中提取信息，生成测试任务"""
    # 尝试在frontend目录中查找package.json
    frontend_package = os.path.join(project_path, "frontend", "package.json")
    backend_package = os.path.join(project_path, "backend", "package.json")
    root_package = os.path.join(project_path, "package.json")
    
    package_json_path = None
    if os.path.exists(frontend_package):
        package_json_path = frontend_package
    elif os.path.exists(backend_package):
        package_json_path = backend_package
    elif os.path.exists(root_package):
        package_json_path = root_package
    
    if not package_json_path:
        # 如果没有package.json，就用目录名生成基本信息
        return {
            'name': os.path.basename(project_path),
            'description': f'Generated fullstack project: {os.path.basename(project_path)}',
            'path': project_path
        }
    
    try:
        with open(package_json_path, 'r', encoding='utf-8') as f:
            package_data = json.load(f)
        
        project_name = package_data.get('name', os.path.basename(project_path))
        description = package_data.get('description', f'Generated fullstack project: {os.path.basename(project_path)}')
        
        return {
            'name': project_name,
            'description': description,
            'path': project_path
        }
    except:
        return {
            'name': os.path.basename(project_path),
            'description': f'Generated fullstack project: {os.path.basename(project_path)}',
            'path': project_path
        }

def generate_test_tasks(projects_dir, output_file):
    """生成WebVoyager测试任务文件"""
    
    # 查找所有重构后的项目
    project_pattern = os.path.join(projects_dir, "*_restructured")
    projects = glob.glob(project_pattern)
    
    tasks = []
    
    for i, project_path in enumerate(sorted(projects)):
        project_info = get_project_info(project_path)
        if not project_info:
            continue
            
        project_name = os.path.basename(project_path)
        
        # 假设项目在localhost:3000运行
        base_url = f"http://localhost:3000"
        
        # 为每个项目生成多个测试任务
        test_cases = [
            {
                "web_name": f"Generated_Project_{project_name}",
                "id": f"{project_name}--homepage",
                "ques": f"Navigate to the homepage of {project_name} and verify that the main interface loads correctly. Check if all navigation elements and key features are visible.",
                "web": base_url
            },
            {
                "web_name": f"Generated_Project_{project_name}",
                "id": f"{project_name}--interaction", 
                "ques": f"Test the main interactive features of {project_name}. Try clicking buttons, filling forms, or using any interactive elements present on the page.",
                "web": base_url
            },
            {
                "web_name": f"Generated_Project_{project_name}",
                "id": f"{project_name}--navigation",
                "ques": f"Navigate through different sections or pages of {project_name} if available. Check that all links work properly and pages load without errors.",
                "web": base_url
            }
        ]
        
        # 如果有描述，生成基于描述的特定测试
        if project_info['description']:
            test_cases.append({
                "web_name": f"Generated_Project_{project_name}",
                "id": f"{project_name}--functionality",
                "ques": f"Based on the project description '{project_info['description']}', test the core functionality of {project_name} and verify it works as expected.",
                "web": base_url
            })
        
        tasks.extend(test_cases)
    
    # 保存任务文件
    with open(output_file, 'w', encoding='utf-8') as f:
        for task in tasks:
            f.write(json.dumps(task, ensure_ascii=False) + '\n')
    
    print(f"生成了 {len(tasks)} 个测试任务，保存到 {output_file}")
    return tasks

def create_project_runner_script(projects_dir, tasks_file):
    """创建项目运行器脚本，用于自动启动项目和运行WebVoyager测试"""
    
    script_content = f'''#!/bin/bash
# 自动化WebVoyager测试脚本
# 为每个项目启动服务器，运行WebVoyager测试，然后关闭

PROJECTS_DIR="{projects_dir}"
WEBVOYAGER_DIR="/Users/luoyujia/Downloads/WebGen-Bench-main/webvoyager"
TASKS_FILE="{tasks_file}"
OUTPUT_DIR="./webvoyager_results"
API_KEY="${{OPENAI_API_KEY}}"

if [ -z "$API_KEY" ]; then
    echo "请设置OPENAI_API_KEY环境变量"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# 获取所有重构后的项目
PROJECTS=($(ls "$PROJECTS_DIR"/*_restructured 2>/dev/null))

echo "找到 ${{#PROJECTS[@]}} 个项目"

for project in "${{PROJECTS[@]}}"; do
    PROJECT_NAME=$(basename "$project")
    echo "\\n=== 测试项目: $PROJECT_NAME ==="
    
    # 进入项目目录
    cd "$project"
    
    # 安装依赖（如果需要）
    if [ ! -d "node_modules" ]; then
        echo "安装依赖..."
        npm install
    fi
    
    # 启动项目（后台运行）
    echo "启动项目服务器..."
    npm start &
    SERVER_PID=$!
    
    # 等待服务器启动
    echo "等待服务器启动..."
    sleep 10
    
    # 检查服务器是否运行
    if curl -s http://localhost:3000 > /dev/null; then
        echo "服务器启动成功"
        
        # 运行WebVoyager测试
        echo "运行WebVoyager测试..."
        cd "$WEBVOYAGER_DIR"
        
        # 创建项目特定的任务文件
        PROJECT_TASKS_FILE="./data/tasks_${{PROJECT_NAME}}.jsonl"
        grep "$PROJECT_NAME" "$TASKS_FILE" > "$PROJECT_TASKS_FILE"
        
        # 运行WebVoyager
        python run.py \\
            --test_file "$PROJECT_TASKS_FILE" \\
            --api_key "$API_KEY" \\
            --headless \\
            --max_iter 10 \\
            --max_attached_imgs 3 \\
            --temperature 0.7 \\
            --output_dir "$OUTPUT_DIR/$PROJECT_NAME" \\
            --window_width 1024 \\
            --window_height 768
            
        echo "WebVoyager测试完成"
    else
        echo "服务器启动失败"
    fi
    
    # 关闭服务器
    echo "关闭项目服务器..."
    kill $SERVER_PID 2>/dev/null
    sleep 3
    
    # 强制杀死如果还在运行
    kill -9 $SERVER_PID 2>/dev/null
    
    # 返回原目录
    cd - > /dev/null
done

echo "\\n=== 所有项目测试完成 ==="
echo "结果保存在: $OUTPUT_DIR"
'''
    
    script_path = "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/run_webvoyager_tests.sh"
    with open(script_path, 'w') as f:
        f.write(script_content)
    
    os.chmod(script_path, 0o755)
    print(f"创建了运行脚本: {script_path}")
    return script_path

def main():
    projects_dir = "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/generated_websites/fullstack_projects"
    tasks_file = "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/fullstack_webvoyager_tasks.jsonl"
    
    print("正在为fullstack项目生成WebVoyager测试任务...")
    
    # 生成测试任务
    tasks = generate_test_tasks(projects_dir, tasks_file)
    
    # 创建运行脚本
    script_path = create_project_runner_script(projects_dir, tasks_file)
    
    print(f"\\n完成! 使用方法:")
    print(f"1. 设置环境变量: export OPENAI_API_KEY='your-api-key'")
    print(f"2. 运行测试: {script_path}")
    print(f"\\n或者手动运行单个项目:")
    print(f"cd webvoyager")
    print(f"python run.py --test_file {tasks_file} --api_key $OPENAI_API_KEY --headless")

if __name__ == "__main__":
    main()
