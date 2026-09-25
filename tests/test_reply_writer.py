from __future__ import annotations

import unittest
from unittest.mock import patch

from src.responder import reply_writer


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '{"should_reply":true,"reply":"Valeu!",'
                                    '"reason":"engagement"}'
                                )
                            }
                        ]
                    }
                }
            ]
        }


class GeminiReplyWriterTests(unittest.TestCase):
    @patch("src.responder.reply_writer.httpx.post", return_value=_Response())
    def test_gemini_requests_bounded_json_without_thinking(self, post) -> None:
        with patch.object(reply_writer, "GEMINI_MODEL", "gemini-2.5-flash"):
            result = reply_writer._via_gemini("Titulo", "Comentario", "Autor")

        body = post.call_args.kwargs["json"]
        config = body["generationConfig"]
        self.assertEqual(config["maxOutputTokens"], 1024)
        self.assertEqual(config["thinkingConfig"], {"thinkingBudget": 0})
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(
            config["responseSchema"]["required"],
            ["should_reply", "reply", "reason"],
        )
        self.assertTrue(result["should_reply"])
        self.assertEqual(result["reply"], "Valeu!")


if __name__ == "__main__":
    unittest.main()
