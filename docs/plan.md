# inf_daken_counter → inf_notebook データ移行プラン

## Context

inf_daken_counter の保存データ（`alllog.pkl`）を inf_notebook のJSON形式に変換・移行するスタンドアロンスクリプトを作成する。移行先に既存データがある場合はマージする必要がある。

## 方針: スタンドアロンスクリプト

両アプリのコードは GUI・OCR・numpy 等の重い依存関係を持つため、直接 import せずに必要なロジックのみをスクリプト内に再実装する。

## 入力データ: alllog.pkl

pickle形式のリスト。各エントリは14要素または15要素のフラットリスト。

**14要素版** (旧データ):
| Index | Field | 型 |
|-------|-------|-----|
| 0 | level | str |
| 1 | music | str |
| 2 | play_mode | str ("DPH","SPA"等) |
| 3 | notes | int |
| 4 | prev_dj_level | str |
| 5 | dj_level | str |
| 6 | prev_clear_type | str/None |
| 7 | clear_type | str |
| 8 | prev_score | int |
| 9 | score | int |
| 10 | prev_miss_count | int/None |
| 11 | miss_count | int/None |
| 12 | options | str |
| 13 | timestamp | str "YYYY-MM-DD-HH-MM" |

**15要素版** (新データ): index 12 に score_rate が追加、options→13, timestamp→14

## 出力データ: inf_notebook JSON

### 曲別ファイル (`records/<hex名>.json`)
```json
{
  "<playtype>": {
    "<difficulty>": {
      "notes": int,
      "latest": { "timestamp", "clear_type": {"value","new"}, ... , "options": {...}, "playspeed": null },
      "timestamps": [...],
      "history": { "<ts>": { ... } },
      "best": { "latest", "clear_type": {"value","timestamp","options"}, ... },
      "achievement": { "fixed": {...}, "S-RANDOM": {...}, "ALL-SCR": {...} }
    }
  }
}
```

### summary.json
全曲の要約データ。曲別ファイルから生成。

### recent.json
alllog にはplay_side/tab/rankposition等のUI情報がないため、**生成しない**。

## 変換処理の詳細

### 1. alllog.pkl 読み込み・正規化
- pickle.load でリスト読み込み
- 14/15要素を判定し、統一dict形式に変換
- タイムスタンプで昇順ソート

### 2. play_mode パース
- 先頭2文字 → playtype: "SP" or "DP"
- 末尾1文字 → difficulty: B=BEGINNER, N=NORMAL, H=HYPER, A=ANOTHER, L=LEGGENDARIA
- BATTLE判定: options文字列に "BATTLE" を含む場合 → playtype を "DP BATTLE" に変更

### 3. タイムスタンプ変換
- `"YYYY-MM-DD-HH-MM"` → `"YYYYMMDD-HHMM00"` (秒は"00"固定)

### 4. オプション文字列パース
入力例と変換結果:
| 入力 | arrange | flip | assist | battle |
|------|---------|------|--------|--------|
| `""` / `"OFF"` / `"OFF / OFF"` | null | null | null | false |
| `"MIRROR"` | "MIRROR" | null | null | false |
| `"MIR / OFF"` | "MIR/OFF" | null | null | false |
| `"MIR / OFF, FLIP"` | "MIR/OFF" | "FLIP" | null | false |
| `"S-RAN / S-RAN"` | "S-RAN/S-RAN" | null | null | false |
| `"BATTLE, MIR / OFF"` | "MIR/OFF" | null | null | true |
| `"OFF / OFF, A-SCR"` | null | null | "A-SCR" | false |
| `"OFF / OFF, LEGACY"` | null | null | "LEGACY" | false |

アルゴリズム:
1. `", "` で分割
2. "BATTLE" トークンを検出・除去 → battle=true
3. "FLIP" トークンを検出・除去 → flip
4. "A-SCR"/"LEGACY" トークンを検出・除去 → assist
5. 残りのトークン（arrange部分）: "OFF" / "OFF / OFF" → null、それ以外 → スペース除去して格納
6. allscratch, regularspeed は alllog に情報がないため null 固定

### 5. "new" フラグ計算
alllog の prev_* フィールドから直接計算:
- **clear_type.new**: `clear_types.index(current) > clear_types.index(prev)` (prev=None → "NO PLAY" 扱い)
- **dj_level.new**: `dj_levels.index(current) > dj_levels.index(prev)`
- **score.new**: `score > prev_score`
- **miss_count.new**: `miss_count < prev_miss_count` (低い方が良い), prev=None かつ current!=None → true

