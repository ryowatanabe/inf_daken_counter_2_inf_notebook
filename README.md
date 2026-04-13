# inf_daken_counter_2_inf_notebook

打鍵カウンタ (inf_daken_counter) の保存データ（`alllog.pkl`）を リザルト手帳 (inf_notebook) の JSON 形式に変換・移行するスクリプトです。

## 免責事項・注意事項

> [!WARNING]
> - このプログラムは厳密に検証されていないため、**意図せぬデータ破損が発生する可能性があります**
> - プログラムの実行前に、更新対象となる inf_notebook のデータを**必ずバックアップしてください**
> - 入力データ（`alllog.pkl`）はこのスクリプトによって変更されません（読み取り専用）
> - 移行後のデータは inf_notebook で動作確認を行ってください

## 概要

- **入力**: inf_daken_counter が生成する `alllog.pkl`（v2）または `playlog.infdc`（v3）
- **出力**: inf_notebook の `records/` ディレクトリ形式（曲別 JSON + `summary.json`）
- 移行先に既存データがある場合は**マージ**します（上書きしません）
- v2 と v3 の両方を同じ出力先に移行しても、重複エントリは自動的にスキップされます

## 動作要件

- Python 3.11 以上
- 標準ライブラリのみ使用（追加インストール不要）

## 使い方

```bash
python migrate.py <入力ファイル> <出力先 records ディレクトリ> (--musicnames <パス> | --no-musicnames)
```

`--musicnames` と `--no-musicnames` のどちらかは必須です。入力ファイルの形式は拡張子で自動判定します（`.infdc` → v3、それ以外 → v2）。

### 新規移行（v2 alllog.pkl）

```bash
python migrate.py path/to/alllog.pkl path/to/inf_notebook/records --musicnames path/to/inf_notebook/resources/musicnamechanges.res
```

### 新規移行（v3 playlog.infdc）

```bash
python migrate.py path/to/playlog.infdc path/to/inf_notebook/records --musicnames path/to/inf_notebook/resources/musicnamechanges.res
```

### 既存データへのマージ

出力先に既存の `records/` ディレクトリを指定するだけです。重複エントリは自動的にスキップされます。

```bash
python migrate.py path/to/alllog.pkl path/to/inf_notebook/records --musicnames path/to/inf_notebook/resources/musicnamechanges.res
```

### 楽曲名修正マッピング

`--musicnames` に inf_notebook の `resources/musicnamechanges.res` を指定すると、alllog に記録された旧い表記が inf_notebook の正式表記に自動的に変換されます。マッピングの内容は今後変わりうるため、**実際の利用では inf_notebook に含まれる最新のファイルを指定してください**。

```bash
# inf_notebook のファイルを指定（推奨）
python migrate.py path/to/alllog.pkl path/to/records --musicnames path/to/inf_notebook/resources/musicnamechanges.res

# 楽曲名修正なし
python migrate.py path/to/alllog.pkl path/to/records --no-musicnames
```

本リポジトリの `resources/musicnamechanges.res` はテスト用に同梱しているものであり、内容が最新でない場合があります。

### 実行結果の例

v2 (alllog.pkl):
```
Input:  alllog.pkl
Output: records/
Loading v2 (alllog.pkl) ...
  Loaded 17535 entries (0 errors, 234 excluded)
  Unique songs: 1719
Migrating ...
Generating summary.json ...

=== Migration Report ===
  Songs processed : 1719
  Entries added   : 15983
  Entries skipped : 1552 (duplicates)
  Entries excluded: 234
  Load errors     : 0
  summary.json    : 1792 songs
Done.
```

v3 (playlog.infdc):
```
Input:  playlog.infdc
Output: records/
Loading v3 (playlog.infdc) ...
  Loaded 14136 entries (0 errors, 4144 excluded)
  Unique songs: 1699
Migrating ...
Generating summary.json ...

=== Migration Report ===
  Songs processed : 1699
  Entries added   : 14124
  Entries skipped : 12 (duplicates)
  Entries excluded: 4144
  Load errors     : 0
  summary.json    : 1699 songs
Done.
```

## 出力ファイル

| ファイル | 説明 |
|---|---|
| `records/<hex>.json` | 曲別のプレイ履歴・ベスト記録（曲名を UTF-8 hex エンコードしたファイル名） |
| `records/summary.json` | 全曲の集計データ |

`recent.json` は alllog にUI表示用の情報（プレイサイド・ランキング等）がないため生成しません。inf_notebook を通常使用すれば自動的に生成されます。

## 移行対象の除外条件

以下に該当するエントリは移行対象から除外されます。

**v2 (alllog.pkl)**

| 条件 | 理由 |
|---|---|
| score が 10 未満 | 画像認識の不具合によるスコア1桁誤認識 |
| miss_count が None | 途中終了プレイ（inf_notebook では記録対象外） |

**v3 (playlog.infdc)**

| 条件 | 理由 |
|---|---|
| timestamp が 0 | v2 インポート時の日時パース失敗 |
| notes が None | ノーツ数不明（スコアレート計算不可） |
| dead が True | 途中落ち |
| bp が 99999999 | v2 の途中終了プレイ（miss_count=None）を v3 に変換したもの |
| score が 10 未満 | 画像認識の不具合によるスコア1桁誤認識 |

## 重複の扱い

alllog はタイムスタンプが**分精度**（例: `20231026-143200`）であるのに対し、inf_notebook は**秒精度**（例: `20231026-143218`）で記録します。同じプレイが両方に存在する場合、**同一分内のエントリを重複とみなしてスキップ**します。

## 楽曲名の修正

alllog に記録された楽曲名が inf_notebook の表記と異なる場合、`--musicnames` で指定したマッピングファイルにより自動的に正規化されます。マッピングの内容は inf_notebook 側で更新されることがあるため、inf_notebook に含まれる最新の `resources/musicnamechanges.res` を指定してください。

本リポジトリの `resources/musicnamechanges.res` はテスト用に同梱しているものです。

## 自己ベストの扱い

楽曲の速度変更（Hi-Speed 変更）を適用してプレイした履歴は、自己ベストの判定から除外されます。これは inf_notebook 本体と同じ挙動です。

なお、inf_daken_counter は速度変更ありのプレイを alllog に記録しないため、alllog 由来のデータに影響はありません。既存の inf_notebook データとのマージ時に効果があります。

## テスト

```bash
python -m unittest test_migrate -v
```

サンプルデータ（`docs/sample_data/`）を使った統合テストを含む153件のテストが実行されます。

## サンプルデータ

| パス | 説明 |
|---|---|
| `docs/sample_data/inf_daken_counter/alllog.pkl` | v2 移行元データのサンプル（17,535件） |
| `docs/sample_data/inf_daken_counter_v3/alllog.pkl` | v3 が v2 からインポートした alllog.pkl（v2 形式） |
| `docs/sample_data/inf_daken_counter_v3/playlog.infdc` | v3 移行元データのサンプル（18,280件: v2 インポート 18,037件 + v3 ネイティブ 243件） |
| `docs/sample_data/inf_notebook/` | 移行先データのサンプル（1,558曲） |

## ライセンス

[LICENSE](LICENSE) ファイルを参照してください。
