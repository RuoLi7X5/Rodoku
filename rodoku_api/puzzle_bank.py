from __future__ import annotations


def parse_puzzle_bank_text(text: str) -> list[str]:
    """
    将文本题库解析为多个 81 位题目串（0 表示空格）。
    兼容：
    - 空格用 0 或 .
    - 任意分隔（空格/换行/其它符号）
    """
    out: list[str] = []
    buf: list[str] = []

    def flush_if_full():
        nonlocal buf
        if len(buf) == 81:
            out.append("".join(buf))
            buf = []

    for ch in text:
        if "1" <= ch <= "9":
            buf.append(ch)
            flush_if_full()
        elif ch == "0" or ch == ".":
            buf.append("0")
            flush_if_full()
        else:
            # 分隔符
            continue

    return out

