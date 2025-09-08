#!/bin/bash

echo "=== WebGen-Bench 项目配置脚本 ==="
echo ""
echo "请按照提示输入您的API配置信息："
echo ""

# 获取OpenAI API Key
echo "1. 请输入您学校的GPT-4o API Key:"
read -p "OpenAI API Key: " openai_key

# 获取GitHub Token (可选)
echo ""
echo "2. 请输入您的GitHub Personal Access Token (用于导入模板，可选):"
echo "   可在 https://github.com/settings/personal-access-tokens/new 创建"
read -p "GitHub Token (按回车跳过): " github_token

# 配置.env.local文件
env_file="bolt.diy-Fork/.env.local"

if [ ! -f "$env_file" ]; then
    echo "错误: $env_file 文件不存在"
    exit 1
fi

# 更新OpenAI API Key
sed -i '' "s/OPENAI_API_KEY=\"YOUR_SCHOOL_GPT4O_API_KEY_HERE\"/OPENAI_API_KEY=\"$openai_key\"/" "$env_file"

# 更新GitHub Token (如果提供了)
if [ ! -z "$github_token" ]; then
    sed -i '' "s/VITE_GITHUB_ACCESS_TOKEN=\"\"/VITE_GITHUB_ACCESS_TOKEN=\"$github_token\"/" "$env_file"
fi

echo ""
echo "✅ 配置完成！"
echo ""
echo "接下来的步骤："
echo "1. 启动Bolt.diy服务: cd bolt.diy-Fork && pnpm run dev"
echo "2. 等待服务启动后，复制显示的URL (通常是 http://localhost:5173/)"
echo "3. 运行测试: python src/automatic_bolt_diy/eval_bolt_diy.py --jsonl_path data/test.jsonl --url <YOUR_URL> --provider OpenAI --desired_model gpt-4o"
echo ""
