import os
from openai import OpenAI

# 初始化 DeepSeek 客户端（兼容 OpenAI SDK）
client = OpenAI(
    api_key='sk-695c208e22e449bea9c4d7cdcaddab7e',  # 从环境变量读取 API Key
    base_url="https://api.deepseek.com"           # DeepSeek API 端点
)

# 统一的用户问题（仅作展示，实际提示词用各语言翻译）
USER_QUESTION = "请解释什么是递归函数，并给出计算斐波那契数列的示例。"

# 五种语言的提示词（内容完全相同，仅语言不同）
PROMPTS = {
    "中文": "请解释什么是递归函数，并给出计算斐波那契数列的示例。",
    "英文": "Please explain what a recursive function is and give an example of calculating the Fibonacci sequence.",
    "日文": "再帰関数とは何かを説明し、フィボナッチ数列を計算する例を示してください。",
    "梵语（罗马化）": "Recursive function kim? Fibonaccisankhya ganana udaharanam dehi.",
    "文言文": "递归函数者何？试述其义，并以斐波那契数列为例演算之。",
}

def call_api(prompt: str, language: str) -> dict:
    """调用 DeepSeek API 并返回响应及 usage 信息"""
    response = client.chat.completions.create(
        model="deepseek-v4-flash",  # 使用 flash 模型，性价比高
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        stream=False,  # 非流式输出，便于一次性获取完整 usage
    )
    
    # 从响应中提取 usage 信息
    usage = response.usage
    return {
        "language": language,
        "prompt": prompt,
        "prompt_tokens": usage.prompt_tokens,        # 输入 Token 数
        "completion_tokens": usage.completion_tokens, # 输出 Token 数
        "total_tokens": usage.total_tokens,          # 总 Token 数
        "response_text": response.choices[0].message.content,
    }

def main():
    print("=" * 60)
    print("DeepSeek API 多语言 Token 消耗对比测试（含文言文）")
    print("=" * 60)
    print(f"统一问题：{USER_QUESTION}\n")
    
    results = []
    for lang, prompt in PROMPTS.items():
        print(f"正在测试 {lang}...")
        try:
            result = call_api(prompt, lang)
            results.append(result)
            print(f"  ✅ {lang} 完成 | 输入: {result['prompt_tokens']} tokens | "
                  f"输出: {result['completion_tokens']} tokens | "
                  f"总计: {result['total_tokens']} tokens")
        except Exception as e:
            print(f"  ❌ {lang} 失败: {e}")
    
    # 打印汇总对比表
    print("\n" + "=" * 60)
    print("汇总对比（以英文为基准）")
    print("=" * 60)
    print(f"{'语言':<14} {'输入Token':<12} {'输出Token':<12} {'总计Token':<12} {'相对英文':<10}")
    print("-" * 60)
    
    # 以英文为基准
    english_total = next(r["total_tokens"] for r in results if r["language"] == "英文")
    
    for r in results:
        ratio = r["total_tokens"] / english_total
        print(f"{r['language']:<14} {r['prompt_tokens']:<12} {r['completion_tokens']:<12} "
              f"{r['total_tokens']:<12} {ratio:.2f}x")
    
    print("\n" + "=" * 60)
    print("各语言模型回答（截取前200字符）")
    print("=" * 60)
    for r in results:
        text = r["response_text"]
        display = text[:200] + "..." if len(text) > 200 else text
        print(f"\n【{r['language']}】")
        print(display)

if __name__ == "__main__":
    main()