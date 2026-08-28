#!/usr/bin/env python3
"""AtCoder サンプル照合スクリプト (Cargo + proconio 対応版)

使い方:
    python check.py                    # src/bin/ の対象 .rs を cargo build して照合
    python check.py abc086_a           # 問題ID指定で照合
    python check.py "cargo run"        # 任意コマンドで照合（言語切替）

対象の探し方 (問題ID):
    - 引数で指定 (abc086_a)
    - 無ければ src/bin/*.rs の内、samples/<id>/ がある最初のもの
    - 無ければ src/main.rs の // problem: ヘッダ
    - 無ければ src/main.rs 自体 (旧レイアウト)

サンプルの置き場:
    samples/<id>/in_1.txt, out_1.txt ...   (問題ID別)
    samples/in_1.txt, out_1.txt ...        (旧レイアウト / 単一問題)

自動取得:
    samples にケースが無い場合、// problem: <id> を読んで fetch.py で自動取得。

終了コード: 全部 PASS で 0、FAIL/エラーがあれば 1
"""
from __future__ import annotations

import argparse
import hashlib
import os
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
SAMPLES_ROOT = ROOT / "samples"
BIN_DIR = ROOT / "src" / "bin"
MAIN_RS = ROOT / "src" / "main.rs"
TIMEOUT_SEC = 10.0  # cargo build の初回は遅いので長め

PROBLEM_RE = re.compile(r"^\s*//\s*problem\s*:\s*(\S+)", re.M)


def resolve_problem_id(arg: str | None) -> tuple[str | None, Path | None]:
    """照合対象の (problem_id, .rs ファイル) を決める。

    arg は 問題ID (abc086_a)、URL、または .rs ファイルパスのいずれか。
    """
    if arg:
        arg = arg.strip()
        p = Path(arg)
        # .rs ファイルパス指定 (VSCode の ${file} から渡される)
        if p.suffix == ".rs":
            rs = p if p.is_absolute() else (ROOT / p).resolve()
            pid = read_problem_id(rs) or (rs.stem if rs.exists() else None)
            return pid, (rs if rs.exists() else None)
        # 問題ID or URL
        m = re.search(r"([a-z]+\d+_[a-z])/?$", arg)
        pid = m.group(1) if m else arg
        rs = BIN_DIR / f"{pid}.rs"
        if rs.exists():
            return pid, rs
        return pid, None

    # src/bin/ から samples が揃っている最初のものを選ぶ
    if BIN_DIR.exists():
        for rs in sorted(BIN_DIR.glob("*.rs")):
            pid = read_problem_id(rs)
            if pid and (SAMPLES_ROOT / pid).exists():
                return pid, rs
        # 無ければ最初の .rs
        for rs in sorted(BIN_DIR.glob("*.rs")):
            pid = read_problem_id(rs) or rs.stem
            return pid, rs

    # 旧レイアウト: src/main.rs
    pid = read_problem_id(MAIN_RS)
    return pid, (MAIN_RS if MAIN_RS.exists() else None)


