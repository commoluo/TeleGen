#!/usr/bin/env python3
"""
测试多API配置的简单脚本
"""

import os
import sys
import logging
from api_config import get_openai_config, get_school_config, get_best_config
from multi_api_client import MultiAPIClient

def test_api_config():
    """测试API配置"""
    print("测试API配置功能")
    print("=" * 50)
    
    # 测试不同的配置
    configs = [
        ("自动检测", get_best_config()),
        ("OpenAI", get_openai_config()),
        ("学校API", get_school_config()),
    ]
    
    for name, config in configs:
        print(f"\n{name}:")
        print(f"  提供商: {config.provider}")
        print(f"  基础URL: {config.config['base_url']}")
        print(f"  默认模型: {config.get_model()}")
        print(f"  API密钥: {'已设置' if config.api_key else '未设置'}")
        print(f"  配置有效: {config.validate()}")
        print(f"  速率限制: {config.get_rate_limits()}")

def test_api_client():
    """测试API客户端"""
    print("\n\n测试API客户端功能")
    print("=" * 50)
    
    # 获取最佳配置
    config = get_best_config()
    if not config.validate():
        print("❌ 没有有效的API配置，请设置API密钥")
        return False
    
    print(f"使用配置: {config.get_description()}")
    
    # 创建客户端
    client = MultiAPIClient(config)
    
    # 测试消息
    test_messages = [
        {"role": "user", "content": "请简单介绍一下你自己，用中文回答，不超过50字。"}
    ]
    
    print("\n发送测试请求...")
    prompt_tokens, completion_tokens, has_error, response = client.chat_completion(
        messages=test_messages,
        max_tokens=100,
        temperature=0.0
    )
    
    if not has_error:
        print("✅ API调用成功!")
        print(f"响应内容: {response.choices[0].message.content}")
        print(f"Token使用: {prompt_tokens} (prompt) + {completion_tokens} (completion) = {prompt_tokens + completion_tokens}")
    else:
        print("❌ API调用失败")
    
    # 打印统计信息
    client.print_stats()
    
    return not has_error

def main():
    """主函数"""
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("多API后端测试工具")
    print("=" * 50)
    
    # 检查环境变量
    api_keys = {
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY'),
        'SCHOOL_API_KEY': os.getenv('SCHOOL_API_KEY'),
        'API_KEY': os.getenv('API_KEY')
    }
    
    print("\n环境变量检查:")
    for key, value in api_keys.items():
        status = "已设置" if value else "未设置"
        print(f"  {key}: {status}")
    
    # 测试配置
    test_api_config()
    
    # 测试客户端
    if any(api_keys.values()):
        success = test_api_client()
        if success:
            print("\n🎉 所有测试通过！可以开始使用多API后端功能。")
        else:
            print("\n❌ 客户端测试失败，请检查API配置。")
    else:
        print("\n⚠️  没有设置API密钥，跳过客户端测试。")
        print("请设置以下环境变量之一：")
        print("  export OPENAI_API_KEY='your-openai-key'")
        print("  export SCHOOL_API_KEY='your-school-key'")
        print("  export API_KEY='your-api-key'")

if __name__ == "__main__":
    main()
