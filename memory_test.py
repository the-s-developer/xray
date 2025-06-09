# memory_test.py

import os
import json
from temporal_memory import TemporalMemory

def read_messages_from_json(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        messages = json.load(f)
        if isinstance(messages, dict) and "messages" in messages:
            messages = messages["messages"]
        return messages

def test_temporal_memory():
    msgs = read_messages_from_json("test/sample.json")
    tm = TemporalMemory()
    # Burada path'i parametre ile geçiriyoruz:
    refined = tm.refine(msgs,preserve_last_n_massive_tool_pairs=1,trim_char_limit=200,tool_arg_trim_limit=100,preserve_last_n_recall_calls=1)
    with open("test/temporal.json", "w", encoding="utf-8") as f:
        json.dump(tm.data, f, ensure_ascii=False, indent=2)
    
    with open("test/refined.json", "w", encoding="utf-8") as f:
        json.dump(refined, f, ensure_ascii=False, indent=2)
            
if __name__ == "__main__":
    test_temporal_memory()