def read_problem_id(rs: Path) -> str | None:
    if not rs.exists():
        return None
    m = PROBLEM_RE.search(rs.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def find_samples(problem_id: str | None) -> Path | None:
    """サンプルディレクトリを探す。problem_id があれば samples/<id>/、無ければ samples/。"""
    if problem_id:
        d = SAMPLES_ROOT / problem_id
        if d.is_dir():
            return d
    if (SAMPLES_ROOT / "in_1.txt").exists():
        return SAMPLES_ROOT
    return None


def iter_cases(sdir: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for inp in sorted(sdir.glob("in_*.txt")):
        num = inp.stem.split("_", 1)[1]
        out = sdir / f"out_{num}.txt"
        if out.exists():
            pairs.append((inp, out))
        else:
            print(f"  [WARN] {out.name} が無いので {inp.name} はスキップ")
    return pairs


def run_command(cmd: list[str], stdin_data: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_SEC,
        cwd=ROOT,
    )


def normalize(text: str) -> str:
    """出力比較用の正規化: 行ごとの末尾空白除去 + 空行除去。"""
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())


def maybe_auto_fetch(problem_id: str) -> list[tuple[Path, Path]] | None:
    """samples/<id>/ を fetch.py で自動取得して照合ケースを返す。失敗時 None。"""
    print(f"[fetch] {problem_id} のサンプルを取得します...")
    res = subprocess.run(
        [sys.executable, str(ROOT / "fetch.py"), problem_id],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        print((res.stdout + res.stderr).strip())
        return None
    sdir = find_samples(problem_id)
    if not sdir:
        return None
    return iter_cases(sdir) or None


def ensure_built(bin_name: str) -> tuple[bool, str]:
    """cargo build --release を実行。戻り値: (成功?, バイナリパス or エラーメッセージ)。

    変更検知はソース内容のハッシュで行う (mtime は信用しない)。
    """
    exe = ROOT / "target" / "release" / (bin_name + (".exe" if os.name == "nt" else ""))
    hash_file = ROOT / "target" / f"{bin_name}_src_hash.txt"

    src = BIN_DIR / f"{bin_name}.rs"
    if not src.exists():
        src = MAIN_RS
    cur_hash = hashlib.sha256(src.read_bytes()).hexdigest() if src.exists() else ""
    prev_hash = hash_file.read_text(encoding="utf-8").strip() if hash_file.exists() else ""

    need_build = not exe.exists() or cur_hash != prev_hash

    if need_build:
        # src/bin/<id>.rs は Cargo の自動検出でビルドされる (cargo build --bin <id>)
        bin_flag = bin_name if (BIN_DIR / f"{bin_name}.rs").exists() else ""
        cmd = ["cargo", "build", "--release", "--quiet"]
        if bin_flag:
            cmd += ["--bin", bin_flag]
        res = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if res.returncode != 0:
            return False, (res.stderr or res.stdout or "").strip() or "cargo build 失敗"
        hash_file.parent.mkdir(exist_ok=True)
        hash_file.write_text(cur_hash, encoding="utf-8")

    return True, str(exe)


def main() -> int:
    parser = argparse.ArgumentParser(description="AtCoder サンプル照合 (Cargo)")
    parser.add_argument(
        "problem",
        nargs="?",
        default=None,
        help="問題ID (例: abc086_a)。省略時は自動検出",
    )
    parser.add_argument(
        "-c", "--cmd",
        default=None,
        help="実行コマンド (省略時: 対象 .rs をビルドして実行)",
    )
    args = parser.parse_args()

    pid, rs = resolve_problem_id(args.problem)
    if rs is None and pid:
        # ID 指定なのにファイルが無い → テンプレ生成を促す
        print(f"src/bin/{pid}.rs がありません。python gen.py {pid} で生成してください。")
        return 1
    if rs is None:
        print("src/main.rs も src/bin/*.rs も見つかりません。")
        return 1

    # コマンド決定
    if args.cmd:
        cmd = args.cmd.split()
        desc = args.cmd
    else:
        if rs == MAIN_RS:
            ok, built = ensure_built("main")
            if not ok:
                print("ビルドエラー:")
                print(built)
                return 1
            cmd = [built]
            desc = "Rust (src/main.rs)"
        else:
            # src/bin/<id>.rs → cargo build --bin <id>
            bin_name = rs.stem
            ok, built = ensure_built(bin_name)
            if not ok:
                print("ビルドエラー:")
                print(built)
                return 1
            cmd = [built]
            desc = f"Rust (src/bin/{bin_name}.rs)"

    # サンプル決定
    sdir = find_samples(pid)
    if not sdir:
        if pid:
            auto = maybe_auto_fetch(pid)
            if auto is None:
                print(f"samples/ にケースがありません。python fetch.py {pid} で取得してください。")
                return 1
            pairs = auto
        else:
            print("samples/ に in_*.txt / out_*.txt のペアがありません。")
            print("  python fetch.py <問題ID> で取得してください。")
            return 1
    else:
        pairs = iter_cases(sdir)

    if not pairs:
        print("サンプルケースがありません (samples/ を確認してください)。")
        return 1

    print(f"問題: {pid or '(不明)'}")
    print(f"言語: {desc}")
    print(f"ケース数: {len(pairs)}")
    print("-" * 60)

    n_pass = 0
    failed = 0
    for inp, out in pairs:
        expected = out.read_text(encoding="utf-8")
        try:
            start = time.perf_counter()
            res = run_command(cmd, inp.read_text(encoding="utf-8"))
            elapsed = (time.perf_counter() - start) * 1000
        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] {inp.name}  ({TIMEOUT_SEC}s 超過)")
            failed += 1
            continue

        if res.returncode != 0:
            print(f"  [RUNTIME ERROR] {inp.name} (exit {res.returncode})")
            err = (res.stderr or "").strip()
            if err:
                print(f"      stderr: {err.splitlines()[-1]}")
            failed += 1
            continue

        actual = res.stdout
        if normalize(actual) == normalize(expected):
            print(f"  [PASS] {inp.name}  ({elapsed:.0f} ms)")
            n_pass += 1
        else:
            print(f"  [FAIL] {inp.name}  ({elapsed:.0f} ms)")
            failed += 1
            inp_lines = normalize(inp.read_text(encoding="utf-8")).splitlines()
            exp_lines = normalize(expected).splitlines()
            act_lines = normalize(actual).splitlines()
            max_show = 10
            print(f"      --- 入力 ({inp.name}) ---")
            for line in inp_lines[:max_show]:
                print(f"        {line!r}")
            if len(inp_lines) > max_show:
                print(f"        ... あと {len(inp_lines) - max_show} 行")
            print(f"      --- 期待出力 ({len(exp_lines)}行) ---")
            for line in exp_lines[:max_show]:
                print(f"        {line!r}")
            if len(exp_lines) > max_show:
                print(f"        ... あと {len(exp_lines) - max_show} 行")
            print(f"      --- 実際の出力 ({len(act_lines)}行) ---")
            for line in act_lines[:max_show]:
                print(f"        {line!r}")
            if len(act_lines) > max_show:
                print(f"        ... あと {len(act_lines) - max_show} 行")

            for idx, (e, a) in enumerate(zip(exp_lines, act_lines)):
                if e != a:
                    print(f"      ! 最初の差分: {idx + 1}行目")
                    print(f"          期待: {e!r}")
                    print(f"          実際: {a!r}")
                    break
            else:
                if len(exp_lines) != len(act_lines):
                    print(f"      ! 行数が異なる: 期待 {len(exp_lines)} 行 / 実際 {len(act_lines)} 行")

    print("-" * 60)
    if failed == 0:
        print(f"ALL PASS ({n_pass}/{len(pairs)})")
        return 0
    print(f"{n_pass} PASS / {failed} FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