### 6. best 構築
エントリを時系列順に処理し、new=true のものがあれば best を更新:
```python
best[key] = {"value": current_value, "timestamp": ts, "options": options_dict}
```
初回（既存bestなし）で prev_* 値がある場合: `{"value": prev_value, "timestamp": null, "options": null}` をセット。

速度変更ありのプレイ (`playspeed != null`) は best 判定から除外する。  
（inf_notebook と同じ挙動。alllog は速度変更ありのプレイを記録しないため alllog 由来のエントリへの影響はないが、既存の inf_notebook データとのマージ時に必要。）

### 7. achievement 生成
`record.py:282` の `generate_achievement_from_histories` ロジックを再実装:
- **fixed**: arrange が `(None, 'MIRROR', 'OFF/MIR', 'MIR/OFF', 'MIR/MIR')` のいずれか
- **S-RANDOM**: arrange が `('S-RANDOM', 'S-RAN/S-RAN')` のいずれか
- **ALL-SCR**: allscratch=true の場合（alllog からは判定不可のため基本スキップ）
- 各カテゴリで clear_type, dj_level の最高値を記録
- MAX: score == notes * 2
- F-COMBO & AAA: clear_type="F-COMBO" かつ dj_level="AAA"

### 8. 移行対象の除外条件
以下に該当するエントリは移行対象から除外する:
- **score が 10 未満**: 画像認識の不具合によるスコア1桁誤認識
- **miss_count が None**: 途中終了プレイ（inf_notebook では記録対象外）

### 9. 既存データとのマージ
1. 出力先に既存JSONがあれば読み込み
2. 既存の timestamps セットを取得
3. 新エントリのうち、タイムスタンプが重複しないもののみ追加
   - 完全一致だけでなく、**同一分内**（alllog の分精度 vs inf_notebook の秒精度）も重複とみなす
4. 全エントリ（既存+新規）をタイムスタンプ順にソートし直す
5. best を全履歴から再計算（マージ後の整合性を保証）
6. achievement を全履歴から再生成
7. latest を最新のエントリに設定

### 10. summary.json 生成
全曲別ファイルを走査し、`record.py:522` の NotebookSummary 形式で集約:
```json
{
  "last_allimported": "migration",
  "musics": {
    "<曲名>": {
      "<playtype>": {
        "<difficulty>": {
          "latest": "<ts>", "playcount": N,
          "best": { "cleartype": {...}, "djlevel": {...}, "score": {...}, "misscount": {...} },
          "achievement": {...}
        }
      }
    }
  }
}
```
注意: summary では `clear_type` → `cleartype`, `dj_level` → `djlevel`, `miss_count` → `misscount` とキー名が異なる。

各曲のエントリは `'SP'`, `'DP'`, `'DP BATTLE'` の3キーを**必ず初期化**してから実データを埋める。`notesradar.py` が両キーの存在を前提にアクセスするため、データのないプレイタイプも空 dict として存在しなければならない。

### 11. 楽曲名修正マッピング
`load_alllog()` 内で `normalize_entry()` 後に `entry['music']` をマッピング dict で置換する。

マッピングファイル:
- **形式**: JSON 配列 `[[旧名, 新名], ...]`（inf_notebook の `resources/musicnamechanges.res` と同形式）
- **テスト用**: `resources/musicnamechanges.res` をリポジトリ内に同梱
- **実際の利用**: inf_notebook に含まれる最新ファイルを `--musicnames` で指定すること（内容は今後変わりうる）

## スクリプト構成

**ファイル**: `migrate.py`（プロジェクトルートに1ファイル）

```
定数定義 (CLEAR_TYPES, DJ_LEVELS, DIFFICULTY_MAP)
DEFAULT_MUSICNAMES_PATH: スクリプト同階層の resources/musicnamechanges.res

--- v2 (alllog.pkl) ---
parse_play_mode(mode_str) -> (playtype, difficulty)
convert_timestamp(ts) -> str
parse_options(opts_str) -> dict
normalize_entry(entry) -> dict
should_exclude(entry) -> str | None
load_alllog(pkl_path, musicname_changes=None) -> (entries, errors, excluded, renamed)

--- v3 (playlog.infdc) ---
_make_enum_stub(members) -> class
_V3Unpickler(Unpickler)
compute_dj_level(score, notes) -> str
convert_unix_timestamp(ts) -> str
convert_v3_options(option) -> dict
normalize_v3_entry(entry) -> dict
should_exclude_v3(entry) -> str | None
load_v3(infdc_path, musicname_changes=None) -> (entries, errors, excluded, renamed)
load_input(path, musicname_changes=None) -> (entries, errors, excluded, renamed)

--- 共通 ---
compute_new_flags(entry) -> dict
build_history_entry(entry) -> dict
load_musicname_changes(path) -> dict[str, str]
merge_entries_into_music(music_json, entries) -> (added, skipped)
generate_achievement(target) -> dict
generate_summary(records_dir) -> dict
main(input_path, output_dir, musicnames_path)
```

