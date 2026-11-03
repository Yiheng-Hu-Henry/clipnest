from __future__ import annotations

import unittest

from clipnest.filter import find_sensitive, is_sensitive, redact


class SensitiveFilterTestCase(unittest.TestCase):
    def test_private_key(self) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
        self.assertIn("private_key", find_sensitive(pem))

    def test_aws_key(self) -> None:
        self.assertIn("aws_access_key", find_sensitive("key=AKIAIOSFODNN7EXAMPLE"))

    def test_github_token(self) -> None:
        self.assertIn("github_token", find_sensitive("ghp_" + "a" * 36))

    def test_openai_key(self) -> None:
        self.assertIn("openai_key", find_sensitive("sk-" + "A1b2C3d4" * 4))

    def test_jwt(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1g"
        self.assertIn("jwt", find_sensitive(token))

    def test_connection_string(self) -> None:
        self.assertIn(
            "connection_string",
            find_sensitive("postgres://admin:hunter2@db.internal:5432/app"),
        )

    def test_credential_assignment(self) -> None:
        self.assertIn("credential_assignment", find_sensitive("password = hunter2"))
        self.assertIn("credential_assignment", find_sensitive("API_KEY: abcd1234efgh"))

    def test_cn_id_card(self) -> None:
        self.assertIn("cn_id_card", find_sensitive("身份证 11010519491231002X"))

    def test_long_digit_sequence(self) -> None:
        self.assertIn("long_digit_sequence", find_sensitive("6222021234567890123"))

    # ------------------------------------------------------------ 不该误伤

    def test_plain_text_is_clean(self) -> None:
        samples = [
            "今天下午三点开会",
            "npm run build",
            "https://example.com/docs?page=2",
            "SELECT * FROM users WHERE id = 42;",
            "版本 1.2.3 已发布",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertFalse(is_sensitive(sample))

    def test_short_numbers_are_clean(self) -> None:
        self.assertFalse(is_sensitive("订单号 1234567890"))

    def test_empty_input(self) -> None:
        self.assertEqual(find_sensitive(""), [])
        self.assertFalse(is_sensitive(""))

    # ------------------------------------------------------------ 脱敏

    def test_redact_masks_secret(self) -> None:
        text = "token ghp_" + "b" * 36 + " 别外传"
        masked = redact(text)
        self.assertNotIn("b" * 36, masked)
        self.assertIn("***", masked)
        self.assertIn("别外传", masked)


if __name__ == "__main__":
    unittest.main()
