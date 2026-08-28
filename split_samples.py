#!/usr/bin/env python3
"""AtCoder 問題ページのコピペ文からサンプル入出力を自動分割する（フォールバック用）

使い方:
    1. 問題ページを開き、本文（制約〜出力例）をコピー
    2. problem.txt に貼り付けて保存
    3. python split_samples.py

出力: samples/in_1.txt, out_1.txt ...
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Windows のコンソールコードページ (cp932) で文字化けしないよう、出力を UTF-8 に固定
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"

IN_HEAD = re.compile(r"^\s*入力例\s*(\d+)\s*$")
OUT_HEAD = re.compile(r"^\s*出力例\s*(\d+)\s*$")


def parse(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[str, int]] = []
    for i, line in enumerate(lines):
        if IN_HEAD.match(line):
            blocks.append(("in", i))
        elif OUT_HEAD.match(line):
            blocks.append(("out", i))

    if not blocks:
        raise ValueError(
            "「入力例 N」「出力例 N」の見出しが見つかりません。\n"
            "問題ページの本文（制約〜出力例）を正しくコピーできているか確認してください。"
        )

    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(blocks):
        kind, pos = blocks[i]
        end = blocks[i + 1][1] if i + 1 < len(blocks) else len(lines)
        content = "\n".join(lines[pos + 1 : end]).strip()

        if kind == "in":
            out_content = ""
            if i + 1 < len(blocks) and blocks[i + 1][0] == "out":
                out_pos = blocks[i + 1][1]
                out_end = blocks[i + 2][1] if i + 2 < len(blocks) else len(lines)
                out_content = "\n".join(lines[out_pos + 1 : out_end]).strip()
                i += 2
            else:
                i += 1
            pairs.append((content, out_content))
        else:
            if not pairs:
                pairs.append(("", content))
            i += 1
    return pairs


def write_samples(pairs: list[tuple[str, str]]) -> None:
    SAMPLES.mkdir(exist_ok=True)
    for f in SAMPLES.glob("in_*.txt"):
        f.unlink()
    for f in SAMPLES.glob("out_*.txt"):
        f.unlink()
    for n, (inp, out) in enumerate(pairs, start=1):
        (SAMPLES / f"in_{n}.txt").write_text(inp + ("\n" if inp else ""), encoding="utf-8")
        (SAMPLES / f"out_{n}.txt").write_text(out + ("\n" if out else ""), encoding="utf-8")
        print(f"  ケース {n}: 入力 {len(inp.splitlines())} 行 / 出力 {len(out.splitlines())} 行")
    print(f"\n{len(pairs)} ケースを {SAMPLES} に書き出しました。")


def main() -> int:
    if not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "problem.txt"
        if not path.exists():
            print(
                "problem.txt が見つかりません。\n"
                "問題ページの本文を problem.txt に貼り付けて保存してから、このスクリプトを実行してください。"
            )
            return 1
        text = path.read_text(encoding="utf-8")

    try:
        pairs = parse(text)
    except ValueError as e:
        print(f"エラー: {e}")
        return 1

    write_samples(pairs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
