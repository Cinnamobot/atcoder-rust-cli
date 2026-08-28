#!/usr/bin/env python3
"""AtCoder 問題ページから本文をスクレイピングしてサンプルを自動分割する

使い方:
    python fetch.py abc086_a
    python fetch.py https://atcoder.jp/contests/abc086/tasks/abc086_a

動作:
    1. 問題ページを取得 (User-Agent 指定)
    2. HTML から <pre> のサンプル入出力を抽出
       → samples/<id>/in_1.txt, out_1.txt ...
    3. 問題文 (タイトル / 制限 / 問題文 / 制約 / 入力 / 出力) をテキスト抽出
       (gen.py が src/bin/<id>.rs のヘッダコメントとして使う)
    4. src/bin/<id>.rs のヘッダに // problem: <id> を付与（無ければ）

注意:
    Turnstile (CAPTCHA) はログイン/提出側にあり、問題ページ取得には通常影響しない。
    もしブロックされたら、split_samples.py (problem.txt 方式) にフォールバック。
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.request
from pathlib import Path

# Windows のコンソールコードページ (cp932) で文字化けしないよう、出力を UTF-8 に固定
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent
SAMPLES_ROOT = ROOT / "samples"
BIN_DIR = ROOT / "src" / "bin"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

ID_RE = re.compile(r"[a-z]+\d+_[a-z]")


def to_url(problem_id: str) -> str:
    """問題ID (abc086_a) を URL に変換する。URL ならそのまま返す。"""
    problem_id = problem_id.strip()
    if problem_id.startswith("http"):
        return problem_id
    m = re.fullmatch(r"([a-z]+\d+)_([a-z])", problem_id)
    if not m:
        raise ValueError(f"問題番号の形式が不正: {problem_id!r} (例: abc086_a)")
    contest, task = m.group(1), m.group(2)
    return f"https://atcoder.jp/contests/{contest}/tasks/{contest}_{task}"


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# サンプル入出力の抽出
# ---------------------------------------------------------------------------
def extract_samples(html_text: str) -> list[tuple[str, str]]:
    """<pre> の内容を順に読み、「入力例」「出力例」の直後の pre をペアにする。

    AtCoder の HTML 構造:
        <h3>入力例 1</h3><pre>...</pre>
        <h3>出力例 1</h3><pre>...</pre>
    """
    tokens: list[tuple[str, str]] = []  # ("h3"|"pre", text)
    for m in re.finditer(r"<h3>(.*?)</h3>|<pre>(.*?)</pre>", html_text, re.S):
        h3, pre = m.group(1), m.group(2)
        if h3 is not None:
            t = re.sub(r"<[^>]+>", "", h3).strip()
            tokens.append(("h3", t))
        else:
            tokens.append(("pre", html.unescape(pre)))

    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        kind, text = tokens[i]
        if kind == "h3" and text.startswith("入力例"):
            inp = tokens[i + 1][1].strip() if i + 1 < len(tokens) and tokens[i + 1][0] == "pre" else ""
            out = ""
            j = i + 1
            while j < len(tokens):
                if tokens[j][0] == "h3" and tokens[j][1].startswith("出力例"):
                    if j + 1 < len(tokens) and tokens[j + 1][0] == "pre":
                        out = tokens[j + 1][1].strip()
                    break
                j += 1
            pairs.append((inp, out))
            i = j + 1  # 出力例の pre の次へ
        else:
            i += 1
    return pairs


# ---------------------------------------------------------------------------
# 問題文 (ヘッダコメント用) の抽出
# ---------------------------------------------------------------------------
# TeX コマンド → Unicode 記号 (AtCoder の新しい問題は \leq 等をそのまま埋め込む)
TEX_REPLACEMENTS: dict[str, str] = {
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\lt": "<", r"\gt": ">", r"\ne": "≠", r"\neq": "≠",
    r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\pm": "±",
    r"\in": "∈", r"\notin": "∉", r"\ni": "∋", r"\subset": "⊂",
    r"\subseteq": "⊆", r"\supset": "⊃", r"\supseteq": "⊇",
    r"\cup": "∪", r"\cap": "∩", r"\emptyset": "∅",
    r"\land": "∧", r"\lor": "∨", r"\lnot": "¬",
    r"\to": "→", r"\rightarrow": "→", r"\leftarrow": "←",
    r"\infty": "∞", r"\forall": "∀", r"\exists": "∃",
    r"\ldots": "…", r"\dots": "…", r"\cdots": "⋯", r"\vdots": "⋮", r"\ddots": "⋱",
    r"\min": "min", r"\max": "max", r"\bmod": " mod ",
    r"\{": "{", r"\}": "}", r"\ ": " ", r"\\": " ",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\theta": "θ", r"\lambda": "λ",
    r"\mu": "μ", r"\pi": "π", r"\sigma": "σ", r"\phi": "φ", r"\omega": "ω",
}
# 長いものを先に置換 (例: \leq と \le が混在)
_TEX_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(TEX_REPLACEMENTS, key=len, reverse=True))
)


def _replace_tex(text: str) -> str:
    """TeX コマンドを Unicode 記号に置換する (未対応コマンドはバックスラッシュ除去)。"""
    def _sub(m: re.Match) -> str:
        return TEX_REPLACEMENTS.get(m.group(0), m.group(0)[1:])
    return _TEX_RE.sub(_sub, text)


def html_to_text(html_text: str) -> str:
    """HTML 断片をプレーンテキストに変換する (段落/箇条書きを改行に)。"""
    t = re.sub(r"<(br|/p|/li|/ul|/h\d|/section)>", "\n", html_text, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = _replace_tex(t)
    lines = [ln.strip() for ln in t.splitlines()]
    out: list[str] = []
    prev_empty = False
    for ln in lines:
        if ln == "":
            if not prev_empty:
                out.append("")
            prev_empty = True
        else:
            out.append(ln)
            prev_empty = False
    return "\n".join(out).strip()


def extract_statement(html_text: str) -> dict:
    """問題文のタイトル・制限・各セクション・変数名・サンプルを抽出する。

    戻り値:
        {"title": str, "limits": str, "sections": {...}, "vars": [str, ...],
         "samples": [(入力, 出力), ...]}
    """
    stmt: dict = {"title": "", "limits": "", "sections": {}, "vars": [], "samples": []}

    m = re.search(r'<span class="h2">(.*?)</span>', html_text, re.S)
    if m:
        t = m.group(1)
        t = re.sub(r"<a[^>]*>.*?</a>", "", t, flags=re.S)  # Editorial 等のリンク除去
        stmt["title"] = re.sub(r"<[^>]+>", "", t).strip()

    m = re.search(r"<p>\s*時間制限\s*:\s*(.*?)\s*/\s*メモリ制限\s*:\s*(.*?)\s*</p>", html_text, re.S)
    if m:
        stmt["limits"] = f"{html.unescape(m.group(1)).strip()} / {html.unescape(m.group(2)).strip()}"

    for m in re.finditer(r"<h3>(.*?)</h3>(.*?)(?=<h3>|$)", html_text, re.S):
        head = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if head in ("問題文", "制約", "入力", "出力"):
            stmt["sections"][head] = html_to_text(m.group(2))
            if head == "入力":
                # 変数名は <var>タグ</var> に入っている (例: <var>a</var> <var>b</var>)
                raw_vars = re.findall(r"<var>(.*?)</var>", m.group(2), re.S)
                stmt["vars"], stmt["arrays"] = _fold_vars(raw_vars)

    # サンプル入出力 (入力例 N / 出力例 N のペア)
    stmt["samples"] = extract_samples(html_text)

    return stmt


# 添字付き変数を畳み込むための正規表現
#   C_1, C_2, \dots, C_N  →  添字1のC, 添字2のC, ... 添字NのC
#   a_1 b_1 / a_2 b_2 ... →  a: 配列, b: 配列
_INDEXED_RE = re.compile(r"^(.+?)_(\d+)$")          # C_1, a_2 など
_RANGE_END_RE = re.compile(r"^(.+?)_([A-Za-z]+)$")  # C_N, a_M など (添字が変数)


def _is_indexed(v: str) -> str | None:
    """添字付き変数なら base 名を返す (C_1, C_N → 'C')。それ以外は None。"""
    v = v.strip()
    if v.startswith("\\"):
        return None
    m = _INDEXED_RE.match(v) or _RANGE_END_RE.match(v)
    return m.group(1) if m else None


def _fold_vars(raw_vars: list[str]) -> tuple[list[str], dict[str, str]]:
    """<var> タグの生リストを畳み込む。

    連続する「同じ名前 + 添字」の変数 (C_1, C_2, ..., C_N) を 1 つの配列名 (C) に
    まとめる。戻り値: (vars リスト, {配列名: 長さ変数名 or "?"})

    例:
        ["N","A","B","C_1","C_2","\\dots","C_N"]
            → (["N","A","B","C"], {"C": "N"})
        ["N","X","a_1","b_1","\\vdots","a_N","b_N"]
            → (["N","X","a","b"], {"a": "N", "b": "N"})
    """
    cleaned = [v for v in raw_vars if not v.startswith("\\")]
    n = len(cleaned)

    # 各位置の base (添字付きのみ)
    bases = [_is_indexed(v) for v in cleaned]

    vars_out: list[str] = []
    arrays: dict[str, str] = {}
    i = 0
    while i < n:
        b = bases[i]
        if b is None:
            vars_out.append(cleaned[i])
            i += 1
            continue

        # 同じ base が後続に現れるか (添字1, 2, ..., N の連続)
        j = i + 1
        while j < n and bases[j] == b:
            j += 1
        if j > i + 1:
            # 配列: 長さは最後の添字 (C_N → N)
            last = cleaned[j - 1].strip()
            lm = _RANGE_END_RE.match(last)
            length = lm.group(2) if lm and not lm.group(2).isdigit() else (
                lm.group(2) if lm else "?"
            )
            arrays[b] = length
            vars_out.append(b)
            i = j
            continue

        # 交互パターン: a_1 b_1 / a_2 b_2 ... (異なる base が同数ペアで並ぶ)
        # i 位置の base の次も添字付きで、さらにその次が再び同じ base → 配列ペア
        if i + 2 < n and bases[i + 1] is not None and bases[i + 2] == b:
            # 長さ: このブロック内の範囲終端 (a_N 等) の添字
            length = "?"
            for k in range(i, n):
                lm = _RANGE_END_RE.match(cleaned[k])
                if lm and lm.group(1) == b:
                    length = lm.group(2)
            arrays[b] = length
            vars_out.append(b)
            # 同じ base の後続をまとめて消費
            j = i + 2
            while j < n and bases[j] == b:
                j += 1
            i = j
            continue

        # a_1 b_1 a_2 b_2 ... a_N b_N (交互ペアの最後で second 側に来た場合)
        # 前の要素が添字付きで、base が異なる → 交互ペアの2番目として配列化
        if i >= 1 and bases[i - 1] is not None and bases[i - 1] != b:
            # 長さ: この b の範囲終端 (b_N 等) の添字
            length = "?"
            for k in range(i, n):
                lm = _RANGE_END_RE.match(cleaned[k])
                if lm and lm.group(1) == b:
                    length = lm.group(2)
            arrays[b] = length
            vars_out.append(b)
            # 後続の同じ base (b_N+1...) を消費
            j = i + 1
            while j < n and bases[j] == b:
                j += 1
            i = j
            continue

        # 単独の添字付き (例: S_1 が1個だけ)
        vars_out.append(cleaned[i])
        i += 1

    return vars_out, arrays


# ---------------------------------------------------------------------------
# サンプルの書き出し
# ---------------------------------------------------------------------------
def write_samples(pairs: list[tuple[str, str]], problem_id: str) -> Path:
    """samples/<id>/in_N.txt, out_N.txt に書き出す。サンプルディレクトリを返す。"""
    sdir = SAMPLES_ROOT / problem_id
    sdir.mkdir(parents=True, exist_ok=True)
    for f in sdir.glob("in_*.txt"):
        f.unlink()
    for f in sdir.glob("out_*.txt"):
        f.unlink()
    for n, (inp, out) in enumerate(pairs, start=1):
        (sdir / f"in_{n}.txt").write_text(inp + ("\n" if inp else ""), encoding="utf-8")
        (sdir / f"out_{n}.txt").write_text(out + ("\n" if out else ""), encoding="utf-8")
        print(f"  ケース {n}: 入力 {len(inp.splitlines())} 行 / 出力 {len(out.splitlines())} 行")
    return sdir


def ensure_problem_header(problem_id: str) -> None:
    """src/bin/<id>.rs の冒頭に // problem: <id> を付与（無ければ）。"""
    rs = BIN_DIR / f"{problem_id}.rs"
    if not rs.exists():
        return
    text = rs.read_text(encoding="utf-8")
    if re.search(r"^\s*//\s*problem\s*:", text, re.M):
        return
    rs.write_text(f"// problem: {problem_id}\n{text}", encoding="utf-8")
    print(f"{rs.name} の冒頭に // problem: {problem_id} を追加しました")


