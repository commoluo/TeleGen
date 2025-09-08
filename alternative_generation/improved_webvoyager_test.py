#!/usr/bin/env python3
"""
改进的WebVoyager测试脚本，实现更好的速率限制和错误处理
"""

import json
import os
import sys
import time
import logging
from datetime import datetime
from typing import List, Dict, Any
import subprocess
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('webvoyager_improved_test.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class RateLimitedWebVoyagerTester:
    """
    带速率限制的WebVoyager测试器
    """
    
    def __init__(self, 
                 test_file: str,
                 max_concurrent_tasks: int = 2,
                 delay_between_tasks: float = 30.0,
                 max_retries: int = 3,
                 retry_delay: float = 60.0):
        """
        初始化测试器
        
        Args:
            test_file: 测试文件路径
            max_concurrent_tasks: 最大并发任务数
            delay_between_tasks: 任务间延迟（秒）
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
        """
        self.test_file = test_file
        self.max_concurrent_tasks = max_concurrent_tasks
        self.delay_between_tasks = delay_between_tasks
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # 创建输出目录
        self.output_dir = f"webvoyager_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 线程锁用于控制并发
        self.task_lock = threading.Lock()
        self.last_task_time = 0
        
        # 统计信息
        self.stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'rate_limit_errors': 0,
            'other_errors': 0,
            'start_time': None,
            'end_time': None
        }
        
    def load_tasks(self) -> List[Dict[str, Any]]:
        """加载测试任务"""
        tasks = []
        try:
            with open(self.test_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        tasks.append(json.loads(line))
            logger.info(f"已加载 {len(tasks)} 个测试任务")
            return tasks
        except Exception as e:
            logger.error(f"加载任务失败: {e}")
            return []
    
    def ensure_task_spacing(self):
        """确保任务间有足够的间隔"""
        with self.task_lock:
            current_time = time.time()
            time_since_last = current_time - self.last_task_time
            
            if time_since_last < self.delay_between_tasks:
                sleep_time = self.delay_between_tasks - time_since_last
                logger.info(f"等待 {sleep_time:.1f} 秒以避免速率限制...")
                time.sleep(sleep_time)
            
            self.last_task_time = time.time()
    
    def run_single_task(self, task: Dict[str, Any], attempt: int = 1) -> Dict[str, Any]:
        """
        运行单个任务
        
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
        
        # 构建WebVoyager命令
        cmd = [
            'python', 'webvoyager/run.py',
            '--test_file', self.test_file,
            '--output_dir', self.output_dir,
            '--num_workers', '1',  # 强制使用单进程
            '--headless',  # 无头模式
            '--api_key', os.getenv('OPENAI_API_KEY', 'key')
        ]
        
        # 创建任务临时文件
        task_file = f"{self.output_dir}/task_{task_id}_{attempt}.jsonl"
        with open(task_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(task) + '\n')
        
        cmd[3] = task_file  # 替换测试文件路径
        
        result = {
            'task_id': task_id,
            'attempt': attempt,
            'success': False,
            'error': None,
            'start_time': time.time(),
            'end_time': None,
            'output_file': None
        }
        
        try:
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
        
        return result
    
    def run_task_with_retries(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        带重试机制的任务执行
        
        Args:
            task: 任务配置
            
        Returns:
            最终执行结果
        """
        task_id = task.get('id', 'unknown')
        
        for attempt in range(1, self.max_retries + 2):
            result = self.run_single_task(task, attempt)
            
            if result['success']:
                self.stats['completed_tasks'] += 1
                return result
            
            # 如果是速率限制错误且还有重试机会，等待后重试
            if attempt <= self.max_retries and '429' in str(result.get('error', '')):
                logger.warning(f"任务 {task_id} 遇到速率限制，等待 {self.retry_delay} 秒后重试...")
                time.sleep(self.retry_delay)
                continue
            
            # 其他错误或重试次数用尽
            if attempt <= self.max_retries:
                logger.warning(f"任务 {task_id} 失败，等待 {self.retry_delay/2} 秒后重试...")
                time.sleep(self.retry_delay / 2)
        
        # 所有重试都失败了
        self.stats['failed_tasks'] += 1
        logger.error(f"任务 {task_id} 最终失败")
        return result
    
    def run_all_tasks(self, tasks: List[Dict[str, Any]]):
        """
        运行所有任务
        
        Args:
            tasks: 任务列表
        """
        self.stats['total_tasks'] = len(tasks)
        self.stats['start_time'] = time.time()
        
        logger.info(f"开始执行 {len(tasks)} 个任务，最大并发: {self.max_concurrent_tasks}")
        
        results = []
        
        # 使用线程池控制并发
        with ThreadPoolExecutor(max_workers=self.max_concurrent_tasks) as executor:
            # 提交所有任务
            future_to_task = {
                executor.submit(self.run_task_with_retries, task): task 
                for task in tasks
            }
            
            # 收集结果
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    # 打印进度
                    completed = self.stats['completed_tasks'] + self.stats['failed_tasks']
                    logger.info(f"进度: {completed}/{self.stats['total_tasks']} "
                              f"(成功: {self.stats['completed_tasks']}, "
                              f"失败: {self.stats['failed_tasks']})")
                    
                except Exception as exc:
                    task_id = task.get('id', 'unknown')
                    logger.error(f"任务 {task_id} 生成异常: {exc}")
                    self.stats['failed_tasks'] += 1
        
        self.stats['end_time'] = time.time()
        
        # 保存结果
        self.save_results(results)
        self.print_summary()
    
    def save_results(self, results: List[Dict[str, Any]]):
        """保存测试结果"""
        results_file = f"{self.output_dir}/test_results.json"
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'stats': self.stats,
            'results': results,
            'config': {
                'test_file': self.test_file,
                'max_concurrent_tasks': self.max_concurrent_tasks,
                'delay_between_tasks': self.delay_between_tasks,
                'max_retries': self.max_retries,
                'retry_delay': self.retry_delay
            }
        }
        
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"结果已保存到: {results_file}")
    
    def print_summary(self):
        """打印测试摘要"""
        duration = self.stats['end_time'] - self.stats['start_time']
        
        print("\n" + "="*60)
        print("测试摘要")
        print("="*60)
        print(f"总任务数: {self.stats['total_tasks']}")
        print(f"成功完成: {self.stats['completed_tasks']}")
        print(f"失败任务: {self.stats['failed_tasks']}")
        print(f"速率限制错误: {self.stats['rate_limit_errors']}")
        print(f"其他错误: {self.stats['other_errors']}")
        print(f"成功率: {self.stats['completed_tasks']/self.stats['total_tasks']*100:.1f}%")
        print(f"总耗时: {duration:.1f} 秒")
        print(f"平均每任务: {duration/self.stats['total_tasks']:.1f} 秒")
        print(f"输出目录: {self.output_dir}")
        print("="*60)

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='改进的WebVoyager测试脚本')
    parser.add_argument('--test_file', default='data/test.jsonl', help='测试文件路径')
    parser.add_argument('--max_concurrent', type=int, default=2, help='最大并发任务数')
    parser.add_argument('--delay', type=float, default=30.0, help='任务间延迟（秒）')
    parser.add_argument('--max_retries', type=int, default=3, help='最大重试次数')
    parser.add_argument('--retry_delay', type=float, default=60.0, help='重试延迟（秒）')
    parser.add_argument('--limit', type=int, help='限制测试任务数量')
    
    args = parser.parse_args()
    
    # 检查API密钥
    if not os.getenv('OPENAI_API_KEY'):
        print("错误: 请设置 OPENAI_API_KEY 环境变量")
        sys.exit(1)
    
    # 创建测试器
    tester = RateLimitedWebVoyagerTester(
        test_file=args.test_file,
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
