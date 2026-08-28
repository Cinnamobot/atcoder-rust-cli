#!/usr/bin/env python3
"""AtCoder 問題テンプレート自動生成 + 監視 (gen.py)

【神 UX】src/bin/<id>.rs が「新規作成された瞬間」に:
    1. 問題文 (タイトル/制限/問題文/制約/入力/出力) をヘッダコメントとして自動挿入
    2. proconio 入力テンプレート (問題文の「入力」セクションから変数名を推定) を自動生成
    3. サンプル入出力を samples/<id>/ に自動取得 (fetch.py 経由)

    すでにコード (fn main) が書かれているファイルは、ヘッダコメントと
    サンプルのみ更新し、コード本体には触れない。

使い方:
    python gen.py abc086_a          # 1回だけ: src/bin/abc086_a.rs を生成
    python gen.py --watch           # 監視: 新規 .rs / problem 変更 / コード保存 を検知
    python gen.py --all             # src/bin/ に既にある .rs 全部を更新

監視モードの検知ルール:
    - src/bin/ に「新規の .rs」が現れた → 問題文+テンプレート+サンプルを生成
    - 既存ファイルの // problem: が書き換わった → ヘッダ+サンプルを更新
    - コード本体が保存された (ヘッダ自動生成の範囲外が変化) → check.py で自動照合
    （ヘッダ更新でファイルが書き換わっても、ID が同じなら再反応しないので無限ループしない）

ログ:
    監視のログは .watch.log に追記される (ログイン時自動起動での確認用)。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path

# Windows のコンソールコードページ (cp932) で文字化けしないよう、出力を UTF-8 に固定
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT / "src" / "bin"
FETCH = ROOT / "fetch.py"
CHECK = ROOT / "check.py"
LOG_FILE = ROOT / ".watch.log"
POLL_INTERVAL = 0.8  # 監視のポーリング間隔 (秒)
CHECK_DEBOUNCE = 1.2  # コード保存後の連続保存をまとめる待機時間 (秒)

PROBLEM_RE = re.compile(r"^\s*//\s*problem\s*:\s*(\S+)", re.M)
ID_RE = re.compile(r"[a-z]+\d+_[a-z]")

# 生成テンプレートに書く「ヘッダ区切り」 (この間を自動更新する)
HEADER_BEGIN = "// ===== AtCoder 問題情報 (自動生成) ====="
HEADER_END = "// ===== ここまで自動生成 ====="

# ヘッダ領域の終端 (自動生成ヘッダの直後にある空行まで) をコード本体とみなす境界
def _log(msg: str) -> None:
    """コンソールと .watch.log の両方に書き出す。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass

# 生成テンプレートに書く「ヘッダ区切り」 (この間を自動更新する)
HEADER_BEGIN = "// ===== AtCoder 問題情報 (自動生成) ====="
HEADER_END = "// ===== ここまで自動生成 ====="

