import json
from typing import List, Dict, Any
from tool_local_client import ToolLocalClient
from context_processor import ContextProcessor
import copy

class TemporalMemory(ContextProcessor):
    SUMMARY_LENGTH = 120  # Preview length for summary

    def __init__(self):
        self.data = {}

    def memorize(self, key: str, value):
        self.data[key] = value

    def recall(self, key: str):
        return self.data.get(key, "Not found")

    def forget(self):
        self.data = {}

    def status(self):
        summary_dict = {}
        for key, msg in self.data.items():
            role = msg.get("role", "")
            content = msg.get("content", "")
            preview = content[:self.SUMMARY_LENGTH] + ("..." if len(content) > self.SUMMARY_LENGTH else "")
            item = {
                "role": role,
                "summary": preview
            }
            # Sadece assistant ve tool_calls list ise
            tool_calls = msg.get("tool_calls")
            if role == "assistant" and isinstance(tool_calls, list):
                arguments_list = []
                for call in tool_calls:
                    # call dict değilse, json olarak parse etmeyi dene
                    if isinstance(call, str):
                        try:
                            call = json.loads(call)
                        except Exception:
                            continue
                    if isinstance(call, dict):
                        args = call.get("arguments")
                        if isinstance(args, dict):
                            arguments_list.append(args)
                        elif isinstance(args, str):
                            try:
                                arguments_list.append(json.loads(args))
                            except Exception:
                                arguments_list.append(args)
                if arguments_list:
                    item["tool_call_arguments"] = arguments_list
            summary_dict[key] = item
        return summary_dict




    def create_tool_client(self):
        client = ToolLocalClient(server_id="temporal-memory")

        async def recall(keys: List[str]) -> List[str]:
            results = []
            for key in keys:
                result = self.recall(key)
                if isinstance(result, (dict, list)):
                    results.append(json.dumps(result, ensure_ascii=False, indent=2))
                else:
                    results.append(str(result))
            return results

        async def status() -> str:
            summaries = self.status()
            return json.dumps(summaries, ensure_ascii=False)

        client.register_tool_auto(
            recall,
            name="recall",
            description="Returns the contents for multiple message ids (array/list) from temporal memory as an array."
        )
        client.register_tool_auto(
            status,
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
        """
        - Tüm büyük tool mesajlarından (recall response hariç) sondan n tanesi ve paired assistant'ları korunur.
        - Recall için de son n recall & paired tool response korunur, diğerleri kaldırılır.
        - Diğer mesajlarda trim/memorize işlemleri devam eder.
        - Recall response tool mesajları asla memorize/summarize edilmez!
        """
        # 1. Recall çağrısı yapan asistan mesajları ve paired tool response'larını topla
        recall_pairs = []  # [(assistant_idx, tool_idx, tool_call_id)]
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
                    if call.get("name") == "recall":
                        tool_call_id = call.get("id")
                        recall_tool_call_ids.add(tool_call_id)
                        # Paired tool cevabı hemen ardından gelmeli (tipik durum)
                        next_idx = idx + 1
                        if (next_idx < len(messages)
                            and messages[next_idx]["role"] == "tool"
                            and messages[next_idx].get("tool_call_id") == tool_call_id):
                            recall_pairs.append((idx, next_idx, tool_call_id))
                        else:
                            recall_pairs.append((idx, None, tool_call_id))
                        break
            idx += 1

        # 2. Recall'lar için koruma ve kaldırma işlemi
        remove_recall_idxs = set()
        if preserve_last_n_recall_calls > 0 and len(recall_pairs) > preserve_last_n_recall_calls:
            for pair in recall_pairs[:-preserve_last_n_recall_calls]:
                remove_recall_idxs.add(pair[0])  # assistant
                if pair[1] is not None:
                    remove_recall_idxs.add(pair[1])  # paired tool

        # 3. Büyük tool mesajlarını tespit et (recall response olanlar hariç)
        big_tool_idxs = []
        for idx, msg in enumerate(messages):
            if msg["role"] == "tool":
                # Recall response mu? call_id eşleşiyorsa SKIP!
                if msg.get("tool_call_id") in recall_tool_call_ids:
                    continue
                tool_content = msg.get("content", "")
                if len(tool_content) > trim_char_limit:
                    big_tool_idxs.append(idx)

        # 4. Sondan itibaren kaç tane korunacak
        preserve_tool_idxs = set(big_tool_idxs[-preserve_last_n_massive_tool_pairs:])

        # 5. Bunların paired assistant'larını da koru
        preserve_idxs = set(preserve_tool_idxs)
        for idx in list(preserve_tool_idxs):
            if idx - 1 >= 0 and messages[idx - 1]["role"] == "assistant":
                preserve_idxs.add(idx - 1)

        # 6. Eski mantık: kalan mesajlarda trim işlemleri
        for idx, msg in enumerate(messages):
            if idx in remove_recall_idxs or idx in preserve_idxs:
                continue  # Ya tamamen kaldırılacak ya da kesin korunacak

            key = msg["meta"]["id"]

            # Only trim arguments in assistant messages containing tool_calls
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                tool_calls = msg["tool_calls"]
                tool_calls_trimmed = False
                if isinstance(tool_calls, list):
                    for call in tool_calls:
                        arguments = call.get("arguments")
                        if arguments and isinstance(arguments, dict):
                            for arg_k, arg_v in arguments.items():
                                if isinstance(arg_v, str) and len(arg_v) > tool_arg_trim_limit:
                                    call["arguments"][arg_k] = arg_v[:tool_arg_trim_limit] + "...(trimmed)"
                                    tool_calls_trimmed = True
                tool_calls_str = json.dumps(tool_calls, ensure_ascii=False)
                assist_content = (msg.get("content") or "")
                if len(assist_content) + len(tool_calls_str) > trim_char_limit or tool_calls_trimmed:
                    self.memorize(key, copy.deepcopy(msg))   # Store the message as is
                    summary_length = self.SUMMARY_LENGTH
                    tool_calls_preview = json.dumps(tool_calls, ensure_ascii=False)[:summary_length]
                    content_preview = assist_content[:summary_length]
                    msg["content"] = (
                        f"(SUMMARY) Assistant tool-call summarized. To see the full data, call tool -> temporal-memory__recall([\"{key}\"]): "
                        + content_preview + ("..." if content_preview else "")
                    )
                    msg["tool_calls"] = f"(TRIMMED preview) {tool_calls_preview}..."
            # For tool responses (küçük tool mesajları)
            elif msg["role"] == "tool":
                # YENİ: Recall response tool mesajlarını atla, asla memorize/summarize etme!
                if msg.get("tool_call_id") in recall_tool_call_ids:
                    continue
                tool_content = msg.get("content", "")
                if len(tool_content) > trim_char_limit:
                    self.memorize(key, copy.deepcopy(msg))
                    summary_length = self.SUMMARY_LENGTH
                    tool_content_preview = tool_content[:summary_length]
                    msg["content"] = (
                        f"(SUMMARY) Tool response trimmed. Full: call tool -> temporal-memory__recall([\"{key}\"]). Preview: {tool_content_preview}..."
                    )

        # 7. Sadece silinmeyen (veya özetlenen) mesajları döndür
        filtered_messages = [
            msg for idx, msg in enumerate(messages) if idx not in remove_recall_idxs
        ]

        with open("temporal.json", "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

        return filtered_messages
