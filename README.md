# inf_daken_counter_2_inf_notebook

inf_daken_counter の保存データ（`alllog.pkl`）を inf_notebook の JSON 形式に変換・移行するスクリプトです。

## 概要

- **入力**: inf_daken_counter が生成する `alllog.pkl`
- **出力**: inf_notebook の `records/` ディレクトリ形式（曲別 JSON + `summary.json`）
- 移行先に既存データがある場合は**マージ**します（上書きしません）

## 動作要件

- Python 3.11 以上
- 標準ライブラリのみ使用（追加インストール不要）

## 使い方

```bash
python migrate.py <alllog.pkl のパス> <出力先 records ディレクトリ>
```

### 新規移行（既存データなし）

```bash
python migrate.py path/to/alllog.pkl path/to/inf_notebook/records
```

### 既存データへのマージ

出力先に既存の `records/` ディレクトリを指定するだけです。重複エントリは自動的にスキップされます。

```bash
python migrate.py path/to/alllog.pkl path/to/inf_notebook/records
```

### 実行結果の例

```
Input:  alllog.pkl
Output: records/
Loading alllog.pkl ...
  Loaded 17535 entries (0 errors)
  Unique songs: 1719
Migrating ...
Generating summary.json ...

=== Migration Report ===
  Songs processed : 1719
  Entries added   : 15983
  Entries skipped : 1552 (duplicates)
  Load errors     : 0
  summary.json    : 1792 songs
Done.
```

## 出力ファイル

| ファイル | 説明 |
|---|---|
| `records/<hex>.json` | 曲別のプレイ履歴・ベスト記録（曲名を UTF-8 hex エンコードしたファイル名） |
| `records/summary.json` | 全曲の集計データ |

`recent.json` は alllog にUI表示用の情報（プレイサイド・ランキング等）がないため生成しません。inf_notebook を通常使用すれば自動的に生成されます。

## 重複の扱い

alllog はタイムスタンプが**分精度**（例: `20231026-143200`）であるのに対し、inf_notebook は**秒精度**（例: `20231026-143218`）で記録します。同じプレイが両方に存在する場合、**同一分内のエントリを重複とみなしてスキップ**します。

## テスト

```bash
python -m unittest test_migrate -v
```

サンプルデータ（`docs/sample_data/`）を使った統合テストを含む68件のテストが実行されます。

## サンプルデータ

| パス | 説明 |
|---|---|
| `docs/sample_data/inf_daken_counter/alllog.pkl` | 移行元データのサンプル（17,535件） |
| `docs/sample_data/inf_notebook/` | 移行先データのサンプル（1,558曲） |
