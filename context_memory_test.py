import unittest
from context_memory import ContextMemory

class TestContextMemory(unittest.TestCase):
    def setUp(self):
        self.ctx = ContextMemory(system_prompt="SYSTEM")
        self.ctx.add_user_prompt("U1")
        self.ctx.add_assistant_reply("A1")
        self.ctx.add_tool_calls({"type": "tool", "id": "TOOLCALL1", "name": "foo", "arguments": {}})
        self.ctx.add_tool_result("TOOLCALL1", "T1")
        self.ctx.add_user_prompt("U2")
        self.ctx.add_assistant_reply("A2")

    def test_add_and_snapshot(self):
        messages = self.ctx.snapshot()
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[2]["role"], "assistant")
        self.assertEqual(messages[3]["role"], "assistant")  # tool_calls da assistant olarak eklenir
        self.assertEqual(messages[4]["role"], "tool")
        self.assertEqual(messages[5]["role"], "user")
        self.assertEqual(messages[6]["role"], "assistant")

    def test_parent_id_linking(self):
        messages = self.ctx.snapshot()
        # İlk asistan ve ilk tool, ilk user'a bağlı olmalı
        first_user_id = messages[1]["meta"]["id"]
        self.assertEqual(messages[2]["meta"]["parent_id"], first_user_id)
        self.assertEqual(messages[3]["meta"]["parent_id"], first_user_id)
        self.assertEqual(messages[4]["meta"]["parent_id"], first_user_id)
        # İkinci asistan ikinci user'a bağlı olmalı
        second_user_id = messages[5]["meta"]["id"]
        self.assertEqual(messages[6]["meta"]["parent_id"], second_user_id)

    def test_delete_single_message(self):
        messages = self.ctx.snapshot()
        to_delete_id = messages[2]["meta"]["id"]
        deleted = self.ctx.delete([to_delete_id])
        self.assertEqual(deleted, 1)
        new_messages = self.ctx.snapshot()
        self.assertFalse(any(m["meta"]["id"] == to_delete_id for m in new_messages))

    def test_delete_user_branch(self):
        messages = self.ctx.snapshot()
        first_user_id = messages[1]["meta"]["id"]
        deleted = self.ctx.delete_user([first_user_id])
        self.assertGreaterEqual(deleted, 3)  # user + 2 assistant + tool
        # Bu branch'ın tüm mesajları gitmiş olmalı
        ids = [m["meta"]["id"] for m in self.ctx.snapshot()]
        self.assertNotIn(first_user_id, ids)
        # İkinci user ve onun asistanı durmalı
        self.assertEqual(self.ctx.snapshot()[-2]["role"], "user")
        self.assertEqual(self.ctx.snapshot()[-1]["role"], "assistant")

    def test_delete_tool(self):
        messages = self.ctx.snapshot()
        # TOOLCALL1 id'li assistant ve onun tool cevabı silinecek
        tool_call_id = "TOOLCALL1"
        deleted = self.ctx.delete_tool(tool_call_id)
        self.assertGreaterEqual(deleted, 2)
        new_messages = self.ctx.snapshot()
        # O call'a bağlı assistant ve tool yok
        for m in new_messages:
            if m["role"] == "assistant" and "tool_calls" in m:
                for tc in m["tool_calls"]:
                    self.assertNotEqual(tc["id"], tool_call_id)
            if m["role"] == "tool":
                self.assertNotEqual(m.get("tool_call_id"), tool_call_id)

    def test_cycle_increases(self):
        before = self.ctx.snapshot()
        user_msg = before[1]
        self.assertEqual(user_msg["meta"].get("cycle", 0), 0)
        self.ctx.cycle()
        after = self.ctx.snapshot()
        self.assertEqual(after[1]["meta"]["cycle"], 1)
        self.ctx.cycle()
        after2 = self.ctx.snapshot()
        self.assertEqual(after2[1]["meta"]["cycle"], 2)

    def test_update_content(self):
        messages = self.ctx.snapshot()
        user_msg_id = messages[1]["meta"]["id"]
        self.assertTrue(self.ctx.update_content(user_msg_id, "NEW USER CONTENT"))
        updated_msg = self.ctx.get_message(user_msg_id)
        self.assertEqual(updated_msg["content"], "NEW USER CONTENT")

    def test_clear(self):
        self.ctx.clear(keep_system=True)
        messages = self.ctx.snapshot()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "system")

if __name__ == "__main__":
    unittest.main()
