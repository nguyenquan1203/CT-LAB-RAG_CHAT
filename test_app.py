"""Offline checks for authentication, sessions, retrieval and citation boundaries."""

import json
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import requests
from streamlit.testing.v1 import AppTest

import firebase_client
import rag
from config import GUIDE_PATH

ROOT = GUIDE_PATH.parent
GUIDE_JSON = GUIDE_PATH.read_text(encoding="utf-8")
RECORDS = json.loads(GUIDE_JSON)
HITS = [{**RECORDS[2], "score": 0.9}]


class RagTests(unittest.TestCase):
    def test_cosine_ranking_instead_of_vector_length(self):
        vectors = np.tile([100.0, 0.0], (12, 1))
        vectors[1] = [0.7, 0.7]
        vectors[2] = [0.0, 2.0]
        with patch("rag.embed", return_value=np.array([[0.0, 1.0]])):
            hits = rag.retrieve("What is the post office address?", RECORDS, vectors, "https://test.invalid")
        self.assertEqual([h["id"] for h in hits], ["G03", "G02", "G01"])
        self.assertAlmostEqual(hits[0]["score"], 1.0)

    def test_invalid_guide_fails_before_network(self):
        records = json.loads(GUIDE_JSON)
        records[1]["id"] = records[0]["id"]
        with patch("rag.embed") as embed:
            with self.assertRaises(rag.RAGError):
                rag.build_index(json.dumps(records), "https://test.invalid")
        embed.assert_not_called()

    def test_empty_question_does_not_call_server(self):
        with patch("rag.embed") as embed:
            with self.assertRaises(rag.RAGError):
                rag.retrieve("   ", RECORDS, np.ones((12, 2)), "https://test.invalid")
        embed.assert_not_called()

    def test_zero_embedding_is_rejected(self):
        with patch("rag._post", return_value={"embeddings": [[0, 0]]}):
            with self.assertRaises(rag.RAGError):
                rag.embed(["A sentence"], "https://test.invalid")

    def test_generation_uses_only_retrieved_context_and_correct_model(self):
        with patch("rag._post", return_value={"message": {"content": "2 Cong Xa Paris. [G03]"}}) as post:
            answer = rag.generate("Where is the post office?", HITS, "https://test.invalid")
        payload = post.call_args.args[2]
        self.assertEqual(payload["model"], "qwen3:4b")
        self.assertTrue(payload["think"])
        self.assertEqual(payload["options"]["num_predict"], 4096)
        self.assertEqual(payload["options"]["num_ctx"], 8192)
        self.assertEqual(payload["options"]["temperature"], 0.6)
        self.assertNotIn("/no_think", payload["messages"][1]["content"])
        self.assertIn("Always answer in English", payload["messages"][0]["content"])
        self.assertIn(RECORDS[2]["text"], payload["messages"][1]["content"])
        self.assertNotIn(RECORDS[9]["text"], payload["messages"][1]["content"])
        self.assertIn("[G03]", answer)

    def test_token_limit_never_returns_an_incomplete_answer(self):
        for content in ["The address is 2 Cong Xa Paris. [G03] More", ""]:
            with self.subTest(content=content):
                response = {
                    "done_reason": "length",
                    "message": {"content": content, "thinking": "unfinished"},
                }
                with patch("rag._post", return_value=response):
                    with self.assertRaisesRegex(rag.RAGError, "token limit") as caught:
                        rag.generate("Where is the post office?", HITS, "https://test.invalid")
                    self.assertEqual(caught.exception.stage, "Generation")

    def test_generation_removes_thinking_before_checking_citations(self):
        final = "The Saigon Central Post Office is at 2 Cong Xa Paris. [G03]"
        variants = [
            f"<think>Draft notes with [G99].</think>\n{final}",
            f"Draft notes with [G99].</think>\n{final}",
            f"Draft notes with [G99].\\</think>\n{final}",
            f"<THINK>Draft notes.</THINK>\n{final}",
        ]
        for content in variants:
            with self.subTest(content=content):
                response = {"message": {"content": content, "thinking": "Separate draft notes."}}
                with patch("rag._post", return_value=response):
                    self.assertEqual(rag.generate("Where is the post office?", HITS, "https://test.invalid"), final)

    def test_unfinished_thinking_is_not_shown_as_an_answer(self):
        with patch("rag._post", return_value={"message": {"content": "<think>Draft notes [G03]"}}):
            with self.assertRaisesRegex(rag.RAGError, "no final answer"):
                rag.generate("Where is the post office?", HITS, "https://test.invalid")

    def test_unsupported_or_missing_citations_are_rejected(self):
        for answer in ["Admission costs VND 100,000. [G99]", "Admission costs VND 100,000."]:
            with self.subTest(answer=answer):
                with patch("rag._post", return_value={"message": {"content": answer}}):
                    self.assertEqual(rag.generate("How much is admission?", HITS, "https://test.invalid"), rag.UNKNOWN)

    def test_explicit_unknown_is_preserved(self):
        with patch("rag._post", return_value={"message": {"content": rag.UNKNOWN}}):
            self.assertEqual(rag.generate("Will it rain tomorrow?", HITS, "https://test.invalid"), rag.UNKNOWN)

    def test_network_error_has_actionable_message(self):
        with patch("rag.requests.post", side_effect=requests.ConnectionError("sensitive detail")):
            with self.assertRaises(rag.RAGError) as caught:
                rag.embed(["A question"], "https://test.invalid")
        self.assertIn("Colab", str(caught.exception))
        self.assertNotIn("sensitive detail", str(caught.exception))
        self.assertEqual(caught.exception.stage, "Connection")


