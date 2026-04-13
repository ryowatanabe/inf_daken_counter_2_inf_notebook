"""
inf_daken_counter の alllog.pkl を inf_notebook の JSON 形式に移行するスクリプト

Usage:
    python migrate.py <alllog.pkl> <output_records_dir> [--no-musicnames]
    python migrate.py <alllog.pkl> <output_records_dir> --musicnames <path>

既存データがある場合はマージ（重複タイムスタンプは無視）します。
recent.json は alllog に UI 情報がないため生成しません。
"""

import json
import os
import pickle
import sys
from copy import deepcopy

# スクリプトと同じリポジトリの resources/ にあるデフォルトのマッピングファイル
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MUSICNAMES_PATH = os.path.join(_SCRIPT_DIR, 'resources', 'musicnamechanges.res')


# ---------- 定数定義 ----------

CLEAR_TYPES = ('NO PLAY', 'FAILED', 'A-CLEAR', 'E-CLEAR', 'CLEAR', 'H-CLEAR', 'EXH-CLEAR', 'F-COMBO')
DJ_LEVELS = ('F', 'E', 'D', 'C', 'B', 'A', 'AA', 'AAA')

DIFFICULTY_MAP = {
    'B': 'BEGINNER',
    'N': 'NORMAL',
    'H': 'HYPER',
    'A': 'ANOTHER',
    'L': 'LEGGENDARIA',
}

# achievement 集計対象となる arrange 値
ACHIEVEMENT_FIXED_ARRANGES = (None, 'MIRROR', 'OFF/MIR', 'MIR/OFF', 'MIR/MIR')
ACHIEVEMENT_SRANDOM_ARRANGES = ('S-RANDOM', 'S-RAN/S-RAN')

ACHIEVEMENT_DEFAULT = {
    'fixed': {'clear_type': None, 'dj_level': None},
    'S-RANDOM': {'clear_type': None, 'dj_level': None},
    'ALL-SCR': {'clear_type': None, 'dj_level': None},
}


# ---------- パース関数 ----------

def parse_play_mode(mode_str: str) -> tuple[str, str]:
    """play_mode 文字列を (playtype, difficulty) に変換する。

    例: "DPH" -> ("DP", "HYPER"), "SPA" -> ("SP", "ANOTHER")
    """
    if len(mode_str) < 3:
        raise ValueError(f"Invalid play_mode: {mode_str!r}")
    playmode = mode_str[:2]  # "SP" or "DP"
    diff_code = mode_str[2]  # B / N / H / A / L
    if playmode not in ('SP', 'DP'):
        raise ValueError(f"Unknown playmode in: {mode_str!r}")
    difficulty = DIFFICULTY_MAP.get(diff_code)
    if difficulty is None:
        raise ValueError(f"Unknown difficulty code in: {mode_str!r}")
    return playmode, difficulty


def convert_timestamp(ts: str) -> str:
    """alllog のタイムスタンプを inf_notebook 形式に変換する。

    "YYYY-MM-DD-HH-MM" -> "YYYYMMDD-HHMM00"
    """
    parts = ts.split('-')
    if len(parts) != 5:
        raise ValueError(f"Invalid timestamp: {ts!r}")
    year, month, day, hour, minute = parts
    return f"{year}{month}{day}-{hour}{minute}00"


def parse_options(opts_str: str) -> dict:
    """alllog のオプション文字列を options dict に変換する。

    Returns:
        {arrange, flip, assist, battle, allscratch, regularspeed}
        (allscratch, regularspeed は alllog に情報がないため None 固定)
    """
    arrange = None
    flip = None
    assist = None
    battle = False

    tokens = [t.strip() for t in opts_str.split(',') if t.strip()]

    # BATTLE
    if 'BATTLE' in tokens:
        battle = True
        tokens.remove('BATTLE')

    # FLIP
    if 'FLIP' in tokens:
        flip = 'FLIP'
        tokens.remove('FLIP')

    # ASSIST
    for a in ('A-SCR', 'LEGACY'):
        if a in tokens:
            assist = a
            tokens.remove(a)

    # arrange（残りのトークン）
    if tokens:
        raw = tokens[0].strip()
        # "OFF" / "OFF / OFF" -> null
        if raw in ('', 'OFF', 'OFF / OFF'):
            arrange = None
        else:
            # "X / Y" -> "X/Y"（スペース除去）
            arrange = raw.replace(' ', '')

    return {
        'arrange': arrange,
        'flip': flip,
        'assist': assist,
        'battle': battle,
        'allscratch': None,
        'regularspeed': None,
    }


