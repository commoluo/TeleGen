"""
Direct API client for OpenAI-compatible endpoints (DashScope by default)
"""
import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from config import (
    get_api_headers,
    get_chat_completion_url,
    resolve_api_base_url,
    DEFAULT_MODEL,
    MAX_TOKENS,
    MAX_CONTINUATION_ROUNDS,
    OUTPUT_END_MARKER,
)

class UniversityAPIClient:
    """Client for direct communication with OpenAI-compatible chat completion API"""
    
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.base_url = resolve_api_base_url(model)
        self.headers = get_api_headers(model=model, base_url=self.base_url)
        self.url = get_chat_completion_url(model=model, base_url=self.base_url)
    
    def _transform_response(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform university API response to standard OpenAI format
        Handles the string 'created' field issue
        """
        if not isinstance(response_data, dict):
            return response_data
        
        # Convert created field from string to Unix timestamp
        if 'created' in response_data and isinstance(response_data['created'], str):
            try:
                # Try to parse the date string and convert to Unix timestamp
                date_obj = datetime.strptime(response_data['created'], "%Y-%m-%d %H:%M:%S")
                response_data['created'] = int(date_obj.timestamp())
            except (ValueError, TypeError):
                # If parsing fails, use current timestamp
                response_data['created'] = int(time.time())
        
        # Ensure required fields are present
        if 'id' not in response_data or not response_data['id']:
            response_data['id'] = f"chatcmpl-{int(time.time())}"
        
        if 'object' not in response_data:
            response_data['object'] = 'chat.completion'
        
        if 'model' not in response_data or not response_data['model']:
            response_data['model'] = self.model
        
        # Ensure choices array has proper format
        if 'choices' in response_data and isinstance(response_data['choices'], list):
            for i, choice in enumerate(response_data['choices']):
                if 'index' not in choice:
                    choice['index'] = i
                if 'finish_reason' not in choice:
                    choice['finish_reason'] = 'stop'
        
        # Ensure usage object exists
        if 'usage' not in response_data:
            response_data['usage'] = {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0
            }
        
        return response_data
    
    def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        top_p: float = 0.9,
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        Send a chat completion request to OpenAI-compatible API
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            top_p: Top-p sampling parameter
            stream: Whether to stream the response
        
        Returns:
            Transformed API response in standard OpenAI format
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "stream": stream
        }

        if max_tokens is None:
            max_tokens = MAX_TOKENS
        payload["max_tokens"] = max_tokens
        
        
        try:
            print(f"Sending request to {self.url}")
            print(f"Model: {self.model}")
            print(f"Messages: {len(messages)} message(s)")
            
            # Retry logic for connection issues
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = requests.post(
                        self.url,
                        headers=self.headers,
                        json=payload,
                        timeout=600
                    )
                    break  # If successful, break out of retry loop
                except (requests.exceptions.ConnectionError, ConnectionResetError) as e:
                    if attempt < max_retries - 1:
                        print(f"⚠️  Connection attempt {attempt + 1} failed, retrying...")
                        time.sleep(2)  # Wait before retry
                        continue
                    else:
                        raise e  # Re-raise if all attempts failed
            
            print(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                print(response)
                transformed_data = self._transform_response(response_data)
                print("✅ Request successful")
                return transformed_data
            else:
                error_msg = f"API request failed with status {response.status_code}: {response.text}"
                print(f"❌ {error_msg}")
                return {
                    "error": {
                        "message": error_msg,
                        "type": "api_error",
                        "code": response.status_code
                    }
                }
        
        except requests.exceptions.Timeout:
            error_msg = "Request timed out"
            print(f"❌ {error_msg}")
            return {
                "error": {
                    "message": error_msg,
                    "type": "timeout_error",
                    "code": "timeout"
                }
            }
        
        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                "error": {
                    "message": error_msg,
                    "type": "request_error",
                    "code": "request_failed"
                }
            }
        
        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse JSON response: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                "error": {
                    "message": error_msg,
                    "type": "json_error",
                    "code": "json_parse_failed"
                }
            }

    def _extract_message_content(self, response: Dict[str, Any]) -> str:
        choices = response.get("choices", []) if isinstance(response, dict) else []
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "") or ""

    def _extract_finish_reason(self, response: Dict[str, Any]) -> Optional[str]:
        choices = response.get("choices", []) if isinstance(response, dict) else []
        if not choices:
            return None
        return choices[0].get("finish_reason")

    def _merge_usage(self, responses: List[Dict[str, Any]]) -> Dict[str, int]:
        merged = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        for response in responses:
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            for key in merged:
                value = usage.get(key, 0)
                if isinstance(value, int):
                    merged[key] += value
        return merged

    def _find_overlap_size(self, previous: str, current: str, max_window: int = 4000) -> int:
        if not previous or not current:
            return 0

        window = min(len(previous), len(current), max_window)
        for size in range(window, 0, -1):
            if previous[-size:] == current[:size]:
                return size
        return 0

    def _merge_continuation_text(self, accumulated: str, chunk: str) -> str:
        if not accumulated:
            return chunk
        overlap = self._find_overlap_size(accumulated, chunk)
        return accumulated + chunk[overlap:]

    def _strip_end_marker(self, content: str, end_marker: str) -> str:
        if end_marker not in content:
            return content.strip()
        return content.split(end_marker, 1)[0].rstrip()

    def chat_completion_with_continuation(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        top_p: float = 0.9,
        stream: bool = False,
        end_marker: str = OUTPUT_END_MARKER,
        max_rounds: int = MAX_CONTINUATION_ROUNDS,
    ) -> Dict[str, Any]:
        """Request a long completion, auto-continue on truncation, and stitch all chunks."""
        if max_rounds < 1:
            max_rounds = 1

        base_messages = list(messages)
        accumulated_content = ""
        round_responses: List[Dict[str, Any]] = []

        for round_index in range(max_rounds):
            if round_index == 0:
                request_messages = base_messages
            else:
                tail = accumulated_content[-1200:]
                request_messages = base_messages + [
                    {
                        "role": "assistant",
                        "content": accumulated_content,
                    },
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was incomplete or missing the required end marker. "
                            "Continue from exactly after the last emitted character. "
                            "Do not restart. Do not repeat earlier content unless a tiny overlap is necessary. "
                            f"When the full file is complete, append this exact marker on its own line: {end_marker}\n\n"
                            f"Last emitted tail for reference:\n{tail}"
                        ),
                    },
                ]

            response = self.chat_completion(
                messages=request_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stream=stream,
            )

            if not response or "error" in response:
                return response if isinstance(response, dict) else {
                    "error": {
                        "message": "Unknown API error during continuation",
                        "type": "api_error",
                        "code": "unknown_error",
                    }
                }

            round_responses.append(response)
            chunk = self._extract_message_content(response)
            if not chunk.strip():
                return {
                    "error": {
                        "message": f"Empty content returned during continuation round {round_index + 1}",
                        "type": "empty_response",
                        "code": "empty_response",
                    }
                }

            accumulated_content = self._merge_continuation_text(accumulated_content, chunk)
            finish_reason = self._extract_finish_reason(response)

            if end_marker in accumulated_content:
                final_content = self._strip_end_marker(accumulated_content, end_marker)
                return {
                    "id": response.get("id", f"chatcmpl-{int(time.time())}"),
                    "object": "chat.completion",
                    "created": response.get("created", int(time.time())),
                    "model": response.get("model", self.model),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": final_content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": self._merge_usage(round_responses),
                    "continuation_rounds": round_index + 1,
                    "raw_finish_reason": finish_reason,
                }

            if finish_reason not in {"length", None}:
                # One more round may still be needed if the model forgot the marker.
                continue

        return {
            "error": {
                "message": (
                    f"Response remained incomplete after {max_rounds} rounds. "
                    f"Required end marker not found: {end_marker}"
                ),
                "type": "truncation_error",
                "code": "continuation_exhausted",
            }
        }
    
    def test_connection(self) -> bool:
        """Test the API connection with a simple request"""
        test_messages = [
            {"role": "user", "content": "Hello, please respond with just 'Hello back!'"}
        ]
        
        print("🔧 Testing API connection...")
        response = self.chat_completion(
            messages=test_messages,
            max_tokens=10,
            temperature=0.1
        )
        
        if "error" in response:
            print(f"❌ Connection test failed: {response['error']['message']}")
            return False
        
        if "choices" in response and len(response["choices"]) > 0:
            content = response["choices"][0].get("message", {}).get("content", "")
            print(f"✅ Connection test successful. Response: {content}")
            return True
        
        print("❌ Connection test failed: No valid response received")
        return False
