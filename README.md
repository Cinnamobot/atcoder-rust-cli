# AtCoder Rust CLI ツール

AtCoder の問題をローカルの **VSCode** で解くための CLI ツール群。
`src/bin/<問題ID>.rs` を新規作成した瞬間に、**問題文コメント＋入力テンプレート＋
サンプル入出力が全部自動生成**され、保存すると**自動でサンプル照合**が走る。

提出は手動（ブラウザでコピペ）。Cloudflare Turnstile があるため自動提出はしない方針。

## できること

| 機能 | 説明 |
|---|---|
| **テンプレ自動生成** | `gen.py abc086_a` で問題文コメント + `input!` テンプレ + サンプルを一括生成 |
| **サンプル取得** | `fetch.py` が問題ページからサンプル入出力を自動スクレイピング |
| **自動照合** | `check.py` がローカルの Rust コードをビルド・実行し、サンプルと照合 |
| **VSCode 連携** | ファイル作成→自動生成、保存→自動照合（File Watcher 拡張） |

## クイックスタート

```bash
# 1. 依存
#    Python 3.10+ (標準ライブラリのみ) / Rust (cargo)

# 2. 問題のテンプレートを生成
python gen.py abc086_a
# → src/bin/abc086_a.rs に問題文コメント + 入力テンプレート + samples/abc086_a/ が生成される

# 3. 解答を書いて照合
python check.py abc086_a
# → cargo build → サンプルと照合 → PASS/FAIL 表示
```

### VSCode で完全自動化

1. `code --install-extension appulate.filewatcher`（File & Folder Watcher）
2. プロジェクトをワークスペースとして開く（`.vscode/settings.json` が有効になる）
3. `src/bin/abc123_a.rs` を新規作成 → 自動で問題文＋テンプレ＋サンプル生成
4. 解答を書いて保存 → 自動でサンプル照合

## コマンド一覧

| コマンド | 動作 |
|---|---|
| `python gen.py abc086_a` | `src/bin/abc086_a.rs` 生成 (問題文+テンプレート+サンプル) |
| `python gen.py src/bin/abc086_a.rs` | ファイルパス指定で生成 (冪等: 最新なら何もしない) |
| `python gen.py --all` | `src/bin/` の全 `.rs` のヘッダ+サンプルを更新 |
| `python check.py` | サンプル照合 (対象を自動検出) |
| `python check.py abc086_a` | 問題ID指定で照合 |
| `python check.py src/bin/abc086_a.rs` | ファイルパス指定で照合 |
| `python check.py -c "cargo run"` | 任意コマンドで照合 (言語切替) |
| `python fetch.py abc086_a` | サンプル+問題文の取得だけ |
| `python split_samples.py` | スクレイピング不可時のフォールバック (コピペ→problem.txt) |

## ディレクトリ構成

```
src/bin/abc086_a.rs      # 解答 (ヘッダに問題文コメントが自動生成される)
samples/abc086_a/        # 問題ごとのサンプル in_N.txt / out_N.txt (自動生成)
.vscode/settings.json    # File Watcher 設定 (このフォルダを開いたときだけ有効)
check.py                 # 照合スクリプト
fetch.py                 # スクレイピング (サンプル+問題文)
gen.py                   # テンプレート自動生成 (ファイルパス/ID/監視に対応)
split_samples.py         # コピペ方式のフォールバック
```

`src/bin/<id>.rs` は Cargo のマルチバイナリなので `cargo run --bin abc086_a` も使える。

## 仕組み

1. `gen.py` が問題ID を `// problem:` 行 or ファイル名から解決
2. `fetch.py` が問題ページを取得:
   - `<pre>` からサンプル入出力 → `samples/<id>/` に保存 + ヘッダコメントにも記載
   - `<h3>` セクション (問題文/制約/入力/出力) → ヘッダコメント
   - `<var>` タグから変数名 → `input!` テンプレート (型はサンプル入力から推定)
3. `check.py` が `cargo build --release` → バイナリ実行 → 出力を正規化して照合

`gen.py` は冪等: ヘッダが既に最新なら書き換えない（ファイルウォッチャーとの無限ループ防止）。

照合の正規化: 行ごとの末尾空白除去 + 空行除去 (AtCoder 判定に準拠)。

## テンプレートの型推定ルール

`input!` テンプレートは問題文の `<var>` タグとサンプル入力から自動生成する:

| 入力パターン | 生成される型 | 例 |
|---|---|---|
| スカラー (数字) | `i64` | `n: i64,` |
| スカラー (文字列) | `String` | `s: String,` |
| 単一配列 `C_1 ... C_N` (長さ判明) | `[i64; n]` | `c: [i64; n],` |
| 単一配列 (長さ不明) | `Vec<i64>` | `c: Vec<i64>,` |
| 行分離 `A_1...A_N` / `B_1...B_N` (別行) | `a: [i64; n], b: [i64; n]` | — |
| 交互ペア `a_1 b_1 / a_2 b_2` (N 行) | `ab: [(i64, i64); n]` | — |
| 複数配列で構造不明 | TODO コメント | — |

- 添字付き変数 (`C_1, C_2, ..., C_N`) は 1 つの配列に畳み込む
- 型はサンプル入力のトークンが数字かどうかで判定 (数字のみ → `i64`)
- **行分離** (配列ごとに別行) は `a: [i64; n], b: [i64; n]` と個別の配列に分ける
- **交互ペア** (a_1 b_1 が N 行) は proconio が `Vec<(T,U)>` を読めない
  (Readable 未実装) ため `[(T,U); n]` のタプル配列に統合する

## Turnstile / 提出について

- 問題ページの取得・サンプルスクレイピングは**ログイン不要**で通常動く
- Cloudflare Turnstile はログイン/提出側にあるため、**提出は手動** (ブラウザでコピペ)
- スクレイピングが 403 等でブロックされたら、ブラウザで問題ページを開いて
  本文をコピー → `problem.txt` に貼り付け → `python split_samples.py`

## 依存

- Python 3.10+ (標準ライブラリのみ、追加インストール不要)
- Rust (rustc / cargo)
- proconio 0.4.5 (Cargo.toml 記載済み。AtCoder の Rust 提出環境に合わせた構成)
- VSCode + File & Folder Watcher 拡張 (自動化を使う場合)

## 免責

本ツールは学習・個人利用を目的としています。AtCoder の利用規約を尊重し、
サーバーに過剰な負荷をかけないようご利用ください。