CLI:
```bash
python migrate.py <alllog.pkl|playlog.infdc> <output_records_dir> (--musicnames <パス> | --no-musicnames)
```

`--musicnames` と `--no-musicnames` のどちらかは必須。省略するとエラー。入力ファイルの形式は拡張子で自動判定（`.infdc` → v3、それ以外 → v2）。

## 主要参照ファイル
- `docs/sample_data/inf_daken_counter/alllog.pkl` - v2 入力サンプル
- `docs/sample_data/inf_daken_counter_v3/playlog.infdc` - v3 入力サンプル（18,280件）
- `docs/sample_data/inf_notebook/*.json` - 出力サンプル
- `../inf-notebook.master/record.py` - NotebookMusic (insert/best/achievement ロジック)
- `../inf-notebook.master/define.py` - 定数定義 (clear_types, dj_levels 等)
- `../inf-notebook.master/versioncheck.py` - バージョン文字列の形式
- `/mnt/c/Users/ryo/git/inf-notebook/resources/musicnamechanges.res` - 実際に動いている inf_notebook の楽曲名修正マッピング（.master より新しい場合がある）
- `../inf_daken_counter.v3/src/result.py` - OneResult, PlayOption クラス定義
- `../inf_daken_counter.v3/src/classes.py` - Enum 定義 (clear_lamp, play_style 等)
- `../inf_daken_counter.v3/src/config_dialog.py:84` - PklImportWorker（v2→v3 変換ロジック）

## 既知の問題と対応（実装済み）

### `fromhistoriesgenerate_lastversion` のバージョン文字列

inf_notebook の `versioncheck.py` は各ドット区切りセグメントから `re.search(r'\d+', ...)` で数字を抽出するため、数字を含まない文字列では `AttributeError` が発生する。

移行スクリプトでは `'0.0.0'` を設定する。これにより inf_notebook が曲データ読込時に achievement を最新ロジックで自動再生成する。

### summary.json のプレイタイプキー欠落による KeyError

`notesradar.py:107` が `summary[musicname][playmode]` にキー存在チェックなしでアクセスするため、SP/DP どちらか一方のデータしかない曲で `KeyError` が発生する。

`generate_summary()` で各曲のエントリを構築する際、`'SP'`, `'DP'`, `'DP BATTLE'` の3キーを常に初期化してから実データを埋めることで対応。

### JSON エンコード形式

inf_notebook は `json.dump(data, f)` を引数なしで呼び出している（`record.py:54`）。移行スクリプトも同じ形式に揃える。

## 検証方法

```bash
python -m unittest test_migrate -v  # 153件
```

1. **v2 ユニットテスト** (`test_migrate.py`):
   - parse_play_mode, convert_timestamp, parse_options の各パターン
   - new フラグ計算のエッジケース
   - マージ処理の重複排除（完全一致・同一分内）
   - 除外条件（score<10, miss_count=None）
   - 速度変更ありのプレイの best 除外
   - 楽曲名修正マッピングの適用・カウント
   - summary の全プレイタイプキー存在確認

2. **v3 ユニットテスト** (`test_migrate.py`):
   - `compute_dj_level()`: 全 DJ LEVEL 境界値
   - `convert_unix_timestamp()`: フォーマット変換
   - `convert_v3_options()`: arrange 正規化（v2略称/v3フルネーム混在）
   - `normalize_v3_entry()`: OneResult → dict 変換（正常系/pre_*=None/BATTLE）
   - `should_exclude_v3()`: 全除外条件の検証
   - `load_v3()` 統合テスト: playlog.infdc 読み込み・件数・エントリ構造

3. **サンプルデータによる統合テスト**:
   - `docs/sample_data/inf_daken_counter/alllog.pkl` を入力として実行
   - `docs/sample_data/inf_daken_counter_v3/playlog.infdc` を入力として実行
   - v2 → v3 マージ（重複がスキップされ v3 ネイティブのみ追加されることを確認）

4. **移行レポート**:
   - 処理曲数、エントリ数、スキップ数、除外数、楽曲名修正数、エラー数を標準出力に表示