# ---------- エントリ正規化 ----------

def normalize_entry(raw: list) -> dict:
    """alllog のフラットリストを処理しやすい dict に変換する。

    14要素版と 15要素版（score_rate あり）の両方に対応する。
    """
    n = len(raw)
    if n == 14:
        timestamp_raw = raw[13]
        options_raw = raw[12]
        score = raw[9]
        prev_score = raw[8]
        miss_count = raw[11]
        prev_miss_count = raw[10]
    elif n == 15:
        timestamp_raw = raw[14]
        options_raw = raw[13]
        # score_rate = raw[12]  # 移行では使用しない
        score = raw[9]
        prev_score = raw[8]
        miss_count = raw[11]
        prev_miss_count = raw[10]
    else:
        raise ValueError(f"Unexpected entry length: {n}")

    playmode_str = raw[2]
    playmode, difficulty = parse_play_mode(playmode_str)
    options = parse_options(options_raw)

    # BATTLE オプションのとき playtype を "DP BATTLE" に変更
    playtype = playmode
    if options['battle']:
        playtype = 'DP BATTLE'

    timestamp = convert_timestamp(timestamp_raw)

    clear_type = raw[7]
    prev_clear_type = raw[6]  # None の場合あり

    dj_level = raw[5]
    prev_dj_level = raw[4]

    return {
        'timestamp': timestamp,
        'music': raw[1],
        'playtype': playtype,
        'difficulty': difficulty,
        'notes': raw[3],
        'clear_type': clear_type,
        'prev_clear_type': prev_clear_type,
        'dj_level': dj_level,
        'prev_dj_level': prev_dj_level,
        'score': score,
        'prev_score': prev_score,
        'miss_count': miss_count,
        'prev_miss_count': prev_miss_count,
        'options': options,
    }


# ---------- new フラグ計算 ----------

def compute_new_flags(entry: dict) -> dict:
    """prev_* フィールドとの比較で new フラグを計算する。

    Returns:
        {clear_type: bool, dj_level: bool, score: bool, miss_count: bool}
    """
    # clear_type
    prev_ct = entry['prev_clear_type'] or 'NO PLAY'
    curr_ct = entry['clear_type']
    try:
        ct_new = CLEAR_TYPES.index(curr_ct) > CLEAR_TYPES.index(prev_ct)
    except ValueError:
        ct_new = False

    # dj_level
    prev_dj = entry['prev_dj_level'] or 'F'
    curr_dj = entry['dj_level']
    try:
        dj_new = DJ_LEVELS.index(curr_dj) > DJ_LEVELS.index(prev_dj)
    except ValueError:
        dj_new = False

    # score（高いほど良い）
    prev_score = entry['prev_score'] or 0
    curr_score = entry['score']
    score_new = (curr_score is not None) and (curr_score > prev_score)

    # miss_count（低いほど良い）
    prev_miss = entry['prev_miss_count']
    curr_miss = entry['miss_count']
    if curr_miss is None:
        miss_new = False
    elif prev_miss is None:
        miss_new = True
    else:
        miss_new = curr_miss < prev_miss

    return {
        'clear_type': ct_new,
        'dj_level': dj_new,
        'score': score_new,
        'miss_count': miss_new,
    }


# ---------- 履歴エントリ構築 ----------

def build_history_entry(entry: dict, new_flags: dict) -> dict:
    """history / latest に保存する dict を構築する。"""
    return {
        'clear_type': {'value': entry['clear_type'], 'new': new_flags['clear_type']},
        'dj_level': {'value': entry['dj_level'], 'new': new_flags['dj_level']},
        'score': {'value': entry['score'], 'new': new_flags['score']},
        'miss_count': {'value': entry['miss_count'], 'new': new_flags['miss_count']},
        'options': entry['options'],
        'playspeed': None,
    }


