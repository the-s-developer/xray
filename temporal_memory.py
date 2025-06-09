import json
from typing import List, Dict, Any
from tool_local_client import ToolLocalClient
from context_processor import ContextProcessor
import copy

class TemporalMemory(ContextProcessor):
    SUMMARY_LENGTH = 120

    def __init__(self):
        self.data = {}

    def memorize(self, key: str, value):
        if value is None:
            print(f"[TM] Warning: memorize called with None for key={key}")
            raise ValueError("Value is None")
        print(f"[TM] memorize: key={key}, type={type(value)}, keys={list(value.keys()) if isinstance(value, dict) else '?'}")
        self.data[key] = value

    async def recall(self, keys: List[str]) -> Dict[str, Any]:
        return {key: self.data.get(key, "Not found") for key in keys}

    def forget(self):
        print("[TM] forget called. All memory wiped.")
        self.data = {}

    def status(self):
        summary_dict = {}
        for key, msg in self.data.items():
            print(f"[TM STATUS] Processing key={key} (role={msg.get('role')})")
            role = msg.get("role", "")
            content = msg.get("content", "")
            preview = content[:self.SUMMARY_LENGTH] + ("..." if len(content) > self.SUMMARY_LENGTH else "")
            item = {
                "role": role,
                "summary": preview
            }
            tool_calls = msg.get("tool_calls")
            if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
                try:
                    tool_calls_summary = json.dumps(tool_calls, ensure_ascii=False)
                except Exception as e:
                    print(f"[TM STATUS]    Failed to json-dump tool_calls: {e}")
                    tool_calls_summary = str(tool_calls)
                tool_calls_summary = tool_calls_summary[:self.SUMMARY_LENGTH]
                item["tool_calls_summary"] = tool_calls_summary + ("..." if len(tool_calls_summary) == self.SUMMARY_LENGTH else "")
            summary_dict[key] = item
        print(f"[TM STATUS] Done. {len(summary_dict)} summaries ready.")
        return summary_dict

    def create_tool_client(self):
        client = ToolLocalClient(server_id="temporal-memory")
        # Class'ın recall fonksiyonunu kaydet!
        client.register_tool_auto(
            self.recall,
            name="recall",
            description="Returns the contents for multiple message ids (array/list) from temporal memory as a dict mapping key to value."
        )

        client.register_tool_auto(
            self.status,
            name="status",
            description="Lists all keys and short summaries from temporal memory."
        )
        return client

    def refine(
        self,
        messages: List[Dict[str, Any]],
        preserve_last_n_massive_tool_pairs: int = 1,
        trim_char_limit: int = 200,
        tool_arg_trim_limit: int = 100,
        preserve_last_n_recall_calls: int = 1
    ) -> List[Dict[str, Any]]:
        print(f"[TM REFINE] Start refine: messages={len(messages)}")
        recall_pairs = []
        recall_tool_call_ids = set()
        idx = 0
        while idx < len(messages):
            msg = messages[idx]
            if (
                msg["role"] == "assistant"
                and msg.get("tool_calls")
                and isinstance(msg["tool_calls"], list)
            ):
                for call in msg["tool_calls"]:
                    if isinstance(call, str):
                        try:
                            call = json.loads(call)
                        except Exception as e:
                            print(f"[TM REFINE]   tool_calls parse error: {call} -> {e}")
                            continue
                    if isinstance(call, dict) and call.get("name") == "recall":
                        tool_call_id = call.get("id")
                        recall_tool_call_ids.add(tool_call_id)
                        next_idx = idx + 1
                        if (
                            next_idx < len(messages)
                            and messages[next_idx]["role"] == "tool"
                            and messages[next_idx].get("tool_call_id") == tool_call_id
                        ):
                            recall_pairs.append((idx, next_idx, tool_call_id))
                        else:
                            recall_pairs.append((idx, None, tool_call_id))
                        break
            idx += 1

        print(f"[TM REFINE] Recall pairs found: {len(recall_pairs)}")
        remove_recall_idxs = set()
        if preserve_last_n_recall_calls > 0 and len(recall_pairs) > preserve_last_n_recall_calls:
            for pair in recall_pairs[:-preserve_last_n_recall_calls]:
                remove_recall_idxs.add(pair[0])
                if pair[1] is not None:
                    remove_recall_idxs.add(pair[1])
            print(f"[TM REFINE] Removing old recall idxs: {remove_recall_idxs}")

        big_tool_idxs = []
        for idx, msg in enumerate(messages):
            if msg["role"] == "tool":
                if msg.get("tool_call_id") in recall_tool_call_ids:
                    continue
                tool_content = msg.get("content", "")
                if len(tool_content) > trim_char_limit:
                    big_tool_idxs.append(idx)
        print(f"[TM REFINE] big_tool_idxs: {big_tool_idxs}")

        preserve_tool_idxs = set(big_tool_idxs[-preserve_last_n_massive_tool_pairs:])
        preserve_idxs = set(preserve_tool_idxs)
        for idx in list(preserve_tool_idxs):
            if idx - 1 >= 0 and messages[idx - 1]["role"] == "assistant":
                preserve_idxs.add(idx - 1)
        print(f"[TM REFINE] preserve_idxs: {preserve_idxs}")

        for idx, msg in enumerate(messages):
            if idx in remove_recall_idxs or idx in preserve_idxs:
                print(f"[TM REFINE] Skipping idx={idx} (remove_recall or preserve)")
                continue

            key = msg["meta"]["id"]

            if msg["role"] == "assistant" and msg.get("tool_calls"):
                tool_calls = msg["tool_calls"]
                tool_calls_trimmed = False
                if isinstance(tool_calls, list):
                    for i, call in enumerate(tool_calls):
                        if isinstance(call, str):
                            try:
                                call = json.loads(call)
                                tool_calls[i] = call
                            except Exception as e:
                                print(f"[TM REFINE] tool_calls[{i}] parse error: {call} -> {e}")
                                continue
                        if isinstance(call, dict):
                            arguments = call.get("arguments")
                            if arguments and isinstance(arguments, dict):
                                for arg_k, arg_v in arguments.items():
                                    if isinstance(arg_v, str) and len(arg_v) > tool_arg_trim_limit:
                                        print(f"[TM REFINE] Trimming arg {arg_k} in tool_call {call.get('name','?')}")
                                        call["arguments"][arg_k] = arg_v[:tool_arg_trim_limit] + "...(trimmed)"
                                        tool_calls_trimmed = True

                tool_calls_str = json.dumps(tool_calls, ensure_ascii=False)
                assist_content = (msg.get("content") or "")
                if len(assist_content) + len(tool_calls_str) > trim_char_limit or tool_calls_trimmed:
                    print(f"[TM REFINE] Memorizing and summarizing assistant msg id={key}")
                    self.memorize(key, copy.deepcopy(msg))
                    summary_length = self.SUMMARY_LENGTH
                    content_preview = assist_content[:summary_length]
                    if tool_calls:
                        tool_calls_preview = json.dumps(tool_calls, ensure_ascii=False)[:summary_length]
                        tool_calls_preview_str = f"\n(TOOL_CALLS PREVIEW): {tool_calls_preview}..."
                    else:
                        tool_calls_preview_str = ""
                    msg["content"] = (
                        f"(SUMMARY) Assistant tool-call summarized. To see the full data, call tool -> temporal-memory__recall([\"{key}\"]): "
                        + content_preview
                        + ("..." if content_preview else "")
                        + tool_calls_preview_str
                    )
                    msg.pop("tool_calls", None)
            elif msg["role"] == "tool":
                if msg.get("tool_call_id") in recall_tool_call_ids:
                    continue
                tool_content = msg.get("content", "")
                if len(tool_content) > trim_char_limit:
                    print(f"[TM REFINE] Memorizing and summarizing tool msg id={key}")
                    self.memorize(key, copy.deepcopy(msg))
                    summary_length = self.SUMMARY_LENGTH
                    tool_content_preview = tool_content[:summary_length]
                    msg["content"] = (
                        f"(SUMMARY) Tool response trimmed. Full: call tool -> temporal-memory__recall([\"{key}\"]). Preview: {tool_content_preview}..."
                    )

        filtered_messages = [
            msg for idx, msg in enumerate(messages) if idx not in remove_recall_idxs
        ]

        print(f"[TM REFINE] End refine: returning {len(filtered_messages)} messages")
        with open("temporal.json", "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

        return filtered_messages
