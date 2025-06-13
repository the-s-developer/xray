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

# blank line after header
_HEADER_SEP: str = "\n\n"


class TemporalMemory(ContextMemory):
    """A context‑aware memory helper that lets the LLM *persist*, *recall* and
    *inspect* small snippets of conversation via simple `#tokens`.

    **Behaviour (revised 2025‑06‑13)**
    ----------------------------------
    *   When a `#key` appears in the *last* user message, every referenced
        message is injected *un‑trimmed* into the prompt for that turn.
    *   Inline‑expand logic is disabled – tokens remain as‑is.
    *   All memorised messages start with a header listing their key(s) and
        descriptions so the LLM is always aware of long‑term memory content.
    """

    # ------------------------------------------------------------------
    # INITIALISATION
    # ------------------------------------------------------------------

    def __init__(
        self,
        system: str,
        *,
        skip_memorized: bool = True,
        show_temporal_status_in_refine: bool = True,
    ) -> None:
        super().__init__(system=system)
        # key → {"msg_id": …, "description": …}
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

    def _build_header_for_msg(self, msg_id: str) -> str:
        parts: List[str] = []
        for k, meta in self.keys.items():
            if meta.get("msg_id") == msg_id:
                desc = meta.get("description", "")
                parts.append(f"[{k}] {desc}" if desc else f"[{k}]")
        return " | ".join(parts) + _HEADER_SEP if parts else ""
    # --------------------------------------------------------------
    # MEMORY MANAGEMENT – TOOL METHODS
    # --------------------------------------------------------------

    def memorize(self, key: str, msg_id: str, description: str) -> str:
        """
        ⚙️ **Tool** – Persist a message snippet for later reuse.

        Call this *immediately after* adding a message you want to turn into a
        reusable snippet.

        Parameters
        ----------
        key : str
            Friendly, **unique** identifier (e.g. ``"projA:intro"``). You will
            refer to the snippet later in prompts via ``#projA:intro``.
        msg_id : str
            The `msg_id` returned by :py:meth:`ContextMemory.add_message` for
            the message you're storing.
        description : str
            One‑sentence, human‑readable summary. Displayed by
            :py:meth:`status` *and* prepended as a header so the model knows
            *what it is* without reading the whole text.

        Returns
        -------
        str
            The literal string ``"success"`` on success.

        Raises (returned as an ``{"error": …}`` dict)
        ---------------------------------------------
        * Empty or missing arguments.
        * Duplicate ``key`` (overwrites silently unless you check).
        """
        if not key or not msg_id or not description:
            return {"error": "msg_id ve description boş olamaz"}
        self.keys[key] = {"msg_id": msg_id, "description": description}
        return "success"

    def recall(self, keys: List[str]) -> Dict[str, Any]:
        """
        ⚙️ **Tool** – Retrieve previously memorised snippets programmatically.

        You can also inject snippets into a prompt by writing ``#key`` directly,
        but this function lets you fetch them inside a tool‑call chain.

        Parameters
        ----------
        keys : List[str]
            Exact key names **or** wildcard patterns. Wildcards follow Unix
            rules – ``*`` matches any sequence (including ``:``), ``?`` matches
            a single character.

        Examples
        --------
        >>> recall(["meeting:notes"])
        >>> recall(["projA:*", "*summary"])

        Returns
        -------
        Dict[str, Any]
            Mapping from *resolved* key → result, where each *result* is either
            ``{"content": <str | None>, "msg_id": <str>}`` or ``None`` if the
            pattern matched nothing.

        Notes
        -----
        *Returned* ``content`` is never trimmed – you receive the full text that
        was originally stored.
        """
        out: Dict[str, Any] = {}
        for pattern in keys:
            if pattern in self.keys:  # exact hit
                meta = self.keys[pattern]
                msg = self.get_message(meta["msg_id"])
                out[pattern] = {
                    "content": msg.get("content") if msg else None,
                    "msg_id": meta["msg_id"],
                }
                continue
            matches = [k for k in self.keys if fnmatch.fnmatch(k, pattern)]
            if not matches:
                out[pattern] = None
                continue
            for k in matches:
                meta = self.keys[k]
                msg = self.get_message(meta["msg_id"])
                out[k] = {
                    "content": msg.get("content") if msg else None,
                    "msg_id": meta["msg_id"],
                }
        return out


    def status(self) -> Dict[str, Dict[str, str]]:
        """⚙️ **Tool** – Overview of all stored keys grouped by namespace."""
        grouped: Dict[str, List[str]] = {}
        for key in self.keys:
            top = key.split(":", 1)[0]
            grouped.setdefault(top, []).append(key)
        for vals in grouped.values():
            vals.sort()
        return {k: {"description": m["description"], "msg_id": m["msg_id"]}
                for k, m in self.keys.items()} | {"_groups": grouped}

    # ------------------------------------------------------------------
    # TOOL‑CLIENT REGISTRATION
    # ------------------------------------------------------------------

    def create_tool_client(self):
        """Register tool methods and return the client (for list_tools etc.)."""
        client = ToolLocalClient(server_id="temporal-memory")
        client.register_tool_auto(self.recall)
        client.register_tool_auto(self.memorize)
        client.register_tool_auto(self.status)
        return client

    
    # ------------------------------------------------------------------
    # REFINE – FULL IMPLEMENTATION (safe for missing 'content')
    # ------------------------------------------------------------------

    def refine(self, with_id: bool = False) -> List[Dict[str, Any]]:  # noqa: C901
        raw = list(self.snapshot())

        # STEP 0 – tokens in last user msg → referenced ids
        patterns: List[str] = []
        referenced_msg_ids: Set[str] = set()
        for idx in range(len(raw) - 1, -1, -1):
            if raw[idx].get("role") == "user":
                patterns = _MEMORY_TOKEN_RE.findall(raw[idx].get("content", ""))
                break
        if patterns:
            for pattern in patterns:
                hits = [pattern] if pattern in self.keys else [k for k in self.keys if fnmatch.fnmatch(k, pattern)]
                for k in hits:
                    referenced_msg_ids.add(self.keys[k]["msg_id"])

        memory_msg_ids: Set[str] = {meta["msg_id"] for meta in self.keys.values()}

        # STEP 1 – mark recall exchanges to drop
        temporal_callids: Set[str] = set()
        assistant_for: Dict[str, int] = {}
        tool_for: Dict[str, int] = {}
        for i, m in enumerate(raw):
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls", []):
                    cid = tc.get("id")
                    if cid:
                        assistant_for[cid] = i
                        if tc.get("function", {}).get("name", "").startswith("temporal-memory"):
                            temporal_callids.add(cid)
            elif (cid := m.get("tool_call_id")):
                tool_for[cid] = i
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
            if isinstance(recalled, dict) and all(k in self.keys for k in recalled):
                drop.add(t_msg["meta"]["id"])
                drop.add(raw[assistant_for[cid]]["meta"]["id"])

        # STEP 2 – rebuild transcript
        refined: List[Dict[str, Any]] = []
        for m in raw:
            mid = m.get("meta", {}).get("id")
            if mid in drop:
                continue
            m = dict(m)  # copy

            content_str = m.get("content", "") if isinstance(m.get("content"), str) else ""

            # header for memorised messages
            if mid in memory_msg_ids:
                header = self._build_header_for_msg(mid)
                if header and not content_str.startswith(header):
                    content_str = header + content_str

            # restore trimmed content if referenced this turn
            if mid in referenced_msg_ids and content_str.endswith(_TRIM_NOTICE):
                orig = self.get_message(mid)
                if orig:
                    content_str = self._build_header_for_msg(mid) + orig.get("content", "")

            # trim long tool outputs (unless protected)
            if (
                m.get("role") == "tool" and
                m.get("tool_call_id") not in temporal_callids and
                len(content_str) > MAX_TOOL_CONTENT_CHARS and
                mid not in referenced_msg_ids
            ):
                content_str = content_str[:MAX_TOOL_CONTENT_CHARS] + _TRIM_NOTICE

            # inject msg-id tag safely
            if with_id and mid and m.get("role") in ("assistant", "tool") and not (
                m.get("role") == "tool" and m.get("tool_call_id") in temporal_callids
            ):
                content_str = f"{content_str}{_HEADER_SEP.rstrip()}[msg-id:{mid}]"

            if content_str:
                m["content"] = content_str
            refined.append(m)

        # STEP 3 – append status block
        if self.show_temporal_status_in_refine:
            block = self._temporal_status_block()
            if block:
                for m in refined:
                    if m.get("role") == "system":
                        m["content"] = m.get("content", "") + block
                        break

        return refined


# ---------------------------------------------------------------------------
# Demo / quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tm = TemporalMemory(system="Sistem mesajı: Hoş geldiniz!")

    aid = tm.add_message({"role": "assistant", "content": "Bu mesajı hafızaya alacağız."})
    tm.memorize("frrev", aid, "Fransız Devrimi ilk mesajı")

    tm.add_message({"role": "user", "content": "Lütfen #frrev hakkında bana bir soru sor."})

    print("\n--- Refine output (with msg ids) ---")
    refined = tm.refine(with_id=True)
    for m in refined:
        print(f"[{m['role']}]\t{m['content'][:100]}…")

    tools_client = tm.create_tool_client()
    print("\nRegistered tool functions:", tools_client.list_tools())
