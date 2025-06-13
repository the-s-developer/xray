from context_memory import ContextMemory
from typing import List, Dict, Any, Optional, Set
from tool_local_client import ToolLocalClient
import fnmatch
import re

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

MAX_TOOL_CONTENT_CHARS: int = 256  # Trim threshold for tool responses
_TRIM_NOTICE: str = "\n[response trimmed because it exceeded the context limit]"

# ``#`` followed by *word*, ``:``, ``*`` or ``?``  → captures hierarchical or
# wildcard token names.
_MEMORY_TOKEN_RE: re.Pattern[str] = re.compile(r"#([\w:*?]+)")


class TemporalMemory(ContextMemory):
    """A context-aware memory helper that lets the LLM *persist*, *recall* and
    *inspect* small snippets of conversation using simple #tokens.

    The three public *tool* methods – :py:meth:`memorize`, :py:meth:`recall` and
    :py:meth:`status` – are automatically exposed to the LLM so that it can call
    them just like any other function-tool.  Each carries a docstring written
    for the language-model so that it knows **what the function does, which
    arguments it expects and what it returns**.
    """

    def __init__(
        self,
        system: str,
        *,
        skip_memorized: bool = True,
        show_temporal_status_in_refine: bool = True,
    ) -> None:
        super().__init__(system=system)

        # Single dictionary: key → {"msg_id": ..., "description": ...}
        self.keys: Dict[str, Dict[str, str]] = {}

        self.skip_memorized = skip_memorized
        self.show_temporal_status_in_refine = show_temporal_status_in_refine

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    def _temporal_status_block(self) -> str:
        st = self.status()
        if not st:
            return ""
        lines = ["##Available temporal memory keys (use #key to reference):"]
        for k, meta in st.items():
            lines.append(f"- `{k}`: {meta.get('description', '')}")
        return "\n".join(lines) + "\n\n"

    # --------------------------------------------------------------
    # MEMORY MANAGEMENT – *tool* METHODS
    # --------------------------------------------------------------

    def memorize(self, key: str, msg_id: str, description: str) -> str:
        """Memorize a message for later recall.  ⚙️ **Tool for the LLM**

        Parameters
        ----------
        key : str
            A short human-readable identifier (single word) that will be used
            inside user prompts as a *hashtag*, e.g. ``#myFact``.
        msg_id : str
            The internal *message-id* returned by :py:meth:`ContextMemory.add_message`.
            This id points to the piece of conversation we want to store.
        description : str
            A brief explanation that will be shown to the language-model when it
            queries :py:meth:`status` so it can remember what this key stands for.

        Returns
        -------
        str
            The same *msg_id* that was stored.  Useful as a confirmation value.
        """
        if not key or not msg_id or not description:
            return {"error":"msg_id ve description boş olamaz"}
        
        self.keys[key] = {"msg_id": msg_id, "description": description}
        return "success"

    def recall(self, keys: List[str]) -> Dict[str, Any]:
        """Fetch one or more stored messages.  ⚙️ **Tool for the LLM**

        Supports *wildcard* patterns so ``recall(["projA:*"])`` returns **all**
        keys under ``projA``.  Each returned entry is of the form::

            {
                "myKey": {
                    "content": "...full text...",
                    "msg_id": "..."
                },
                "anotherKey": None            # if key not found
            }
        """
        out: Dict[str, Any] = {}
        for pattern in keys:
            # Direct hit first
            if pattern in self.keys:
                meta = self.keys[pattern]
                msg = self.get_message(meta["msg_id"])
                out[pattern] = {"content": msg.get("content") if msg else None,
                                "msg_id": meta["msg_id"]}
                continue

            # Otherwise treat *pattern* as a wildcard
            matches = [k for k in self.keys if fnmatch.fnmatch(k, pattern)]
            if not matches:
                out[pattern] = None
                continue

            for k in matches:
                meta = self.keys[k]
                msg = self.get_message(meta["msg_id"])
                out[k] = {"content": msg.get("content") if msg else None,
                          "msg_id": meta["msg_id"]}
        return out

    def status(self) -> Dict[str, Dict[str, str]]:
        """List all memorised keys grouped by top‑level *scope*.  ⚙️ **Tool**"""
        # Build grouped view for human readability
        grouped: Dict[str, List[str]] = {}
        for key in self.keys:
            top = key.split(":", 1)[0]
            grouped.setdefault(top, []).append(key)
        # Ensure deterministic order
        for vals in grouped.values():
            vals.sort()
        return {
            k: {"description": meta["description"], "msg_id": meta["msg_id"]}
            for k, meta in self.keys.items()
        } | {"_groups": grouped}


    # ------------------------------------------------------------------
    # TOOL-CLIENT
    # ------------------------------------------------------------------

    def create_tool_client(self):
        """Register *tool* functions with a :pyclass:`ToolLocalClient`."""
        client = ToolLocalClient(server_id="temporal-memory")
        client.register_tool_auto(self.recall)
        client.register_tool_auto(self.memorize)
        #client.register_tool_auto(self.status)
        return client

    # ------------------------------------------------------------------
    # REFINE LOGIC – NOT EXPOSED AS TOOLS
    # ------------------------------------------------------------------

    def refine(self, with_id: bool = False) -> List[Dict[str, Any]]:  # noqa: C901
        """Return a pruned/annotated transcript that follows the *7-rule spec*.

        This method is intended for *internal* use and therefore is **not**
        registered as a tool.  It reconstructs the conversation while applying
        several rules (dropping redundant recall exchanges, trimming long tool
        outputs, expanding #tokens, etc.).
        """
        raw = list(self.snapshot())

        # Identify all *temporal-memory* call-IDs by scanning assistant tool_calls
        temporal_callids: Set[str] = set()
        assistant_for: Dict[str, int] = {}
        tool_for: Dict[str, int] = {}
        for idx, m in enumerate(raw):
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls", []):
                    cid = tc.get("id")
                    fn_name = tc.get("function", {}).get("name", "")
                    if cid:
                        assistant_for[cid] = idx
                        if fn_name.startswith("temporal-memory"):
                            temporal_callids.add(cid)
            elif m.get("role") == "tool":
                cid = m.get("tool_call_id")
                if cid:
                    tool_for[cid] = idx

        # Pass 1 – mark recall exchanges that can be dropped (rule 7)
        drop: Set[str] = set()
        for cid in temporal_callids:
            t_idx = tool_for.get(cid)
            if t_idx is None:
                continue
            t_msg = raw[t_idx]
            try:
                recalled = eval(t_msg.get("content", "{}"))
            except Exception:
                continue
            if not isinstance(recalled, dict):
                continue
            if all(k in self.keys for k in recalled):
                drop.add(t_msg["meta"]["id"])
                a_idx = assistant_for.get(cid)
                if a_idx is not None:
                    drop.add(raw[a_idx]["meta"]["id"])

        # Pass 2 – rebuild transcript
        refined: List[Dict[str, Any]] = []
        last_user_idx: Optional[int] = None
        for m in raw:
            mid = m.get("meta", {}).get("id")
            if mid in drop:
                continue
            m = dict(m)  # shallow copy

            # Trim long tool responses *except* temporal-memory ones
            if (
                m.get("role") == "tool"
                and m.get("tool_call_id") not in temporal_callids
                and len(m.get("content", "")) > MAX_TOOL_CONTENT_CHARS
            ):
                m["content"] = (m.get("content") or "")[:MAX_TOOL_CONTENT_CHARS] + _TRIM_NOTICE

            # Inject [msg-id] except for temporal-memory tool outputs
            if with_id and mid and m.get("role") in ("assistant", "tool"):
                if not (
                    m.get("role") == "tool" and m.get("tool_call_id") in temporal_callids
                ):
                    m["content"] = f"{m.get('content') or ''}\n[msg-id:{mid}]"

            refined.append(m)
            if m.get("role") == "user":
                last_user_idx = len(refined) - 1

        # Pass 3 – expand #memoryKey tokens (hierarchical + wildcard)
        if last_user_idx is not None:
            u = refined[last_user_idx]
            txt = u.get("content", "")
            patterns = _MEMORY_TOKEN_RE.findall(txt)
            for pattern in patterns:
                results = self.recall([pattern])
                # Gather all non‑None contents
                contents = [
                    v["content"] for v in results.values() if v and v["content"]
                ]
                if contents:
                    combined = "\n".join(contents)
                    txt = txt.replace(f"#{pattern}", combined)
            u["content"] = txt
            refined[last_user_idx] = u

        # Pass 4 – append status block to first system message
        if self.show_temporal_status_in_refine:
            block = self._temporal_status_block()
            if block:
                for m in refined:
                    if m.get("role") == "system":
                        m["content"] += block
                        break

        return refined


"""
TemporalMemory demo script – unchanged, kept for reference.
"""

if __name__ == "__main__":
    from temporal_memory import TemporalMemory   # Adjust if file name changes

    # 1) Instantiate TemporalMemory
    tm = TemporalMemory(system="Sistem mesajı: Hoş geldiniz!")
    print(tm.status())

    msg_id = tm.add_message({"role": "assistant", "content": "Bu mesajı hafızaya alacağız."})

    # 3) Store the message under a key
    tm.memorize(key="frrev", msg_id=msg_id, description="Fransız Devrimi ilk mesajı")

    # 4) The user sends a prompt that references #frrev
    tm.add_message({"role": "user", "content": "Lütfen #frrev hakkında bana bir soru sor."})

    # 5) Call refine() to test the #frrev substitution
    refined = tm.refine(with_id=True)   # with_id=True to show msg-id tags

    # 6) Print the last user message
    last_user = refined[-1]
    print("=== Son kullanıcı iletisi (refine sonrası) ===")
    print(last_user["content"])
    print("\n=== Tüm refine çıktısı ===")
    for m in refined:
        print(f"[{m['role']}]\t{m['content']}")
