
import requests
import json

url = "http://127.0.0.1:8002/api/critique_chapter"
payload = {
    "chapter_content": "这是一个测试章节内容，长度必须超过十个字才能通过验证。",
    "chapter_title": "测试章节",
    "api_key": "test_key",
    "base_url": "https://api.example.com",
    "model": "gpt-4o-mini"
}

try:
    # 模拟前端发送的请求结构
    response = requests.post(url, json=payload)
    print(f"Status Code: {response.status_code}")
    if response.status_code != 200:
        print(f"Error: {response.text}")
    else:
        # 因为 api_key 是假的，后端可能会报错连不上 LLM，但只要不是 422 就说明参数校验通过了
        print("Success (Validation passed)")
except Exception as e:
    print(f"Exception: {e}")