# ---------- best 更新 ----------

def update_best(best: dict, entry: dict, new_flags: dict) -> None:
    """best dict を entry の内容で更新する（破壊的）。"""
    best['latest'] = entry['timestamp']
    opts = entry['options']

    spec = {
        'clear_type': (entry['clear_type'], entry['prev_clear_type']),
        'dj_level': (entry['dj_level'], entry['prev_dj_level']),
        'score': (entry['score'], entry['prev_score']),
        'miss_count': (entry['miss_count'], entry['prev_miss_count']),
    }

    for key, (current, prev) in spec.items():
        if new_flags[key]:
            best[key] = {
                'value': current,
                'timestamp': entry['timestamp'],
                'options': opts,
            }
        elif key not in best and prev is not None:
            # 最初のエントリで prev_* に値がある場合：タイムスタンプ不明のベスト
            best[key] = {
                'value': prev,
                'timestamp': None,
                'options': None,
            }


# ---------- achievement 生成 ----------

def generate_achievement(target: dict) -> dict:
    """history 全体から achievement を再計算する。

    record.py:282 の generate_achievement_from_histories に相当。
    """
    achievement = deepcopy(ACHIEVEMENT_DEFAULT)
    notes = target.get('notes')

    for ts in target.get('timestamps', []):
        record = target['history'].get(ts)
        if record is None:
            continue
        opts = record.get('options')
        if opts is None:
            continue

        # どの achievement カテゴリに属するか判定
        achievement_key = None
        allscratch = opts.get('allscratch')
        if allscratch:
            achievement_key = 'ALL-SCR'
        else:
            arrange = opts.get('arrange')
            if arrange in ACHIEVEMENT_FIXED_ARRANGES:
                achievement_key = 'fixed'
            elif arrange in ACHIEVEMENT_SRANDOM_ARRANGES:
                achievement_key = 'S-RANDOM'

        if achievement_key is None:
            continue

        ach = achievement[achievement_key]

        # MAX チェック
        score_val = record.get('score', {}).get('value')
        if 'MAX' not in ach and notes is not None and score_val == notes * 2:
            ach['MAX'] = True

        # F-COMBO & AAA チェック
        ct_val = record.get('clear_type', {}).get('value')
        dj_val = record.get('dj_level', {}).get('value')
        if 'F-COMBO & AAA' not in ach and ct_val == 'F-COMBO' and dj_val == 'AAA':
            ach['F-COMBO & AAA'] = True

        # clear_type / dj_level の最高値を記録
        for field, valuelist in [('clear_type', CLEAR_TYPES), ('dj_level', DJ_LEVELS)]:
            val = record.get(field, {}).get('value')
            if val is None:
                continue
            try:
                idx_current = valuelist.index(val)
            except ValueError:
                continue
            current_best = ach.get(field)
            if current_best is None:
                ach[field] = val
            else:
                try:
                    idx_best = valuelist.index(current_best)
                    if idx_current > idx_best:
                        ach[field] = val
                except ValueError:
                    ach[field] = val

    achievement['fromhistoriesgenerate_lastversion'] = '0.0.0'
    return achievement


# ---------- 曲別 JSON マージ処理 ----------

def music_filename(music_name: str) -> str:
    """曲名を inf_notebook のファイル名（hex エンコード）に変換する。"""
    return music_name.encode('utf-8').hex() + '.json'


def load_music_json(records_dir: str, music_name: str) -> dict:
    """既存の曲別 JSON を読み込む。存在しなければ空 dict を返す。"""
    path = os.path.join(records_dir, music_filename(music_name))
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_music_json(records_dir: str, music_name: str, data: dict) -> None:
    """曲別 JSON を保存する（アトミック書き込み）。"""
    path = os.path.join(records_dir, music_filename(music_name))
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    os.replace(tmp_path, path)


def _ts_minute_prefix(ts: str) -> str:
    """タイムスタンプから分単位プレフィックスを返す。

    "20251225-234500" -> "20251225-2345"
    """
    return ts[:13]