def main() -> int:
    parser = argparse.ArgumentParser(description="AtCoder 問題取得 (サンプル+問題文)")
    parser.add_argument("problem_id", help="例: abc086_a または URL")
    args = parser.parse_args()

    pid = args.problem_id
    try:
        url = to_url(pid)
        print(f"取得: {url}")
        html_text = fetch_html(url)
        pairs = extract_samples(html_text)
        if not pairs:
            print("エラー: サンプルが見つかりませんでした（ページ構成が変わった？）")
            return 1

        m = re.search(r"/([a-z]+\d+_[a-z])/?$", url)
        norm = m.group(1) if m else pid
        sdir = write_samples(pairs, norm)
        ensure_problem_header(norm)

        stmt = extract_statement(html_text)
        secs = stmt["sections"]
        print(f"\n{len(pairs)} ケースを {sdir} に取得しました。")
        print(f"問題文: {stmt['title'] or '(不明)'}  (セクション: {', '.join(secs) or 'なし'})")
        print("gen.py で src/bin/<id>.rs に問題文+テンプレートを生成できます。")
        return 0
    except Exception as e:
        print(f"エラー: {type(e).__name__}: {e}")
        print("ネットワーク不可 or ブロックされた場合は split_samples.py (problem.txt 方式) を使ってください。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
