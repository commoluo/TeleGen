#!/bin/bash
# 自动化WebVoyager测试脚本
# 为每个项目启动服务器，运行WebVoyager测试，然后关闭

PROJECTS_DIR="/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/generated_websites/fullstack_projects"
WEBVOYAGER_DIR="/Users/luoyujia/Downloads/WebGen-Bench-main/webvoyager"
TASKS_FILE="/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/fullstack_webvoyager_tasks.jsonl"
OUTPUT_DIR="./webvoyager_results"
API_KEY="${OPENAI_API_KEY}"

if [ -z "$API_KEY" ]; then
    echo "请设置OPENAI_API_KEY环境变量"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# 获取所有重构后的项目
PROJECTS=($(ls "$PROJECTS_DIR"/*_restructured 2>/dev/null))

echo "找到 ${#PROJECTS[@]} 个项目"

for project in "${PROJECTS[@]}"; do
    PROJECT_NAME=$(basename "$project")
    echo "\n=== 测试项目: $PROJECT_NAME ==="
    
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
        PROJECT_TASKS_FILE="./data/tasks_${PROJECT_NAME}.jsonl"
        grep "$PROJECT_NAME" "$TASKS_FILE" > "$PROJECT_TASKS_FILE"
        
        # 运行WebVoyager
        python run.py \
            --test_file "$PROJECT_TASKS_FILE" \
            --api_key "$API_KEY" \
            --headless \
            --max_iter 10 \
            --max_attached_imgs 3 \
            --temperature 0.7 \
            --output_dir "$OUTPUT_DIR/$PROJECT_NAME" \
            --window_width 1024 \
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

echo "\n=== 所有项目测试完成 ==="
echo "结果保存在: $OUTPUT_DIR"