def merge_entries_into_music(music_json: dict, entries: list[dict]) -> tuple[int, int]:
    """指定曲のエントリ群を music_json にマージする。

    重複チェック:
    - 完全一致のタイムスタンプはスキップ
    - alllog は分精度（末尾 "00" 秒）のため、同一分内に既存エントリがある場合もスキップ
      （inf_notebook が秒精度で記録済みの同一プレイを二重登録しない）

    マージ後に best と achievement を全履歴から再計算する。

    Returns:
        (added_count, skipped_count)
    """
    added = 0
    skipped = 0

    for entry in entries:
        playtype = entry['playtype']
        difficulty = entry['difficulty']
        ts = entry['timestamp']

        # JSON ツリーを構築
        if playtype not in music_json:
            music_json[playtype] = {}
        if difficulty not in music_json[playtype]:
            music_json[playtype][difficulty] = {
                'notes': entry['notes'],
                'timestamps': [],
                'history': {},
                'best': {},
            }

        target = music_json[playtype][difficulty]

        # notes は常に最新値で更新
        target['notes'] = entry['notes']

        # 重複チェック（完全一致）
        if ts in target.get('history', {}):
            skipped += 1
            continue
        if ts in target.get('timestamps', []):
            skipped += 1
            continue

        # 重複チェック（同一分内 - alllog は分精度のため既存秒精度と照合）
        ts_prefix = _ts_minute_prefix(ts)
        minute_dup = any(
            _ts_minute_prefix(existing_ts) == ts_prefix
            for existing_ts in target.get('timestamps', [])
        )
        if minute_dup:
            skipped += 1
            continue

        # 履歴追加
        new_flags = compute_new_flags(entry)
        hist_entry = build_history_entry(entry, new_flags)

        if 'timestamps' not in target:
            target['timestamps'] = []
        if 'history' not in target:
            target['history'] = {}

        target['timestamps'].append(ts)
        target['history'][ts] = hist_entry
        added += 1

    # マージ後に各譜面の best / achievement / latest を再計算
    for playtype, diffs in music_json.items():
        for difficulty, target in diffs.items():
            if not target.get('timestamps'):
                continue

            # タイムスタンプを昇順ソート
            target['timestamps'].sort()

            # best を全履歴から再計算
            # 速度変更ありのプレイ (playspeed != None) は best 判定から除外する
            # (inf_notebook も playspeed is None の場合のみ best を更新する)
            best: dict = {}
            for ts in target['timestamps']:
                hist = target['history'].get(ts)
                if hist is None:
                    continue
                if hist.get('playspeed') is not None:
                    continue
                best['latest'] = ts
                opts = hist.get('options')
                spec = {
                    'clear_type': (hist.get('clear_type', {}).get('value'), None),
                    'dj_level': (hist.get('dj_level', {}).get('value'), None),
                    'score': (hist.get('score', {}).get('value'), None),
                    'miss_count': (hist.get('miss_count', {}).get('value'), None),
                }
                _update_best_from_history(best, ts, spec, opts)
            target['best'] = best

            # latest を更新
            last_ts = target['timestamps'][-1]
            last_hist = target['history'][last_ts]
            target['latest'] = {
                'timestamp': last_ts,
                **last_hist,
            }

            # achievement を再生成
            target['achievement'] = generate_achievement(target)

    return added, skipped


def _update_best_from_history(best: dict, ts: str, spec: dict, opts: dict | None) -> None:
    """best dict を全履歴を辿って更新する内部関数。"""
    metric_order = {
        'clear_type': CLEAR_TYPES,
        'dj_level': DJ_LEVELS,
    }

    for key, (current_val, _) in spec.items():
        if current_val is None:
            continue

        order = metric_order.get(key)
        if key not in best:
            best[key] = {
                'value': current_val,
                'timestamp': ts,
                'options': opts,
            }
        else:
            existing = best[key]['value']
            if order is not None:
                try:
                    is_better = order.index(current_val) > order.index(existing)
                except ValueError:
                    is_better = False
            elif key == 'score':
                is_better = (isinstance(current_val, (int, float)) and
                             isinstance(existing, (int, float)) and
                             current_val > existing)
            elif key == 'miss_count':
                is_better = (isinstance(current_val, (int, float)) and
                             isinstance(existing, (int, float)) and
                             current_val < existing)
            else:
                is_better = False

            if is_better:
                best[key] = {
                    'value': current_val,
                    'timestamp': ts,
                    'options': opts,
                }