class FirebaseTests(unittest.TestCase):
    def test_wrong_password_is_safe_and_never_creates_session(self):
        response = Mock(ok=False)
        response.json.return_value = {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}}
        with patch("firebase_client.FIREBASE_API_KEY", "test-key"):
            with patch("firebase_client.requests.post", return_value=response):
                with self.assertRaises(firebase_client.FirebaseError) as caught:
                    firebase_client.sign_in("a@example.com", "wrong")
        self.assertIn("incorrect", str(caught.exception))

    def test_sign_in_retains_neither_password_nor_tokens(self):
        response = Mock(ok=True)
        response.json.return_value = {
            "localId": "user-1", "email": "a@example.com", "expiresIn": "3600",
            "idToken": "secret-token", "refreshToken": "secret-refresh",
        }
        with patch("firebase_client.FIREBASE_API_KEY", "test-key"):
            with patch("firebase_client.requests.post", return_value=response):
                user = firebase_client.sign_in("a@example.com", "password")
        self.assertEqual(set(user), {"uid", "email", "expires_at"})


class AppTests(unittest.TestCase):
    def test_saved_history_hides_thinking_without_changing_user_messages(self):
        with patch("config.FIREBASE_API_KEY", "test-key"):
            app = AppTest.from_file(str(ROOT / "app.py"))
            app.session_state["user"] = {
                "uid": "user-1", "email": "a@example.com", "expires_at": time.time() + 3600,
            }
            app.session_state["messages"] = [
                {"role": "user", "content": "What does <think> mean?"},
                {"role": "assistant", "content": "Draft notes.</think>2 Cong Xa Paris. [G03]"},
            ]
            app.run()
            self.assertFalse(app.exception)
            messages = app.session_state["messages"]
            self.assertEqual(messages[0]["content"], "What does <think> mean?")
            self.assertEqual(messages[1]["content"], "2 Cong Xa Paris. [G03]")
            self.assertNotIn("Draft notes", " ".join(element.value for element in app.markdown))

    def test_login_chat_cache_and_logout(self):
        with (
            patch("config.FIREBASE_API_KEY", "test-key"),
            patch("config.OLLAMA_BASE_URL", "https://test.invalid"),
            patch("firebase_client.sign_in", return_value={
                "uid": "user-1", "email": "a@example.com", "expires_at": time.time() + 3600,
            }),
            patch("rag.build_index", return_value=(RECORDS, np.ones((12, 2)))) as build,
            patch("rag.retrieve", return_value=HITS),
            patch("rag.generate", return_value="2 Cong Xa Paris. [G03]"),
        ):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_input), 0)
            build.assert_not_called()
            app.text_input[0].set_value("a@example.com")
            app.text_input[1].set_value("password")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_input), 1)
            app.chat_input[0].set_value("Where is the post office?").run()
            app.chat_input[0].set_value("What is the post office address?").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_message), 4)
            self.assertEqual(len(app.expander), 2)
            build.assert_called_once()
            app.sidebar.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_input), 0)
            self.assertEqual(len(app.chat_message), 0)
            with self.assertRaises(KeyError):
                app.session_state["messages"]
            with self.assertRaises(KeyError):
                app.session_state["user"]

    def test_expired_session_clears_old_conversation(self):
        with patch("config.FIREBASE_API_KEY", "test-key"):
            app = AppTest.from_file(str(ROOT / "app.py"))
            app.session_state["user"] = {"uid": "old", "email": "old@example.com", "expires_at": 0}
            app.session_state["messages"] = [{"role": "assistant", "content": "private history"}]
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_input), 0)
            with self.assertRaises(KeyError):
                app.session_state["messages"]


if __name__ == "__main__":
    unittest.main()
