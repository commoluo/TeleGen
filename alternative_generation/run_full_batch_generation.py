import json
from fullstack_generator import FullStackGenerator

def main():
    """
    运行完整的批量生成流程，为 test.jsonl 中的每个指令生成一个项目。
    在生成过程中，它会自动查找并使用对应的API文档。
    """
    # 1. 从 ../data/test.jsonl 加载所有指令
    instructions = []
    try:
        # 假设此脚本在 alternative_generation 目录下运行
        with open('../data/test.jsonl', 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    instructions.append(data.get("instruction", ""))
    except FileNotFoundError:
        print("❌ 错误: 'data/test.jsonl' 文件未找到。请确保你在 WebGen-Bench-main 根目录下运行此脚本。")
        return
    except Exception as e:
        print(f"❌ 读取测试数据失败: {e}")
        return

    if not instructions:
        print("❌ 未找到可用于测试的指令。")
        return

    print(f"✅ 成功加载 {len(instructions)} 条测试指令。")

    # 2. 初始化生成器
    generator = FullStackGenerator()

    # 3. 运行完整的批量生成
    print("\n🚀 开始完整批量生成（将使用API文档）...")
    generator.generate_batch_simple_projects(
        instructions=instructions,
        base_name="full_run_with_api_doc"
    )
    print("\n✅ 完整批量生成完成。")

if __name__ == "__main__":
    main()