# ---------- summary.json 生成 ----------

def generate_summary(records_dir: str) -> dict:
    """records/ 以下の全 JSON ファイルを走査して summary.json を生成する。"""
    summary = {
        'last_allimported': 'migration',
        'musics': {},
    }

    for fname in sorted(os.listdir(records_dir)):
        if not fname.endswith('.json'):
            continue
        if fname in ('recent.json', 'summary.json'):
            continue

        hex_name = fname[:-5]
        try:
            music_name = bytes.fromhex(hex_name).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            continue

        path = os.path.join(records_dir, fname)
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        # NotebookSummary と同様に SP / DP / DP BATTLE を必ず初期化する。
        # notesradar.py は SP・DP キーの存在を前提にアクセスするため、
        # データのないプレイタイプも空 dict として存在しなければならない。
        music_summary: dict = {'SP': {}, 'DP': {}, 'DP BATTLE': {}}
        for playtype, diffs in data.items():
            pt_summary: dict = {}
            for difficulty, target in diffs.items():
                timestamps = target.get('timestamps', [])
                best = target.get('best', {})
                achievement = target.get('achievement')

                def _best_entry(key_in_best: str) -> dict | None:
                    val = best.get(key_in_best)
                    if val is None:
                        return None
                    return {
                        'value': val.get('value'),
                        'timestamp': val.get('timestamp'),
                        'options': val.get('options'),
                    }

                pt_summary[difficulty] = {
                    'latest': timestamps[-1] if timestamps else None,
                    'playcount': len(timestamps),
                    'best': {
                        'cleartype': _best_entry('clear_type'),
                        'djlevel': _best_entry('dj_level'),
                        'score': _best_entry('score'),
                        'misscount': _best_entry('miss_count'),
                    },
                    'achievement': achievement,
                }

            if pt_summary:
                music_summary[playtype] = pt_summary

        summary['musics'][music_name] = music_summary

    return summary


# ---------- 楽曲名修正マッピング ----------

