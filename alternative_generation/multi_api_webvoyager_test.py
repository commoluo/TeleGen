#!/usr/bin/env python3
"""
修改版WebVoyager运行脚本，支持多API后端
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_config import APIConfig, get_openai_config, get_school_config, get_best_config
from multi_api_client import MultiAPIClient
from improved_webvoyager_test import RateLimitedWebVoyagerTester

# 设置日志
logger = logging.getLogger(__name__)

class MultiAPIWebVoyagerTester(RateLimitedWebVoyagerTester):
    """
    支持多API后端的WebVoyager测试器
    """
    
    def __init__(self, 
                 test_file: str,
                 api_provider: str = 'auto',
                 api_base_url: str = None,
                 model: str = None,
                 max_concurrent_tasks: int = 2,
                 delay_between_tasks: float = 30.0,
                 max_retries: int = 3,
                 retry_delay: float = 60.0):
        """
        初始化多API测试器
        
        Args:
            test_file: 测试文件路径
            api_provider: API提供商 ('openai', 'school', 'auto')
            api_base_url: 自定义API基础URL
            model: 模型名称
            max_concurrent_tasks: 最大并发任务数
            delay_between_tasks: 任务间延迟（秒）
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
        """
        super().__init__(test_file, max_concurrent_tasks, delay_between_tasks, max_retries, retry_delay)
        
        # 设置API配置
        self.api_config = self._setup_api_config(api_provider, api_base_url)
        self.model = model or self.api_config.get_model()
        
        # 创建API客户端
        self.api_client = MultiAPIClient(
            api_config=self.api_config,
            model=self.model,
            max_retries=max_retries,
            initial_delay=retry_delay,
            max_delay=retry_delay * 5,
            backoff_factor=2.0
        )
        
        logger.info(f"使用API提供商: {self.api_config.provider}")
        logger.info(f"API基础URL: {self.api_config.config['base_url']}")
        logger.info(f"使用模型: {self.model}")
    
    def _setup_api_config(self, provider: str, base_url: str = None) -> APIConfig:
        """设置API配置"""
        if provider == 'auto':
            return get_best_config()
        elif provider == 'openai':
            return get_openai_config()
        elif provider == 'school':
            return get_school_config()
        elif provider == 'custom' and base_url:
            from api_config import get_custom_config
            return get_custom_config(base_url)
        else:
            logger.warning(f"未知的API提供商: {provider}，使用自动检测")
            return get_best_config()
    
    def run_single_task(self, task: Dict[str, Any], attempt: int = 1) -> Dict[str, Any]:
        """
        运行单个任务，使用多API后端
        
        Args:
            task: 任务配置
            attempt: 当前尝试次数
            
        Returns:
            任务执行结果
        """
        task_id = task.get('id', 'unknown')
        logger.info(f"开始执行任务 {task_id} (尝试 {attempt}/{self.max_retries + 1})")
        
        # 确保任务间隔
        self.ensure_task_spacing()
        
        # 创建任务临时文件
        task_file = f"{self.output_dir}/task_{task_id}_{attempt}.jsonl"
        with open(task_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(task) + '\n')
        
        # 构建修改版WebVoyager命令
        cmd = [
            'python', 
            os.path.join(os.path.dirname(__file__), 'webvoyager_multi_api.py'),
            '--test_file', task_file,
            '--output_dir', self.output_dir,
            '--api_provider', self.api_config.provider,
            '--api_model', self.model,
            '--headless',  # 无头模式
            '--max_iter', '5',
            '--num_workers', '1',  # 强制使用单进程
        ]
        
        # 添加API配置
        if self.api_config.config.get('base_url'):
            cmd.extend(['--api_base_url', self.api_config.config['base_url']])
        
        if self.api_config.api_key:
            cmd.extend(['--api_key', self.api_config.api_key])
        
        result = {
            'task_id': task_id,
            'attempt': attempt,
            'success': False,
            'error': None,
            'start_time': time.time(),
            'end_time': None,
            'output_file': None,
            'api_stats': None
        }
        
        try:
            import subprocess
            import time
            
            # 执行WebVoyager
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.dirname(os.path.abspath(__file__)) + '/..'
            )
            
            stdout, stderr = process.communicate(timeout=300)  # 5分钟超时
            
            result['end_time'] = time.time()
            result['duration'] = result['end_time'] - result['start_time']
            
            if process.returncode == 0:
                result['success'] = True
                result['output_file'] = f"{self.output_dir}/task_{task_id}"
                logger.info(f"任务 {task_id} 执行成功")
            else:
                result['error'] = f"进程返回码: {process.returncode}"
                result['stderr'] = stderr
                logger.error(f"任务 {task_id} 执行失败: {stderr}")
                
                # 检查是否是速率限制错误
                if '429' in stderr or 'rate limit' in stderr.lower():
                    self.stats['rate_limit_errors'] += 1
                    raise Exception(f"Speed limit error: {stderr}")
                else:
                    self.stats['other_errors'] += 1
                    
        except subprocess.TimeoutExpired:
            process.kill()
            result['error'] = "任务超时"
            result['end_time'] = time.time()
            logger.error(f"任务 {task_id} 超时")
            
        except Exception as e:
            result['error'] = str(e)
            result['end_time'] = time.time()
            logger.error(f"任务 {task_id} 异常: {e}")
            
        finally:
            # 清理临时文件
            if os.path.exists(task_file):
                os.remove(task_file)
        
        # 获取API统计信息
        result['api_stats'] = self.api_client.get_stats()
        
        return result
    
    def print_summary(self):
        """打印测试摘要，包括API统计"""
        super().print_summary()
        
        # 打印API统计
        self.api_client.print_stats()

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='支持多API后端的WebVoyager测试脚本')
    parser.add_argument('--test_file', default='../data/test.jsonl', help='测试文件路径')
    parser.add_argument('--api_provider', default='auto', 
                       choices=['auto', 'openai', 'school', 'custom'],
                       help='API提供商')
    parser.add_argument('--api_base_url', help='自定义API基础URL')
    parser.add_argument('--model', help='模型名称')
    parser.add_argument('--max_concurrent', type=int, default=2, help='最大并发任务数')
    parser.add_argument('--delay', type=float, default=30.0, help='任务间延迟（秒）')
    parser.add_argument('--max_retries', type=int, default=3, help='最大重试次数')
    parser.add_argument('--retry_delay', type=float, default=60.0, help='重试延迟（秒）')
    parser.add_argument('--limit', type=int, help='限制测试任务数量')
    
    args = parser.parse_args()
    
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'multi_api_webvoyager_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
            logging.StreamHandler()
        ]
    )
    
    # 检查API配置
    if args.api_provider == 'custom' and not args.api_base_url:
        print("错误: 使用自定义API时必须指定 --api_base_url")
        sys.exit(1)
    
    # 创建测试器
    tester = MultiAPIWebVoyagerTester(
        test_file=args.test_file,
        api_provider=args.api_provider,
        api_base_url=args.api_base_url,
        model=args.model,
        max_concurrent_tasks=args.max_concurrent,
        delay_between_tasks=args.delay,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay
    )
    
    # 加载任务
    tasks = tester.load_tasks()
    if not tasks:
        print("没有找到任务，退出")
        sys.exit(1)
    
    # 限制任务数量
    if args.limit:
        tasks = tasks[:args.limit]
        print(f"限制任务数量为: {len(tasks)}")
    
    # 运行测试
    try:
        tester.run_all_tasks(tasks)
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)

if __name__ == "__main__":
    main()
