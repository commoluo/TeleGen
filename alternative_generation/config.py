"""
Configuration for alternative website generation using university API
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# University API Configuration
API_BASE_URL = "https://aigc-api.hkust-gz.edu.cn/v1"
API_KEY = "8ef4c3ccf5f14ee6ad39dccaf1daef545aa3af0833ce4301a561ace8331947b2"


API_KEY_4_DEEPSEEK = "sk-e1844037a3514fc5ac6292e4c394eb30"
# Model Configuration
DEFAULT_MODEL = "Qwen"
# DEFAULT_MODEL = "DeepSeek-R1-671B"
# DEFAULT_MODEL = "gpt-4"
ALTERNATIVE_MODEL = "gpt-4"

# Generation Settings
MAX_TOKENS = 8000
TEMPERATURE = 0.7
TOP_P = 0.9

# Qwen-specific settings
ENABLE_THINKING = False # True for enable_thinking positive, False for enable_thinking negative.

# Output Configuration
OUTPUT_DIR = "generated_websites"
DOWNLOAD_DIR = "downloads"

# Test Configuration
TEST_JSONL_PATH = "../data/test.jsonl"
SINGLE_TEST_PATH = "../test_single.jsonl"

def get_api_headers():
    """Get API headers for requests"""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Python-requests/2.32.4",
        "Accept": "application/json",
        "Connection": "keep-alive"
    }

def get_chat_completion_url():
    """Get the chat completion endpoint URL"""
    return f"{API_BASE_URL}/chat/completions"
