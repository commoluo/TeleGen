#!/usr/bin/env python3
"""
支持多API后端的WebVoyager客户端
"""

import time
import logging
from typing import Dict, Any, Optional, Tuple
from openai import OpenAI
from api_config import APIConfig, get_best_config

class MultiAPIClient:
    """
    支持多API后端的客户端
    """
    
    def __init__(self, 
                 api_config: Optional[APIConfig] = None,
                 model: Optional[str] = None,
                 max_retries: int = 5,
                 initial_delay: float = 10.0,
                 max_delay: float = 300.0,
                 backoff_factor: float = 2.0):
        """
        初始化多API客户端
        
        Args:
            api_config: API配置，如果为None则自动检测
            model: 模型名称
            max_retries: 最大重试次数
            initial_delay: 初始延迟时间
            max_delay: 最大延迟时间
            backoff_factor: 退避因子
        """
        self.api_config = api_config or get_best_config()
        self.model = model or self.api_config.get_model()
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        
        # 初始化OpenAI客户端
        self.client = self._create_client()
        
        # 统计信息
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'rate_limit_errors': 0,
            'other_errors': 0,
            'total_tokens': 0,
            'total_cost': 0.0
        }
        
        logging.info(f"使用API配置: {self.api_config.get_description()}")
        logging.info(f"使用模型: {self.model}")
    
    def _create_client(self) -> OpenAI:
        """创建OpenAI客户端"""
        config = self.api_config.get_client_config()
        return OpenAI(**config)
    
    def _calculate_delay(self, attempt: int) -> float:
        """计算延迟时间"""
        delay = self.initial_delay * (self.backoff_factor ** (attempt - 1))
        return min(delay, self.max_delay)
    
    def _handle_error(self, error: Exception, attempt: int) -> bool:
        """
        处理API错误
        
        Args:
            error: 异常对象
            attempt: 当前尝试次数
            
        Returns:
            是否应该重试
        """
        error_type = type(error).__name__
        
        if error_type == "RateLimitError":
            self.stats['rate_limit_errors'] += 1
            if attempt < self.max_retries:
                delay = self._calculate_delay(attempt)
                logging.warning(f"遇到速率限制错误，等待 {delay:.1f} 秒后重试 (尝试 {attempt}/{self.max_retries})")
                time.sleep(delay)
                return True
        
        elif error_type == "APIError":
            self.stats['other_errors'] += 1
            if attempt < self.max_retries:
                delay = self._calculate_delay(attempt) / 2  # API错误使用较短延迟
                logging.warning(f"遇到API错误: {error}，等待 {delay:.1f} 秒后重试 (尝试 {attempt}/{self.max_retries})")
                time.sleep(delay)
                return True
        
        elif error_type == "InvalidRequestError":
            self.stats['other_errors'] += 1
            logging.error(f"无效请求错误: {error}")
            return False
        
        else:
            self.stats['other_errors'] += 1
            if attempt < self.max_retries:
                delay = self._calculate_delay(attempt) / 3  # 其他错误使用最短延迟
                logging.warning(f"遇到未知错误: {error}，等待 {delay:.1f} 秒后重试 (尝试 {attempt}/{self.max_retries})")
                time.sleep(delay)
                return True
        
        return False
    
    def chat_completion(self, 
                       messages: list,
                       max_tokens: int = 1000,
                       temperature: float = 0.0,
                       timeout: int = 60,
                       **kwargs) -> Tuple[Optional[int], Optional[int], bool, Optional[Any]]:
        """
        调用聊天完成API
        
        Args:
            messages: 消息列表
            max_tokens: 最大token数
            temperature: 温度参数
            timeout: 超时时间
            **kwargs: 其他参数
            
        Returns:
            (prompt_tokens, completion_tokens, has_error, response)
        """
        self.stats['total_requests'] += 1
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logging.info(f"调用 {self.model} API (尝试 {attempt}/{self.max_retries})")
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout,
                    **kwargs
                )
                
                # 成功获取响应
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                total_tokens = prompt_tokens + completion_tokens
                
                self.stats['successful_requests'] += 1
                self.stats['total_tokens'] += total_tokens
                
                logging.info(f"API调用成功 - Prompt: {prompt_tokens}, Completion: {completion_tokens}, Total: {total_tokens}")
                
                return prompt_tokens, completion_tokens, False, response
                
            except Exception as error:
                logging.error(f"API调用失败: {type(error).__name__}: {error}")
                
                if not self._handle_error(error, attempt):
                    # 不可重试的错误
                    break
        
        # 所有重试都失败了
        self.stats['failed_requests'] += 1
        logging.error(f"API调用最终失败，已重试 {self.max_retries} 次")
        return None, None, True, None
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self.stats.copy()
        stats['success_rate'] = (
            stats['successful_requests'] / stats['total_requests'] * 100
            if stats['total_requests'] > 0 else 0
        )
        stats['api_provider'] = self.api_config.provider
        stats['model'] = self.model
        return stats
    
    def print_stats(self):
        """打印统计信息"""
        stats = self.get_stats()
        print("\n" + "="*50)
        print("API调用统计")
        print("="*50)
        print(f"API提供商: {stats['api_provider']}")
        print(f"模型: {stats['model']}")
        print(f"总请求数: {stats['total_requests']}")
        print(f"成功请求: {stats['successful_requests']}")
        print(f"失败请求: {stats['failed_requests']}")
        print(f"速率限制错误: {stats['rate_limit_errors']}")
        print(f"其他错误: {stats['other_errors']}")
        print(f"成功率: {stats['success_rate']:.1f}%")
        print(f"总Token数: {stats['total_tokens']}")
        print("="*50)

# 用于替换原始WebVoyager中的call_gpt4v_api函数
def call_gpt4v_api_improved(args, client: MultiAPIClient, messages):
    """
    改进的GPT-4V API调用函数
    
    Args:
        args: 命令行参数
        client: MultiAPIClient实例
        messages: 消息列表
        
    Returns:
        (prompt_tokens, completion_tokens, has_error, response)
    """
    return client.chat_completion(
        messages=messages,
        max_tokens=getattr(args, 'max_tokens', 1000),
        temperature=getattr(args, 'temperature', 0.0),
        timeout=getattr(args, 'timeout', 60)
    )

if __name__ == "__main__":
    # 测试客户端
    import os
    
    # 设置日志
    logging.basicConfig(level=logging.INFO)
    
    # 测试消息
    test_messages = [
        {"role": "user", "content": "Hello, how are you?"}
    ]
    
    # 测试不同的API配置
    from api_config import get_openai_config, get_school_config
    
    configs = [
        ("学校API", get_school_config()),
        ("OpenAI", get_openai_config()),
    ]
    
    for name, config in configs:
        if config.validate():
            print(f"\n测试 {name}:")
            client = MultiAPIClient(config)
            
            # 发送测试请求
            prompt_tokens, completion_tokens, has_error, response = client.chat_completion(test_messages)
            
            if not has_error:
                print(f"成功! 响应: {response.choices[0].message.content[:100]}...")
            else:
                print("失败!")
            
            client.print_stats()
        else:
            print(f"\n{name} 配置无效，跳过测试")
