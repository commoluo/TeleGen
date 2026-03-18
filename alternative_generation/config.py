"""
Configuration for alternative website generation (DashScope official API)
"""
import os
from pathlib import Path
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# 优先加载项目根目录 .env（用户当前更新密钥的位置），再加载本目录 .env
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(SCRIPT_DIR / ".env")

# OpenAI-compatible API Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


def _infer_provider_from_model(model: str = "") -> str:
    model_lower = (model or "").strip().lower()
    if "qwen" in model_lower:
        return "qwen"
    if "deepseek" in model_lower:
        return "deepseek"
    return "generic"


def resolve_api_base_url(model: str = "") -> str:
    provider = _infer_provider_from_model(model)

    if provider == "qwen":
        return os.getenv("QWEN_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    if provider == "deepseek":
        return os.getenv("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com")

    return os.getenv("API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


def _resolve_api_key() -> str:
    explicit_api_key = os.getenv("API_KEY")
    if explicit_api_key:
        return explicit_api_key

    base_url_lower = API_BASE_URL.lower()
    if "deepseek.com" in base_url_lower:
        return os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or ""

    return (
        os.getenv("QWEN_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


def resolve_api_key(model: str = "", base_url: str = "") -> str:
    explicit_api_key = os.getenv("API_KEY")
    if explicit_api_key:
        return explicit_api_key

    provider = _infer_provider_from_model(model)
    base_url_lower = (base_url or "").lower()
    if provider == "generic":
        if "deepseek.com" in base_url_lower:
            provider = "deepseek"
        elif "dashscope.aliyuncs.com" in base_url_lower:
            provider = "qwen"

    if provider == "deepseek":
        return (
            os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )

    if provider == "qwen":
        return (
            os.getenv("QWEN_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )

    return (
        os.getenv("QWEN_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


API_KEY = _resolve_api_key()

# Model Configuration
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3.5-flash")
ALTERNATIVE_MODEL = os.getenv("ALTERNATIVE_MODEL", "qwen3.5-flash")

# Generation Settings
# MAX_TOKENS: Qwen3.5-flash 最大上下文 32k，但考虑：
# 1) 多轮续接时会累积 prompt - 保留余量避免超限
# 2) 单个组件代码通常 3-6k token - 8k 是保守估计
# 3) 可通过 MAX_TOKENS 环境变量覆盖（范围 4000-16000）
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8000"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
TOP_P = float(os.getenv("TOP_P", "0.9"))
MAX_CONTINUATION_ROUNDS = int(os.getenv("MAX_CONTINUATION_ROUNDS", "6"))
OUTPUT_END_MARKER = os.getenv("OUTPUT_END_MARKER", "__FULLSTACK_WEBGEN_END_OF_OUTPUT__")

# Qwen-specific settings (部分兼容接口可忽略该参数)
ENABLE_THINKING = os.getenv("ENABLE_THINKING", "false").lower() == "true"

# Output Configuration
OUTPUT_DIR = "generated_websites"
DOWNLOAD_DIR = "downloads"

# Test Configuration
TEST_JSONL_PATH = "../data/test.jsonl"
SINGLE_TEST_PATH = "../test_single.jsonl"


def get_api_headers(model: str = "", base_url: str = ""):
    """Get API headers for requests"""
    api_key = resolve_api_key(model=model, base_url=base_url)
    if not api_key:
        raise ValueError(
            "API key is empty. Please set API_KEY or provider-specific key in .env "
            "(DEEPSEEK_API_KEY / QWEN_API_KEY / DASHSCOPE_API_KEY / OPENAI_API_KEY)."
        )

    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Python-requests/2.32.4",
        "Accept": "application/json",
        "Connection": "keep-alive"
    }


def get_chat_completion_url(model: str = "", base_url: str = ""):
    """Get the chat completion endpoint URL"""
    chosen_base_url = base_url or resolve_api_base_url(model)
    return f"{chosen_base_url.rstrip('/')}/chat/completions"
