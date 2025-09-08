
import json
from fullstack_generator import FullStackGenerator

def main():
    """
    测试单个项目生成，并利用API文档
    """
    # 1. 从 ../data/test.jsonl 加载第一条指令
    instruction = ""
    try:
        with open('../data/test.jsonl', 'r', encoding='utf-8') as f:
            first_line = f.readline()
            if first_line:
                data = json.loads(first_line)
                instruction = data.get("instruction", "")
    except Exception as e:
        print(f"❌ 读取测试数据失败: {e}")
        return

    if not instruction:
        print("❌ 未找到可用于测试的指令。")
        return

    print("✅ 成功加载测试指令。")

    # 2. 初始化生成器
    # FullStackGenerator 默认会将输出目录设置在 ../outputs/，这是正确的相对路径
    generator = FullStackGenerator()

    # 3. 为单个项目运行批量生成函数
    # 该函数需要一个指令列表
    print("\n🚀 开始单个项目生成测试（将使用API文档）...")
    generator.generate_batch_simple_projects(
        instructions=[instruction],
        base_name="test_run_with_api_doc"  # 使用一个特定的基础名称以避免覆盖
    )
    print("\n✅ 单个项目生成测试完成。")

if __name__ == "__main__":
    main()