def load_musicname_changes(path: str) -> dict[str, str]:
    """musicnamechanges.res を読み込み、旧名→新名の dict を返す。

    ファイルが存在しない場合や解析失敗の場合は空 dict を返す。
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return {old: new for old, new in data}
    except (json.JSONDecodeError, ValueError, OSError):
        return {}


# ---------- alllog.pkl 読み込み ----------

def should_exclude(entry: dict) -> str | None:
    """移行対象から除外すべきエントリの理由を返す。対象外なら None。

    除外条件:
    - score が 10 未満: 画像認識の不具合によるスコア1桁誤認識
    - miss_count が None: 途中終了プレイ（inf_notebook では記録対象外）
    """
    if entry['score'] is not None and entry['score'] < 10:
        return f"score too low ({entry['score']})"
    if entry['miss_count'] is None:
        return "miss_count is None (interrupted play)"
    return None


def load_alllog(pkl_path: str, musicname_changes: dict[str, str] | None = None) -> list[dict]:
    """alllog.pkl を読み込み、正規化・フィルタ済みの dict リストを返す（タイムスタンプ昇順）。

    Args:
        pkl_path: alllog.pkl のパス
        musicname_changes: 旧楽曲名→新楽曲名のマッピング dict（None の場合は適用しない）

    Returns:
        (entries, parse_errors, excluded_count, renamed_count)
    """
    with open(pkl_path, 'rb') as f:
        raw_list = pickle.load(f)

    entries = []
    errors = 0
    excluded = 0
    renamed = 0
    for i, raw in enumerate(raw_list):
        try:
            entry = normalize_entry(raw)
        except Exception as e:
            print(f"  [WARN] Entry {i} skipped: {e}", file=sys.stderr)
            errors += 1
            continue

        # 楽曲名修正マッピングを適用
        if musicname_changes:
            old_name = entry['music']
            new_name = musicname_changes.get(old_name)
            if new_name is not None:
                entry['music'] = new_name
                renamed += 1

        reason = should_exclude(entry)
        if reason:
            excluded += 1
            continue

        entries.append(entry)

    entries.sort(key=lambda e: e['timestamp'])
    return entries, errors, excluded, renamed


# ---------- メイン処理 ----------

def main(alllog_path: str, output_dir: str, musicnames_path: str | None = DEFAULT_MUSICNAMES_PATH) -> None:
    """
    Args:
        alllog_path: alllog.pkl のパス
        output_dir: 出力先 records ディレクトリ
        musicnames_path: musicnamechanges.res のパス。None の場合は楽曲名修正を行わない。
    """
    print(f"Input:  {alllog_path}")
    print(f"Output: {output_dir}")

    os.makedirs(output_dir, exist_ok=True)

    # 楽曲名修正マッピングを読み込む
    musicname_changes: dict[str, str] | None = None
    if musicnames_path is not None:
        musicname_changes = load_musicname_changes(musicnames_path)
        if musicname_changes:
            print(f"Music name changes: {len(musicname_changes)} entries loaded from {musicnames_path}")

    # 1. alllog.pkl 読み込み
    print("Loading alllog.pkl ...")
    entries, load_errors, excluded, renamed = load_alllog(alllog_path, musicname_changes)
    print(f"  Loaded {len(entries)} entries ({load_errors} errors, {excluded} excluded)")
    if renamed > 0:
        print(f"  Music names renamed: {renamed}")

    # 2. 曲別にグループ化
    music_entries: dict[str, list[dict]] = {}
    for entry in entries:
        key = entry['music']
        if key not in music_entries:
            music_entries[key] = []
        music_entries[key].append(entry)

    print(f"  Unique songs: {len(music_entries)}")

    # 3. 曲別 JSON に書き込み（マージ）
    total_added = 0
    total_skipped = 0
    total_songs = 0
    print("Migrating ...")

    for music_name, ents in music_entries.items():
        music_json = load_music_json(output_dir, music_name)
        added, skipped = merge_entries_into_music(music_json, ents)
        save_music_json(output_dir, music_name, music_json)
        total_added += added
        total_skipped += skipped
        total_songs += 1

    # 4. summary.json 生成
    print("Generating summary.json ...")
    summary = generate_summary(output_dir)
    summary_path = os.path.join(output_dir, 'summary.json')
    tmp_summary = summary_path + '.tmp'
    with open(tmp_summary, 'w', encoding='utf-8') as f:
        json.dump(summary, f)
    os.replace(tmp_summary, summary_path)

    print()
    print("=== Migration Report ===")
    print(f"  Songs processed : {total_songs}")
    print(f"  Entries added   : {total_added}")
    print(f"  Entries skipped : {total_skipped} (duplicates)")
    print(f"  Entries excluded: {excluded} (score<10 or miss_count=None)")
    if renamed > 0:
        print(f"  Names renamed   : {renamed}")
    print(f"  Load errors     : {load_errors}")
    print(f"  summary.json    : {len(summary['musics'])} songs")
    print("Done.")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='inf_daken_counter の alllog.pkl を inf_notebook の JSON 形式に移行する'
    )
    parser.add_argument('alllog_pkl', help='alllog.pkl のパス')
    parser.add_argument('output_records_dir', help='出力先 records ディレクトリ')

    musicnames_group = parser.add_mutually_exclusive_group(required=True)
    musicnames_group.add_argument(
        '--musicnames',
        metavar='PATH',
        default=None,
        help='musicnamechanges.res のパス（リポジトリ同梱: resources/musicnamechanges.res）',
    )
    musicnames_group.add_argument(
        '--no-musicnames',
        action='store_true',
        help='楽曲名修正マッピングを適用しない',
    )

    args = parser.parse_args()

    if args.no_musicnames:
        musicnames_path = None
    elif args.musicnames:
        musicnames_path = args.musicnames
    else:
        musicnames_path = DEFAULT_MUSICNAMES_PATH

    main(args.alllog_pkl, args.output_records_dir, musicnames_path)
