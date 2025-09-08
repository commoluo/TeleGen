"""
API Documentation Generator
读取test.jsonl数据，根据instruction生成前后端交互的API文档
"""
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from api_client import UniversityAPIClient
from config import DEFAULT_MODEL

class APIDocumentationGenerator:
    """API文档生成器"""
    
    def __init__(self, model: str = DEFAULT_MODEL, output_dir: str = None):
        """
        初始化API文档生成器
        
        Args:
            model: 使用的大模型名称
            output_dir: 输出目录，默认为当前目录下的api_docs
        """
        self.client = UniversityAPIClient(model)
        
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path("api_docs")
        
        self.ensure_output_directory()
        
        # API文档生成的prompt模板（后续可以补充）
        self.api_doc_prompt = ""
    
    def ensure_output_directory(self):
        """确保输出目录存在"""
        self.output_dir.mkdir(exist_ok=True)
    
    def set_prompt(self, prompt: str):
        """
        设置API文档生成的prompt
        
        Args:
            prompt: API文档生成的提示词
        """
        self.api_doc_prompt = prompt
    
    def read_test_data(self, file_path: str = "../data/test.jsonl") -> List[Dict[str, Any]]:
        """
        读取test.jsonl文件中的数据
        
        Args:
            file_path: jsonl文件路径
            
        Returns:
            包含所有记录的列表
        """
        try:
            data = []
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():  # 跳过空行
                        record = json.loads(line.strip())
                        data.append(record)
            
            print(f"✅ 成功读取 {len(data)} 条数据")
            return data
            
        except FileNotFoundError:
            print(f"❌ 文件未找到: {file_path}")
            return []
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析错误: {e}")
            return []
        except Exception as e:
            print(f"❌ 读取文件时发生错误: {e}")
            return []
    
    def generate_api_doc_for_instruction(
        self, 
        instruction: str, 
        record_id: str = None,
        max_tokens: int = 4000
    ) -> Dict[str, Any]:
        """
        根据instruction生成API文档
        
        Args:
            instruction: 项目描述指令
            record_id: 记录ID（可选）
            max_tokens: 最大token数
            
        Returns:
            包含生成结果的字典
        """
        if not self.api_doc_prompt:
            return {
                "success": False,
                "error": "API文档生成prompt未设置，请先调用set_prompt()方法",
                "record_id": record_id,
                "instruction": instruction
            }
        
        # 构建完整的prompt
        full_prompt = f"Task Requirements:\n{instruction}\n\n{self.api_doc_prompt}\n\n"
        
        print(f"🔧 正在为记录 {record_id} 生成API文档...")
        
        messages = [
            {
                "role": "system",
                "content": "You are an expert Senior Software Architect. Your mission is to generate a comprehensive REST API specification based on the provided **Task Requirements**. This specification will serve as the **Single Source of Truth**—a definitive contract for generating both frontend and backend code. Ambiguity is not acceptable."
            },
            {
                "role": "user",
                "content": full_prompt
            }
        ]
        
        start_time = time.time()
        
        try:
            response = self.client.chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            generation_time = time.time() - start_time
            
            if "error" in response:
                return {
                    "success": False,
                    "error": response["error"],
                    "record_id": record_id,
                    "instruction": instruction,
                    "generation_time": generation_time
                }
            
            if "choices" not in response or len(response["choices"]) == 0:
                return {
                    "success": False,
                    "error": "API响应中没有生成内容",
                    "record_id": record_id,
                    "instruction": instruction,
                    "generation_time": generation_time
                }
            
            generated_content = response["choices"][0].get("message", {}).get("content", "")
            
            if not generated_content.strip():
                return {
                    "success": False,
                    "error": "生成的API文档内容为空",
                    "record_id": record_id,
                    "instruction": instruction,
                    "generation_time": generation_time
                }
            
            return {
                "success": True,
                "record_id": record_id,
                "instruction": instruction,
                "api_documentation": generated_content,
                "generation_time": generation_time,
                "content_length": len(generated_content),
                "timestamp": datetime.now().isoformat(),
                "api_response": response.get("usage", {})
            }
            
        except Exception as e:
            generation_time = time.time() - start_time
            return {
                "success": False,
                "error": f"调用API时发生异常: {str(e)}",
                "record_id": record_id,
                "instruction": instruction,
                "generation_time": generation_time
            }
    
    def generate_single_api_doc(self, record_id: str, instruction: str) -> Dict[str, Any]:
        """
        为单个记录生成API文档并保存
        
        Args:
            record_id: 记录ID
            instruction: 项目描述
            
        Returns:
            生成结果
        """
        result = self.generate_api_doc_for_instruction(instruction, record_id)
        
        if result["success"]:
            # 保存API文档
            doc_file = self.output_dir / f"api_doc_{record_id}.md"
            with open(doc_file, 'w', encoding='utf-8') as f:
                f.write(result["api_documentation"])
            
            # 保存元数据
            metadata_file = self.output_dir / f"metadata_{record_id}.json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 记录 {record_id} API文档生成成功")
            print(f"   文档长度: {result['content_length']} 字符")
            print(f"   生成耗时: {result['generation_time']:.2f}秒")
            print(f"   文档文件: {doc_file}")
            
        else:
            print(f"❌ 记录 {record_id} API文档生成失败: {result.get('error', 'Unknown error')}")
        
        return result
    
    def generate_batch_api_docs(
        self, 
        data: List[Dict[str, Any]] = None,
        start_index: int = 0,
        end_index: int = None,
        delay_seconds: float = 2.0
    ) -> Dict[str, Any]:
        """
        批量生成API文档
        
        Args:
            data: 数据列表，如果为None则自动读取test.jsonl
            start_index: 开始索引
            end_index: 结束索引，如果为None则处理到最后
            delay_seconds: 每次调用间的延迟时间（秒）
            
        Returns:
            批量处理结果
        """
        if data is None:
            data = self.read_test_data()
        
        if not data:
            return {
                "success": False,
                "error": "没有可处理的数据"
            }
        
        if end_index is None:
            end_index = len(data)
        
        end_index = min(end_index, len(data))
        
        print(f"\n🚀 开始批量生成API文档")
        print(f"处理范围: {start_index} - {end_index - 1}")
        print(f"总共 {end_index - start_index} 条记录")
        print("=" * 60)
        
        results = []
        successful_count = 0
        failed_count = 0
        
        start_time = time.time()
        
        for i in range(start_index, end_index):
            record = data[i]
            record_id = record.get("id", f"record_{i}")
            instruction = record.get("instruction", "")
            
            print(f"\n--- 处理记录 {i + 1}/{end_index}: {record_id} ---")
            
            if not instruction:
                print(f"⚠️  记录 {record_id} 缺少instruction字段，跳过")
                results.append({
                    "record_id": record_id,
                    "success": False,
                    "error": "缺少instruction字段"
                })
                failed_count += 1
                continue
            
            result = self.generate_single_api_doc(record_id, instruction)
            results.append(result)
            
            if result["success"]:
                successful_count += 1
            else:
                failed_count += 1
            
            # 添加延迟避免API限制
            if i < end_index - 1:  # 最后一次不需要延迟
                print(f"⏳ 等待 {delay_seconds} 秒...")
                time.sleep(delay_seconds)
        
        total_time = time.time() - start_time
        
        # 创建批量处理总结
        batch_summary = {
            "total_processed": end_index - start_index,
            "successful_count": successful_count,
            "failed_count": failed_count,
            "success_rate": successful_count / (end_index - start_index) if (end_index - start_index) > 0 else 0,
            "total_time": total_time,
            "start_index": start_index,
            "end_index": end_index,
            "delay_seconds": delay_seconds,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        
        # 保存批量处理总结
        summary_file = self.output_dir / f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(batch_summary, f, indent=2, ensure_ascii=False)
        
        print(f"\n📊 批量处理完成!")
        print(f"   总处理数: {batch_summary['total_processed']}")
        print(f"   成功数: {successful_count}")
        print(f"   失败数: {failed_count}")
        print(f"   成功率: {batch_summary['success_rate']:.1%}")
        print(f"   总耗时: {total_time:.2f}秒")
        print(f"   总结文件: {summary_file}")
        
        return batch_summary

# 使用示例和测试函数
def main():
    """主函数，用于测试"""
    
    # 创建API文档生成器
    generator = APIDocumentationGenerator()
    
    # 设置prompt（这里先设置一个示例，您可以后续修改）
    example_prompt = API_PROMPT_STRING = """
You are an expert Senior Software Architect. Your mission is to generate a comprehensive REST API specification based on the provided **Task Requirements**. This specification will serve as the **Single Source of Truth**—a definitive contract for generating both frontend and backend code. Ambiguity is not acceptable.


---

### Core Directives (Adhere Strictly)
1.  **Single Source of Truth:** This output is the **only** specification. All code will be based *exactly* on this document.
2.  **Stateless & In-Memory:** The backend must use a stateless, in-memory JavaScript data store (e.g., `let data = {...}`). No database logic.
3.  **Strict Adherence to Schema:** You must follow the markdown structure, JSON shapes, and naming conventions defined below without deviation.
4.  **Naming Convention:**
    * **Models:** Use **PascalCase** and **singular** (e.g., `TodoItem`, `UserProfile`).
    * **Endpoints:** Use **kebab-case** and **plural** (e.g., `/api/todo-items`, `/api/user-profiles`).

---

### API Specification Output (Use This Exact Format)

```markdown
# [Project Name] API Documentation

## 1. Core Specifications
- **Base URL:** `http://localhost:5001/api`
- **Data Storage:** In-memory JavaScript arrays/objects.
- **ID Generation:** Timestamp-based strings: `Date.now().toString()`
- **Date Fields:** ISO 8601 format: `new Date().toISOString()`
- **Standard Response Wrapper:** ALL responses (success and error) **MUST** use this exact wrapper. On failure, `data` is `null` and `error` contains the details.
  ```json
  {
    "success": boolean,
    "data": any | null,
    "error": { "message": string, "details"?: { [key: string]: string } } | null
  }
  ```

## 2. API Endpoints
*A complete and unambiguous summary of all available endpoints for code generation.*
| Method | Path                  | Purpose                       | Request Body        | Success Response (`data`) |
|--------|-----------------------|-------------------------------|---------------------|---------------------------|
| GET    | /api/[resource-names] | Get all resources             | None                | `[ModelName][]`           |
| POST   | /api/[resource-names] | Create a new resource         | `Create[ModelName]` | `[ModelName]`             |
| GET    | /api/[resource-names]/:id | Get a single resource by ID   | None                | `[ModelName]`             |
| PATCH  | /api/[resource-names]/:id | Update an existing resource   | `Update[ModelName]` | `[ModelName]`             |
| DELETE | /api/[resource-names]/:id | Delete a resource by ID       | None                | `{ "id": string }`        |

## 3. Data Models
*Define the data structures below based **directly** on the Task Requirements. Replace all placeholder fields (`field1`, `field2`, etc.) with specific fields, types, and validation rule comments.*

### [ModelName] (Backend Storage Model)
```typescript
{
  "id": string;        // Primary Key
  "field1": string;      // Example: Required, 3-100 chars
  "field2"?: number;     // Example: Optional, min 0
  "createdAt": string;   // ISO 8601 Date
  "updatedAt": string;   // ISO 8601 Date
}
```

### Create[ModelName] (For POST)
*All fields required to create a resource. Omit `id`, `createdAt`, and `updatedAt`.*
```typescript
{
  "field1": string;
  "field2"?: number;
}
```

### Update[ModelName] (For PATCH)
*All fields are optional for partial updates.*
```typescript
{
  "field1"?: string;
  "field2"?: number;
}
```

## 4. Endpoint Logic & Validation
*Detailed business logic for each endpoint, derived from the data models.*

### POST /api/[resource-names]
- **Validation:** Enforce all constraints defined in the `[ModelName]` model.
- **Success (201):** Generate `id` and timestamps, add the new resource to the store, and return it.
- **Failure (400):** Return a standard error response if validation fails.

### PATCH /api/[resource-names]/:id
- **Validation:** ID must exist (404 if not). Body fields must meet model constraints.
- **Success (200):** Update fields and `updatedAt`, then return the full, updated resource.

## 5. Backend Initial State
*The initial mock data for the in-memory store, matching the defined `[ModelName]`.*
```javascript
const dataStore = {
  "[resource-names]": [
    {
      "id": "1735693200001",
      "field1": "Sample Value 1",
      "field2": 100,
      "createdAt": "2024-01-01T00:00:00.000Z",
      "updatedAt": "2024-01-01T00:00:00.000Z"
    }
  ]
};
```
```
"""

    
    generator.set_prompt(example_prompt)
    
    # 读取测试数据
    data = generator.read_test_data()
    
    if data:
        print(f"找到 {len(data)} 条记录")
        
        # 选择处理模式
        choice = input("\n选择处理模式:\n1. 处理单个记录\n2. 批量处理前5条记录\n3. 批量处理所有记录\n请输入选择 (1/2/3): ")
        
        if choice == "1":
            # 处理单个记录
            record_id = data[0].get("id", "000001")
            instruction = data[0].get("instruction", "")
            result = generator.generate_single_api_doc(record_id, instruction)
            
        elif choice == "2":
            # 批量处理前5条记录
            generator.generate_batch_api_docs(data, start_index=0, end_index=5)
            
        elif choice == "3":
            # 批量处理所有记录
            generator.generate_batch_api_docs(data)
            
        else:
            print("无效选择")
    else:
        print("没有找到可处理的数据")

if __name__ == "__main__":
    main()
