# WebVoyager改进测试配置文件

# API速率限制设置
RATE_LIMIT_CONFIG = {
    # 基础设置
    'max_concurrent_tasks': 2,          # 最大并发任务数（建议1-3）
    'delay_between_tasks': 30.0,        # 任务间延迟（秒）
    'max_retries': 3,                   # 最大重试次数
    'retry_delay': 60.0,                # 重试延迟（秒）
    
    # 高级设置
    'task_timeout': 300,                # 单任务超时时间（秒）
    'exponential_backoff': True,        # 是否启用指数退避
    'base_delay': 10.0,                 # 基础延迟（秒）
    'max_delay': 300.0,                 # 最大延迟（秒）
    
    # 监控设置
    'log_level': 'INFO',                # 日志级别
    'save_detailed_logs': True,         # 是否保存详细日志
    'monitor_api_usage': True,          # 是否监控API使用情况
}

# 不同场景的预设配置
PRESET_CONFIGS = {
    'conservative': {
        'max_concurrent_tasks': 1,
        'delay_between_tasks': 60.0,
        'max_retries': 5,
        'retry_delay': 120.0,
        'description': '保守模式：最慢但最稳定'
    },
    
    'balanced': {
        'max_concurrent_tasks': 2,
        'delay_between_tasks': 30.0,
        'max_retries': 3,
        'retry_delay': 60.0,
        'description': '平衡模式：速度和稳定性的平衡'
    },
    
    'aggressive': {
        'max_concurrent_tasks': 3,
        'delay_between_tasks': 15.0,
        'max_retries': 2,
        'retry_delay': 30.0,
        'description': '积极模式：更快但可能遇到更多速率限制'
    },
    
    'testing': {
        'max_concurrent_tasks': 1,
        'delay_between_tasks': 10.0,
        'max_retries': 1,
        'retry_delay': 20.0,
        'description': '测试模式：快速测试少量任务'
    }
}

# OpenAI API相关设置
OPENAI_CONFIG = {
    'model': 'gpt-4o',
    'max_tokens': 1000,
    'timeout': 60,
    'temperature': 0.0,
    
    # 速率限制相关
    'requests_per_minute': 60,          # 每分钟请求数限制
    'tokens_per_minute': 60000,         # 每分钟token限制
    'requests_per_day': 10000,          # 每天请求数限制
}

# 错误处理设置
ERROR_HANDLING = {
    'rate_limit_errors': {
        'initial_delay': 60.0,          # 首次遇到429错误的延迟
        'max_delay': 300.0,             # 最大延迟
        'backoff_factor': 2.0,          # 退避因子
        'max_attempts': 5,              # 最大尝试次数
    },
    
    'api_errors': {
        'initial_delay': 30.0,
        'max_delay': 180.0,
        'backoff_factor': 1.5,
        'max_attempts': 3,
    },
    
    'network_errors': {
        'initial_delay': 10.0,
        'max_delay': 60.0,
        'backoff_factor': 2.0,
        'max_attempts': 5,
    }
}

# 监控和报告设置
MONITORING = {
    'enable_progress_bar': True,
    'progress_update_interval': 10,     # 进度更新间隔（秒）
    'save_intermediate_results': True,  # 保存中间结果
    'generate_html_report': True,       # 生成HTML报告
    'track_api_costs': True,           # 跟踪API成本
}

# 文件和目录设置
FILE_CONFIG = {
    'output_dir_prefix': 'webvoyager_results',
    'log_file_prefix': 'webvoyager_test',
    'backup_results': True,            # 备份结果
    'compress_logs': True,             # 压缩日志
    'cleanup_temp_files': True,        # 清理临时文件
}
