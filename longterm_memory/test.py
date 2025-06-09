import time
from semantic_memory import SemanticMemory

def simple_test():
    mem = SemanticMemory()  # Uses default env/config

    # 1. Memorize some sentences
    key1 = mem.memorize("The quick brown fox jumps over the lazy dog.")
    key2 = mem.memorize("ChatGPT is a large language model developed by OpenAI.")
    key3 = mem.memorize("Milvus is a vector database for AI applications.")

    print(f"Inserted keys: {key1}, {key2}, {key3}")

    # 2. Recall by key
    recalled = mem.recall(key1)
    print("Recalled by key:", recalled)

    # 3. Semantic search
    results = mem.semantic_search("What is ChatGPT?", top_k=2)
    print("Semantic search results:")
    for res in results:
        print(res)

    # 4. Count
    print("Memory count:", mem.count())

    # 5. Forget one
    deleted = mem.forget(key2)
    print(f"Deleted {key2}: {deleted}")
    print("Memory count after delete:", mem.count())

    # 6. Status
    print("Collection status:", mem.status())

if __name__ == "__main__":
    simple_test()
