"""敏感内容识别。

剪贴板里最容易被无意记下来的,正是那些不该落盘的东西:私钥、访问令牌、
带密码的连接串、身份证号。这里用一组保守的正则做纯本地检测,命中即跳过,
既不写数据库,也不进日志。

设计取舍:宁可多跳过一条普通文本,也不要把一条密钥存进历史。因此像
「16~19 位连续数字」这样会误判订单号的规则也在列 —— 由调用方决定是否启用。
"""

from __future__ import annotations

import re
from typing import List, Tuple

Rule = Tuple[str, "re.Pattern[str]"]

#: (规则名, 正则)。顺序即优先级,报告时取第一个命中项。
RULES: Tuple[Rule, ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    ),
    (
        "aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    (
        "slack_token",
        re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    ),
    (
        "openai_key",
        re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
        ),
    ),
    (
        "connection_string",
        re.compile(
            r"(?i)\b(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|amqp)://"
            r"[^\s:@/]+:[^\s@/]+@"
        ),
    ),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token)"
            r"\b\s*[:=]\s*['\"]?\S{6,}"
        ),
    ),
    (
        "cn_id_card",
        re.compile(
            r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}"
            r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
        ),
    ),
    (
        "long_digit_sequence",
        re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
    ),
)


def find_sensitive(text: str) -> List[str]:
    """返回命中的规则名列表（可能为空）。"""
    if not text:
        return []
    return [name for name, pattern in RULES if pattern.search(text)]


def is_sensitive(text: str) -> bool:
    """是否存在任何敏感特征。"""
    return bool(find_sensitive(text))


def redact(text: str, mask: str = "***") -> str:
    """把命中片段替换成 ``mask``，便于把内容安全地写进日志。"""
    result = text
    for _, pattern in RULES:
        result = pattern.sub(mask, result)
    return result
