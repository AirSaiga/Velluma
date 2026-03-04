"""
阿里云 DashScope API Key 测试脚本
用法: python test_api_key.py <你的API_KEY>
"""
import sys
import dashscope
from dashscope import TextEmbedding

def test_embedding_api(api_key: str):
    """测试 Embedding API 是否可用"""
    dashscope.api_key = api_key

    test_text = "这是一个测试文本，用于验证 API Key 是否有效。"

    print(f"正在测试 API Key: {api_key[:10]}...")
    print(f"测试文本: {test_text}")

    try:
        response = TextEmbedding.call(
            model=TextEmbedding.Models.text_embedding_v2,
            input=test_text
        )

        if response.status_code == 200:
            embedding = response.output['embeddings'][0]['embedding']
            print(f"\n✅ API Key 有效!")
            print(f"返回向量维度: {len(embedding)}")
            print(f"向量前5个值: {embedding[:5]}")
            return True
        else:
            print(f"\n❌ API 调用失败")
            print(f"状态码: {response.status_code}")
            print(f"错误信息: {response.message}")
            return False

    except Exception as e:
        print(f"\n❌ 异常错误: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python test_api_key.py <你的API_KEY>")
        print("\n请先从 https://dashscope.console.aliyun.com/ 获取 API Key")
        sys.exit(1)

    api_key = sys.argv[1]
    success = test_embedding_api(api_key)
    sys.exit(0 if success else 1)
