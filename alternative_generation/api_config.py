#!/usr/bin/env python3
"""
API配置管理器 - 支持OpenAI和学校API
"""

import os
from typing import Dict, Any, Optional

class APIConfig:
    """API配置管理器"""
    
    # 预定义的API配置
    PROVIDERS = {
        'openai': {
            'name': 'OpenAI',
            'base_url': 'https://api.openai.com/v1',
            'models': ['gpt-4o', 'gpt-4', 'gpt-3.5-turbo'],
            'default_model': 'gpt-4o',
            'requires_key': True,
            'rate_limits': {
                'requests_per_minute': 60,
                'tokens_per_minute': 60000,
                'requests_per_day': 10000
            }
        },
        
        'school': {
            'name': '学校API',
            'base_url': 'https://oneapi.xty.app/v1',  # 学校API基础URL
            'models': ['gpt-4o', 'gpt-4', 'gpt-3.5-turbo'],
            'default_model': 'gpt-4o',
            'requires_key': True,
            'rate_limits': {
                'requests_per_minute': 200,  # 学校API通常有更高的限制
                'tokens_per_minute': 200000,
                'requests_per_day': 50000
            }
        },
        
        'custom': {
            'name': '自定义API',
            'base_url': None,  # 需要用户指定
            'models': ['gpt-4o', 'gpt-4', 'gpt-3.5-turbo'],
            'default_model': 'gpt-4o',
            'requires_key': True,
            'rate_limits': {
                'requests_per_minute': 100,
                'tokens_per_minute': 100000,
                'requests_per_day': 20000
            }
        }
    }
    
    def __init__(self, provider: str = 'openai', custom_base_url: Optional[str] = None):
        """
        初始化API配置
        
        Args:
            provider: API提供商 ('openai', 'school', 'custom')
            custom_base_url: 自定义API基础URL
        """
        self.provider = provider
        self.config = self.PROVIDERS.get(provider, self.PROVIDERS['openai'])
        
        if provider == 'custom' and custom_base_url:
            self.config['base_url'] = custom_base_url
        
        # 从环境变量获取API密钥
        self.api_key = self._get_api_key()
        
    def _get_api_key(self) -> Optional[str]:
        """获取API密钥"""
        key_env_names = [
            f'{self.provider.upper()}_API_KEY',
            'OPENAI_API_KEY',
            'API_KEY'
        ]
        
        for env_name in key_env_names:
            key = os.getenv(env_name)
            if key:
                return key
        
        return None
    
    def get_client_config(self) -> Dict[str, Any]:
        """获取OpenAI客户端配置"""
        config = {
            'api_key': self.api_key,
        }
        
        # 如果不是OpenAI官方API，需要设置base_url
        if self.provider != 'openai' and self.config['base_url']:
            config['base_url'] = self.config['base_url']
        
        return config
    
    def get_model(self, model_name: Optional[str] = None) -> str:
        """获取模型名称"""
        if model_name and model_name in self.config['models']:
            return model_name
        return self.config['default_model']
    
    def get_rate_limits(self) -> Dict[str, int]:
        """获取速率限制配置"""
        return self.config['rate_limits'].copy()
    
    def validate(self) -> bool:
        """验证配置是否有效"""
        if self.config['requires_key'] and not self.api_key:
            return False
        
        if self.provider == 'custom' and not self.config['base_url']:
            return False
        
        return True
    
    def get_description(self) -> str:
        """获取配置描述"""
        return f"{self.config['name']} - {self.config['base_url']}"

# 预定义的配置实例
def get_openai_config() -> APIConfig:
    """获取OpenAI配置"""
    return APIConfig('openai')

def get_school_config() -> APIConfig:
    """获取学校API配置"""
    return APIConfig('school')

def get_custom_config(base_url: str) -> APIConfig:
    """获取自定义API配置"""
    return APIConfig('custom', base_url)

# 自动检测最佳配置
def get_best_config() -> APIConfig:
    """自动检测最佳可用配置"""
    # 优先尝试学校API
    school_config = get_school_config()
    if school_config.validate():
        return school_config
    
    # 其次尝试OpenAI
    openai_config = get_openai_config()
    if openai_config.validate():
        return openai_config
    
    # 返回默认配置
    return openai_config

if __name__ == "__main__":
    # 测试配置
    print("测试API配置:")
    
    configs = [
        ('OpenAI', get_openai_config()),
        ('学校API', get_school_config()),
        ('自定义API', get_custom_config('https://api.example.com/v1'))
    ]
    
    for name, config in configs:
        print(f"\n{name}:")
        print(f"  有效: {config.validate()}")
        print(f"  描述: {config.get_description()}")
        print(f"  API密钥: {'已设置' if config.api_key else '未设置'}")
        print(f"  默认模型: {config.get_model()}")
        print(f"  速率限制: {config.get_rate_limits()}")
    
    print(f"\n最佳配置: {get_best_config().get_description()}")
