"""
Direct API client for university's GPT-4 API
Handles the API format compatibility issues directly
"""
import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from config import get_api_headers, get_chat_completion_url, DEFAULT_MODEL, MAX_TOKENS

class UniversityAPIClient:
    """Client for direct communication with university's GPT-4 API"""
    
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.headers = get_api_headers()
        self.url = get_chat_completion_url()
    
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
        Send a chat completion request to the university API
        
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
        
        if max_tokens:
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
                        timeout=60,
                        verify=False  # Disable SSL verification if there are certificate issues
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
