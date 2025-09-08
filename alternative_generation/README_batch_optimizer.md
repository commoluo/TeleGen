# 批量代码优化器使用指南

## 概述

`batch_code_optimizer.py` 是一个批量代码优化工具，能够：
1. 读取所有项目的JSX代码和console logs
2. 使用GPT-4进行代码优化
3. 保存优化结果和处理记录

## 主要功能

### 1. 批量优化所有项目
- 逐个处理所有99个项目
- 自动跳过已处理的项目
- 支持断点续传
- 保存详细的处理日志

### 2. 单项目优化
- 测试单个项目的优化流程
- 适合调试和验证

### 3. 重试失败项目
- 重新处理之前失败的项目
- 提高整体成功率

### 4. 进度管理
- 自动保存处理进度
- 支持中断后继续处理
- 详细的统计报告

## 使用方法

### 基本使用
```bash
cd /Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation
python batch_code_optimizer.py
```

### 程序化使用
```python
from batch_code_optimizer import BatchCodeOptimizer

# 创建优化器
optimizer = BatchCodeOptimizer()

# 批量优化所有项目
results = optimizer.batch_optimize_all_projects()

# 优化单个项目
result = optimizer.optimize_single_project("001_simple_project_runnable")

# 查看处理总结
summary = optimizer.get_optimization_summary()
```

## 需要用户补全的部分

### 1. 优化提示词 (`_create_optimization_prompt` 方法)
当前提示词模板已创建，但需要根据具体需求优化：

```python
def _create_optimization_prompt(self, project_name: str, frontend_code: str, console_logs: dict, error_analysis: dict) -> str:
    # TODO: 用户需要在此处补全更详细的提示词
    prompt = f"""
请优化以下React JSX代码，根据console logs中的错误信息修复问题。

项目: {project_name}
错误数量: {error_analysis.get('total_error_logs', 0)}

[在此处添加更具体的优化指导]
```

### 2. 消息格式 (`_create_messages` 方法)
当前使用基础的system/user格式，可以根据需要调整：

```python
def _create_messages(self, prompt: str) -> List[Dict]:
    # TODO: 用户需要在此处补全更详细的消息格式
    messages = [
        {
            "role": "system",
            "content": "你是一个专业的前端开发专家..."  # 可以更详细
        },
        {
            "role": "user", 
            "content": prompt
        }
    ]
    return messages
```

## 文件结构

```
alternative_generation/
├── batch_code_optimizer.py        # 主程序
├── optimized_code/                # 优化后的代码输出目录
│   ├── 001_simple_project_runnable_optimized.jsx
│   ├── 002_simple_project_runnable_optimized.jsx
│   └── ...
└── optimization_logs/             # 优化日志目录
    ├── optimization_progress.json # 处理进度
    ├── 001_simple_project_runnable_optimization_result.json
    ├── batch_optimization_20250820_143022.json
    └── ...
```

## 数据流程

1. **数据读取**: 使用 `CodeOptimizationDataReader` 读取项目数据
   - Frontend JSX代码 (`frontend_original.jsx`)
   - Console logs数据 (合并后的JSON)
   - 错误分析结果

2. **提示词生成**: 根据项目数据创建优化提示词
   - 包含原始代码
   - 包含错误信息
   - 包含修复建议

3. **API调用**: 使用 `UniversityAPIClient` 调用GPT-4
   - 复用现有的API客户端
   - 处理API响应和错误

4. **结果保存**: 保存优化结果
   - 优化后的代码文件 (`.jsx`)
   - 详细的处理结果 (`.json`)
   - 批量处理统计

## 配置选项

### 输出目录
```python
optimizer = BatchCodeOptimizer(
    output_dir="/path/to/optimized_code",
    log_dir="/path/to/optimization_logs"
)
```

### 批量处理选项
```python
# 从第10个项目开始处理
optimizer.batch_optimize_all_projects(start_from=10)

# 最多处理20个项目
optimizer.batch_optimize_all_projects(max_projects=20)

# 重新处理已处理的项目
optimizer.batch_optimize_all_projects(skip_existing=False)
```

## 错误处理

- **自动重试**: API调用失败时自动重试
- **进度保存**: 异常中断时保存当前进度
- **错误记录**: 详细记录所有错误信息
- **失败重试**: 可以单独重试失败的项目

## 性能优化

- **延迟控制**: 请求间隔2秒，避免API限制
- **断点续传**: 支持中断后继续处理
- **内存管理**: 逐个处理项目，避免内存溢出
- **日志压缩**: 大文件自动截断，保持日志可读性

## 监控和调试

### 实时监控
- 处理进度实时显示
- 成功/失败统计
- 错误信息即时反馈

### 详细日志
- 每个项目的完整处理记录
- API调用详情
- 错误堆栈跟踪

### 结果验证
- 优化前后代码对比
- Console logs分析
- 问题修复验证

## 示例输出

```
🚀 批量代码优化器
============================================================

📊 当前状态:
   已处理项目: 15
   失败项目: 2
   成功率: 88.2%

🎯 优化项目: 016_simple_project_runnable
--------------------------------------------------
📖 读取项目数据...
✅ 代码长度: 3542 字符
✅ 错误数量: 8
✅ 问题类型: 3
💭 创建优化提示词...
🤖 调用GPT-4进行代码优化...
✅ 优化完成，输出长度: 3678 字符
💾 优化代码已保存: /path/to/016_simple_project_runnable_optimized.jsx
💾 优化结果已保存: /path/to/016_simple_project_runnable_optimization_result.json
```

## 下一步工作

1. **补全提示词**: 根据具体需求优化提示词模板
2. **测试API调用**: 确保大模型调用正常工作
3. **验证结果**: 检查优化后的代码质量
4. **调整参数**: 根据效果调整temperature等参数
5. **批量处理**: 开始大规模的代码优化工作