TEMPLATE = """use proconio::input;

fn main() {{
    input! {{
{body}    }}

    // TODO: 解答を書く
}}
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_problem_id(rs: Path) -> str | None:
    """.rs ファイルの // problem: <id> を読む。無ければ None。"""
    if not rs.exists():
        return None
    m = PROBLEM_RE.search(rs.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def resolve_id(rs: Path) -> str | None:
    """ファイルから problem ID を決める: // problem: 行 → 無ければファイル名 (stem)。"""
    pid = read_problem_id(rs)
    if pid:
        return pid
    if ID_RE.fullmatch(rs.stem):
        return rs.stem
    return None


# ---------------------------------------------------------------------------
# 問題文コメント / テンプレート生成
# ---------------------------------------------------------------------------
def _to_comment(text: str, indent: str = "// ") -> str:
    """複数行テキストを // コメントに変換する。"""
    return "\n".join(indent + ln if ln else indent.rstrip() for ln in text.splitlines())


def build_header(problem_id: str, stmt: dict | None) -> str:
    """問題文+サンプルをヘッダコメントブロックにする。stmt が無ければ最小ブロック。"""
    lines = [HEADER_BEGIN, f"// problem: {problem_id}"]
    if stmt:
        if stmt.get("title"):
            lines.append(f"// {stmt['title']}")
        if stmt.get("limits"):
            lines.append(f"// 制限: {stmt['limits']}")
        for sec in ("問題文", "制約", "入力", "出力"):
            if sec in stmt.get("sections", {}):
                lines.append("//")
                lines.append(f"// 【{sec}】")
                lines.append(_to_comment(stmt["sections"][sec]))
        # サンプル入出力 (問題文の一部としてコメントに含める)
        samples = stmt.get("samples") or []
        for n, (inp, out) in enumerate(samples, start=1):
            lines.append("//")
            lines.append(f"// 【入力例 {n}】")
            lines.append(_to_comment(inp))
            lines.append("//")
            lines.append(f"// 【出力例 {n}】")
            lines.append(_to_comment(out))
    lines.append(HEADER_END)
    return "\n".join(lines)


def _find_len_var(arrays: dict[str, str], scalar_vars: list[str]) -> str | None:
    """配列の長さ変数を探す (arrays の値が N 等のスカラー変数名ならそれを返す)。"""
    for arr_len in arrays.values():
        if arr_len and arr_len.isalpha() and arr_len in scalar_vars:
            return arr_len
    return None


def _len_var_value(len_var: str, scalar_vars: list[str], first_line: list[str]) -> int | None:
    """長さ変数の値をサンプル入力の1行目から読む。数字でなければ None。"""
    if not len_var:
        return None
    # scalar_vars の並び順 == 1行目のトークン順 (大文字小文字は無視)
    for pos, name in enumerate(scalar_vars):
        if name.lower() == len_var.lower():
            if pos < len(first_line) and re.fullmatch(r"-?\d+", first_line[pos]):
                return int(first_line[pos])
            return None
    return None


def build_template(problem_id: str, stmt: dict | None, sample_inputs: list[str] | None = None) -> str:
    """proconio 入力テンプレートを生成する。

    変数名は問題文の「入力」セクションの <var> タグ (fetch.py が抽出済み) を使う。
    添字付き変数 (C_1, ..., C_N) は fetch.py の _fold_vars で 1 つの配列 (C) に畳み込まれ、
    stmt["arrays"] に {"C": "N"} の形で入っている。

    型と構造はサンプル入力から推定する:
        - スカラー: 入力1行目のトークンと順番対応。数字のみ → i64、文字 → String
        - 単一配列 (C_1 ... C_N)     → [i64; n] (長さ判明時) / Vec<i64>
        - 分離配列 (A_1...A_N / B_1...B_N が別行) → a: [i64; n], b: [i64; n]
        - 交互ペア (a_1 b_1 / a_2 b_2 が N 行)    → ab: [(i64, i64); n]
    推定できない場合は TODO コメントだけにする。
    """
    body = ""
    vars_ = (stmt or {}).get("vars", [])
    arrays = (stmt or {}).get("arrays", {}) if stmt else {}

    if vars_:
        # サンプル入力の行構造を解析
        lines: list[list[str]] = []
        if sample_inputs:
            lines = [ln.split() for ln in sample_inputs[0].splitlines() if ln.strip()]
        first_line = lines[0] if lines else []
        all_tokens = [tok for ln in lines for tok in ln]

        # スカラー変数 (配列でないもの) の型: 1行目のトークンと順番対応
        scalar_vars = [v for v in vars_ if v not in arrays]
        scalar_types: dict[str, str] = {}
        for pos, v in enumerate(scalar_vars):
            tok = first_line[pos] if pos < len(first_line) else ""
            scalar_types[v] = "String" if not re.fullmatch(r"-?\d+", tok) else "i64"

        # 配列変数の型: 1行目のスカラートークンを除いた残りから判定
        rest_tokens = all_tokens[len(first_line):]
        rest_lines = lines[1:]  # スカラー行を除いた残り行
        elem_ok = all(re.fullmatch(r"-?\d+", t) for t in rest_tokens) if rest_tokens else True
        elem_ty = "i64" if elem_ok else "String"

        array_vars = [v for v in vars_ if v in arrays]
        # 残り行のトークン数パターンで構造を判別:
        #   - 常に 1 トークン/行 → 列分離 (A_1 / B_1 が 1 行ずつ交互)
        #   - 常に「配列数」トークン/行 → 交互ペア (a_1 b_1 が N 行)
        #   - 常に「長さ N」トークン/行 → 行分離 (A_1...A_N の行の後に B_1...B_N)
        #   - 混在 / 空 → 構造不明
        per_line = len(array_vars)
        if array_vars and rest_lines:
            tokens_per_line = {len(ln) for ln in rest_lines}
        else:
            tokens_per_line = set()
        len_var = _find_len_var(arrays, scalar_vars)
        len_val = _len_var_value(len_var, scalar_vars, first_line)
        separated = tokens_per_line == {1}
        # 行内トークン数による構造判別:
        #   - 各行トークン数 == 配列数 (per_line) → 交互ペア (a_1 b_1 が N 行)
        #   - 各行トークン数 == 配列の長さ N で行数 == 配列数 → 行分離 (A の行, B の行)
        # 交互ペアを優先 (AtCoder で一般的)。行トークン数が配列数でないときのみ行分離を試す。
        interleaved = (
            len(array_vars) >= 2
            and tokens_per_line == {per_line}
            and not separated
        )
        row_separated = (
            len(array_vars) >= 2
            and not interleaved
            and len(rest_lines) == len(array_vars)
            and len(tokens_per_line) == 1
            and len_val is not None
            and next(iter(tokens_per_line)) == len_val
        )

        if len(array_vars) == 1:
            # 単一配列: 長さ判明なら [T; n]、不明なら Vec<T>
            a = array_vars[0]
            len_var = _find_len_var(arrays, scalar_vars)
            if len_var:
                scalar_types[a] = f"[{elem_ty}; {len_var.lower()}]"
            else:
                scalar_types[a] = f"Vec<{elem_ty}>"
        elif separated or row_separated:
            # 分離配列: A_1...A_N / B_1...B_N → a: [i64; n], b: [i64; n]
            # (separated = 1行1トークン、row_separated = 配列ごとに1行)
            len_var = _find_len_var(arrays, scalar_vars)
            for a in array_vars:
                if len_var:
                    scalar_types[a] = f"[{elem_ty}; {len_var.lower()}]"
                else:
                    scalar_types[a] = f"Vec<{elem_ty}>"
        elif interleaved:
            # 交互ペア: a_1 b_1 が N 行 → ab: [(i64, i64); n]
            # 各位置の型: 残り行の列ごとに判定
            col_types: list[str] = []
            for col in range(per_line):
                col_toks = [ln[col] for ln in rest_lines if col < len(ln)]
                col_types.append(
                    "i64" if col_toks and all(re.fullmatch(r"-?\d+", t) for t in col_toks) else "String"
                )
            # proconio は Vec<(T,U)> を読めない (Readable 未実装)。
            # [T; n] は「ちょうど n 個読む」固定長配列で、長さ変数は先に読んだスカラー (N 等)。
            tuple_ty = ", ".join(col_types)
            merged = "".join(array_vars).lower()
            len_var = _find_len_var(arrays, scalar_vars)
            if len_var:
                scalar_types[merged] = f"[({tuple_ty}); {len_var.lower()}]"
            else:
                body += f"        // TODO: {merged}: 入力構造を確認 (長さ不明のタプル配列)\n"
            # 個別の配列変数は出力しない (タプルに統合)
            for a in array_vars:
                scalar_types.pop(a, None)
        else:
            # 構造不明 → TODO コメント
            for a in array_vars:
                scalar_types.pop(a, None)
            body += "        // TODO: 複数配列の入力構造を確認\n"

        # 変数行を組み立て (vars の順序を保つ。タプル統合は個別名をスキップし末尾に追加)
        for v in vars_:
            var = v.strip()
            if not var:
                continue
            var_l = var.lower()
            ty = scalar_types.get(var)
            if ty is None:
                continue
            body += f"        {var_l}: {ty},\n"
        # タプル統合名を最後に追加
        if interleaved and len(array_vars) >= 2:
            merged = "".join(array_vars).lower()
            if merged in scalar_types:
                body += f"        {merged}: {scalar_types[merged]},\n"

    if not body:
        body = "        // TODO: 入力形式に合わせて変数を定義\n"
    return TEMPLATE.format(body=body)


def _fetch_statement(problem_id: str) -> dict | None:
    """fetch.py の抽出ロジックを再利用して問題文を取得する。失敗時 None。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("fetch_mod", FETCH)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fetch_mod"] = mod
    try:
        spec.loader.exec_module(mod)
        url = mod.to_url(problem_id)
        html_text = mod.fetch_html(url)
        return mod.extract_statement(html_text)
    except Exception:
        return None


def generate(problem_id: str, rs: Path, force: bool = False) -> tuple[bool, str]:
    """src/bin/<id>.rs を生成 or 更新する。戻り値: (成功?, メッセージ)。

    冪等性: ヘッダが既に同一でサンプルも存在する場合は何もせず「最新」を返す。
    （VSCode の File Watcher が「生成→保存」を再検知しても無限ループしないため）

    手順:
      1. fetch.py でサンプルを取得 (samples/<id>/)
      2. 問題文を抽出してヘッダコメントを組み立て
      3a. ファイルが無い / コード (fn main) が無い → ヘッダ + テンプレートで作成
      3b. コードがある → 自動生成ヘッダの区間だけ置換 (コード本体は触らない)
    """
    # --- サンプル取得 (fetch.py に一元化) ---
    res = subprocess.run(
        [sys.executable, str(FETCH), problem_id],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if res.returncode != 0:
        return False, "fetch.py 失敗:\n" + (res.stdout + res.stderr).strip()

    rs.parent.mkdir(parents=True, exist_ok=True)
    stmt = _fetch_statement(problem_id)

    # サンプル入力の1行目 (型推定用)
    sample_inputs: list[str] = []
    sdir = ROOT / "samples" / problem_id
    if sdir.is_dir():
        for f in sorted(sdir.glob("in_*.txt")):
            try:
                sample_inputs.append(f.read_text(encoding="utf-8"))
            except OSError:
                pass

    header = build_header(problem_id, stmt)

    # 冪等チェック: 既存ファイルのヘッダが同一で、サンプルもあるなら何もしない
    if rs.exists() and not force:
        text = rs.read_text(encoding="utf-8")
        b = text.find(HEADER_BEGIN)
        e = text.find(HEADER_END)
        if b != -1 and e != -1 and text[b : e + len(HEADER_END)] == header:
            if sdir.is_dir() and any(sdir.glob("in_*.txt")):
                return True, f"最新 (変更なし): {rs.name}"

    if rs.exists():
        text = rs.read_text(encoding="utf-8")
        if "fn main" not in text:
            # 空 / コメントだけ → テンプレートごと書き直し
            template = build_template(problem_id, stmt, sample_inputs)
            rs.write_text(header + "\n\n" + template, encoding="utf-8")
            return True, f"生成 (テンプレート): {rs.name}"

        # コードあり → ヘッダ区間だけ置換
        b = text.find(HEADER_BEGIN)
        e = text.find(HEADER_END)
        if b != -1 and e != -1:
            e += len(HEADER_END)
            new_text = text[:b] + header + text[e:]
        else:
            m = PROBLEM_RE.search(text)
            if m:
                pos = m.end()
                new_text = text[:pos] + "\n" + header + text[pos:]
            else:
                new_text = header + "\n" + text
        rs.write_text(new_text, encoding="utf-8")
        return True, f"ヘッダ更新: {rs.name}"
    else:
        # 新規: ヘッダ + テンプレート
        template = build_template(problem_id, stmt, sample_inputs)
        rs.write_text(header + "\n\n" + template, encoding="utf-8")
        return True, f"生成: {rs.name}"


def run_check(problem_id: str) -> bool:
    """check.py を呼んで照合する。戻り値: 全PASS なら True。"""
    _log(f"[check] {problem_id} を照合します...")
    res = subprocess.run(
        [sys.executable, str(CHECK), problem_id],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    out = (res.stdout + res.stderr).strip()
    for ln in out.splitlines():
        _log("  " + ln)
    return res.returncode == 0


# ---------------------------------------------------------------------------
# 監視
# ---------------------------------------------------------------------------
def _code_hash(text: str) -> str:
    """自動生成ヘッダを除いた「コード本体」部分のハッシュ。

    ヘッダ区切り (HEADER_BEGIN 〜 HEADER_END) を除いた残り全体のハッシュ。
    ヘッダが無い場合は全文。
    """
    b = text.find(HEADER_BEGIN)
    e = text.find(HEADER_END)
    if b != -1 and e != -1:
        code = text[:b] + text[e + len(HEADER_END):]
    else:
        code = text
    return _hash(code)


def _snapshot() -> dict[str, tuple[str, str, str]]:
    """src/bin/*.rs の {ファイル名: (problem_id, ヘッダハッシュ, コードハッシュ)}。"""
    snap: dict[str, tuple[str, str, str]] = {}
    if not BIN_DIR.exists():
        return snap
    for rs in BIN_DIR.glob("*.rs"):
        text = rs.read_text(encoding="utf-8", errors="replace")
        snap[rs.name] = (resolve_id(rs) or "", _hash(text), _code_hash(text))
    return snap


def watch() -> int:
    """src/bin/ を監視し、新規 .rs / problem 変更 / コード保存を検知して自動処理。"""
    _log(f"[watch] {BIN_DIR} を監視中 (Ctrl+C で終了)")
    _log("  - 新規 .rs / // problem: 変更 → 問題文+テンプレート+サンプルを自動生成")
    _log("  - コード保存 → check.py で自動照合")
    prev = _snapshot()
    # 保存→チェックの連続発火を抑えるデバウンス (問題ID -> 最終チェック時刻)
    last_check: dict[str, float] = {}
    while True:
        time.sleep(POLL_INTERVAL)
        cur = _snapshot()
        for name, (pid, h, code_h) in cur.items():
            old = prev.get(name)
            if old is None:
                if pid:
                    _log(f"[watch] 新規検出: {name} (problem: {pid})")
                    ok, msg = generate(pid, BIN_DIR / name)
                    _log(f"  {'OK' if ok else 'FAIL'}: {msg}")
                    if ok and pid:
                        time.sleep(CHECK_DEBOUNCE)
                        run_check(pid)
            elif old[0] != pid:
                _log(f"[watch] problem 変更: {name} {old[0] or '(なし)'} -> {pid}")
                ok, msg = generate(pid, BIN_DIR / name)
                _log(f"  {'OK' if ok else 'FAIL'}: {msg}")
                if ok and pid:
                    time.sleep(CHECK_DEBOUNCE)
                    run_check(pid)
            elif old[2] != code_h:
                # コード本体が保存された → 自動チェック (デバウンス付き)
                now = time.time()
                if pid and now - last_check.get(pid, 0) > CHECK_DEBOUNCE:
                    last_check[pid] = now
                    _log(f"[watch] コード保存: {name}")
                    run_check(pid)
        prev = cur


def main() -> int:
    parser = argparse.ArgumentParser(description="AtCoder 問題テンプレート自動生成")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("problem_id", nargs="?", help="例: abc086_a / URL / src/bin/abc086_a.rs のファイルパス")
    g.add_argument("--watch", action="store_true", help="src/bin/ を監視して自動生成")
    g.add_argument("--all", action="store_true", help="src/bin/ にある全 .rs を更新")
    args = parser.parse_args()

    if args.watch:
        return watch()

    targets: list[tuple[str, Path]] = []
    if args.all:
        if BIN_DIR.exists():
            for rs in sorted(BIN_DIR.glob("*.rs")):
                pid = resolve_id(rs)
                if pid:
                    targets.append((pid, rs))
        if not targets:
            print("src/bin/ に対象の .rs がありません。")
            return 1
    elif args.problem_id:
        arg = args.problem_id.strip()
        # ファイルパス指定 (例: src/bin/abc086_a.rs, C:\...\abc086_a.rs)
        # 存在しないファイルでも、ファイル名が abc086_a 形式なら新規生成する
        p = Path(arg)
        if p.suffix == ".rs":
            rs = p if p.is_absolute() else (ROOT / p).resolve()
            # 存在すれば // problem: 行から、無ければファイル名 (stem) から解決
            pid = resolve_id(rs) if rs.exists() else (rs.stem if ID_RE.fullmatch(rs.stem) else None)
            if not pid:
                print(f"問題IDを特定できません: {rs.name} (ファイル名が abc086_a 形式か、// problem: 行を書いてください)")
                return 1
            targets.append((pid, rs))
        else:
            # 問題ID or URL
            pid = arg
            m = re.search(r"/([a-z]+\d+_[a-z])/?$", pid)
            if m:
                pid = m.group(1)
            if not ID_RE.fullmatch(pid):
                print(f"問題IDの形式が不正: {pid!r} (例: abc086_a)")
                return 1
            targets.append((pid, BIN_DIR / f"{pid}.rs"))
    else:
        parser.print_help()
        return 1

    n_ok = 0
    for pid, rs in targets:
        ok, msg = generate(pid, rs)
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
        n_ok += ok
    print(f"\n完了: {n_ok}/{len(targets)}")
    return 0 if n_ok == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
