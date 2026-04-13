"""
migrate.py のユニットテスト・統合テスト
"""

import json
import os
import pickle
import shutil
import tempfile
import unittest

from migrate import (
    CLEAR_TYPES,
    DJ_LEVELS,
    _ts_minute_prefix,
    build_history_entry,
    compute_new_flags,
    convert_timestamp,
    generate_achievement,
    generate_summary,
    load_alllog,
    merge_entries_into_music,
    music_filename,
    normalize_entry,
    parse_options,
    parse_play_mode,
    save_music_json,
    load_music_json,
    should_exclude,
)


class TestParsePlayMode(unittest.TestCase):
    def test_sp_another(self):
        self.assertEqual(parse_play_mode('SPA'), ('SP', 'ANOTHER'))

    def test_sp_hyper(self):
        self.assertEqual(parse_play_mode('SPH'), ('SP', 'HYPER'))

    def test_sp_normal(self):
        self.assertEqual(parse_play_mode('SPN'), ('SP', 'NORMAL'))

    def test_sp_beginner(self):
        self.assertEqual(parse_play_mode('SPB'), ('SP', 'BEGINNER'))

    def test_sp_leggendaria(self):
        self.assertEqual(parse_play_mode('SPL'), ('SP', 'LEGGENDARIA'))

    def test_dp_another(self):
        self.assertEqual(parse_play_mode('DPA'), ('DP', 'ANOTHER'))

    def test_dp_hyper(self):
        self.assertEqual(parse_play_mode('DPH'), ('DP', 'HYPER'))

    def test_dp_normal(self):
        self.assertEqual(parse_play_mode('DPN'), ('DP', 'NORMAL'))

    def test_dp_leggendaria(self):
        self.assertEqual(parse_play_mode('DPL'), ('DP', 'LEGGENDARIA'))

    def test_invalid_playmode(self):
        with self.assertRaises(ValueError):
            parse_play_mode('XXH')

    def test_invalid_difficulty(self):
        with self.assertRaises(ValueError):
            parse_play_mode('SPX')

    def test_too_short(self):
        with self.assertRaises(ValueError):
            parse_play_mode('SP')


class TestConvertTimestamp(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(convert_timestamp('2023-06-26-23-14'), '20230626-231400')

    def test_zero_padding(self):
        self.assertEqual(convert_timestamp('2024-01-01-00-00'), '20240101-000000')

    def test_midnight(self):
        self.assertEqual(convert_timestamp('2025-12-31-23-59'), '20251231-235900')

    def test_invalid(self):
        with self.assertRaises(ValueError):
            convert_timestamp('2023-06-26')


class TestParseOptions(unittest.TestCase):
    def _opts(self, s):
        return parse_options(s)

    def test_empty_string(self):
        o = self._opts('')
        self.assertIsNone(o['arrange'])
        self.assertIsNone(o['flip'])
        self.assertIsNone(o['assist'])
        self.assertFalse(o['battle'])

    def test_off(self):
        o = self._opts('OFF')
        self.assertIsNone(o['arrange'])

    def test_off_slash_off(self):
        o = self._opts('OFF / OFF')
        self.assertIsNone(o['arrange'])

    def test_mirror_sp(self):
        o = self._opts('MIRROR')
        self.assertEqual(o['arrange'], 'MIRROR')
        self.assertIsNone(o['flip'])

    def test_mir_off(self):
        o = self._opts('MIR / OFF')
        self.assertEqual(o['arrange'], 'MIR/OFF')
        self.assertIsNone(o['flip'])

    def test_mir_off_flip(self):
        o = self._opts('MIR / OFF, FLIP')
        self.assertEqual(o['arrange'], 'MIR/OFF')
        self.assertEqual(o['flip'], 'FLIP')

    def test_s_ran_s_ran(self):
        o = self._opts('S-RAN / S-RAN')
        self.assertEqual(o['arrange'], 'S-RAN/S-RAN')

    def test_ran_ran_flip(self):
        o = self._opts('RAN / RAN, FLIP')
        self.assertEqual(o['arrange'], 'RAN/RAN')
        self.assertEqual(o['flip'], 'FLIP')

    def test_battle(self):
        o = self._opts('BATTLE, MIR / OFF')
        self.assertTrue(o['battle'])
        self.assertEqual(o['arrange'], 'MIR/OFF')

    def test_battle_ascr(self):
        o = self._opts('BATTLE, MIR / OFF, A-SCR')
        self.assertTrue(o['battle'])
        self.assertEqual(o['arrange'], 'MIR/OFF')
        self.assertEqual(o['assist'], 'A-SCR')

    def test_legacy(self):
        o = self._opts('OFF / OFF, LEGACY')
        self.assertIsNone(o['arrange'])
        self.assertEqual(o['assist'], 'LEGACY')

    def test_off_mir(self):
        o = self._opts('OFF / MIR')
        self.assertEqual(o['arrange'], 'OFF/MIR')

    def test_allscratch_always_none(self):
        # alllog には allscratch 情報がないため常に None
        o = self._opts('OFF / OFF')
        self.assertIsNone(o['allscratch'])
        self.assertIsNone(o['regularspeed'])

    def test_battle_symm_ran(self):
        o = self._opts('BATTLE, SYMM-RAN, A-SCR')
        self.assertTrue(o['battle'])
        self.assertEqual(o['arrange'], 'SYMM-RAN')
        self.assertEqual(o['assist'], 'A-SCR')


class TestComputeNewFlags(unittest.TestCase):
    def _make_entry(self, **kwargs):
        base = {
            'clear_type': 'CLEAR',
            'prev_clear_type': 'CLEAR',
            'dj_level': 'A',
            'prev_dj_level': 'A',
            'score': 1000,
            'prev_score': 1000,
            'miss_count': 10,
            'prev_miss_count': 10,
        }
        base.update(kwargs)
        return base

    def test_clear_type_improved(self):
        entry = self._make_entry(clear_type='H-CLEAR', prev_clear_type='CLEAR')
        flags = compute_new_flags(entry)
        self.assertTrue(flags['clear_type'])

    def test_clear_type_not_improved(self):
        entry = self._make_entry(clear_type='CLEAR', prev_clear_type='H-CLEAR')
        flags = compute_new_flags(entry)
        self.assertFalse(flags['clear_type'])

    def test_clear_type_prev_none(self):
        entry = self._make_entry(clear_type='CLEAR', prev_clear_type=None)
        flags = compute_new_flags(entry)
        self.assertTrue(flags['clear_type'])

    def test_clear_type_prev_no_play(self):
        entry = self._make_entry(clear_type='FAILED', prev_clear_type='NO PLAY')
        flags = compute_new_flags(entry)
        self.assertTrue(flags['clear_type'])

    def test_dj_level_improved(self):
        entry = self._make_entry(dj_level='AA', prev_dj_level='A')
        flags = compute_new_flags(entry)
        self.assertTrue(flags['dj_level'])

    def test_dj_level_same(self):
        entry = self._make_entry(dj_level='A', prev_dj_level='A')
        flags = compute_new_flags(entry)
        self.assertFalse(flags['dj_level'])

    def test_score_improved(self):
        entry = self._make_entry(score=1100, prev_score=1000)
        flags = compute_new_flags(entry)
        self.assertTrue(flags['score'])

    def test_score_not_improved(self):
        entry = self._make_entry(score=900, prev_score=1000)
        flags = compute_new_flags(entry)
        self.assertFalse(flags['score'])

    def test_miss_improved(self):
        entry = self._make_entry(miss_count=5, prev_miss_count=10)
        flags = compute_new_flags(entry)
        self.assertTrue(flags['miss_count'])

    def test_miss_not_improved(self):
        entry = self._make_entry(miss_count=15, prev_miss_count=10)
        flags = compute_new_flags(entry)
        self.assertFalse(flags['miss_count'])

    def test_miss_prev_none(self):
        # prev_miss_count が None → miss_count があれば new=True
        entry = self._make_entry(miss_count=5, prev_miss_count=None)
        flags = compute_new_flags(entry)
        self.assertTrue(flags['miss_count'])

    def test_miss_current_none(self):
        entry = self._make_entry(miss_count=None, prev_miss_count=10)
        flags = compute_new_flags(entry)
        self.assertFalse(flags['miss_count'])


class TestTsMinutePrefix(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_ts_minute_prefix('20251225-234518'), '20251225-2345')

    def test_alllog_format(self):
        self.assertEqual(_ts_minute_prefix('20251225-234500'), '20251225-2345')

    def test_same_minute(self):
        self.assertEqual(
            _ts_minute_prefix('20251225-234518'),
            _ts_minute_prefix('20251225-234500'),
        )


class TestMergeEntriesIntoMusic(unittest.TestCase):
    def _make_entry(self, ts, music='test', playtype='SP', difficulty='ANOTHER',
                    clear_type='CLEAR', prev_ct='CLEAR',
                    dj_level='A', prev_dj='A',
                    score=1000, prev_score=900,
                    miss_count=10, prev_miss=15,
                    notes=1000):
        return {
            'timestamp': ts,
            'music': music,
            'playtype': playtype,
            'difficulty': difficulty,
            'notes': notes,
            'clear_type': clear_type,
            'prev_clear_type': prev_ct,
            'dj_level': dj_level,
            'prev_dj_level': prev_dj,
            'score': score,
            'prev_score': prev_score,
            'miss_count': miss_count,
            'prev_miss_count': prev_miss,
            'options': {
                'arrange': None, 'flip': None, 'assist': None,
                'battle': False, 'allscratch': None, 'regularspeed': None,
            },
        }

    def test_empty_merge(self):
        music_json = {}
        entries = [self._make_entry('20230101-120000')]
        added, skipped = merge_entries_into_music(music_json, entries)
        self.assertEqual(added, 1)
        self.assertEqual(skipped, 0)
        self.assertIn('SP', music_json)
        self.assertIn('ANOTHER', music_json['SP'])
        self.assertIn('20230101-120000', music_json['SP']['ANOTHER']['history'])

    def test_duplicate_exact(self):
        music_json = {}
        entry = self._make_entry('20230101-120000')
        merge_entries_into_music(music_json, [entry])
        # 同じエントリを再度マージ
        added, skipped = merge_entries_into_music(music_json, [entry])
        self.assertEqual(added, 0)
        self.assertEqual(skipped, 1)

    def test_duplicate_same_minute(self):
        """inf_notebook 秒精度エントリと alllog 分精度エントリの重複"""
        music_json = {}
        # まず秒精度エントリ（notebook由来）を手動で追加
        ts_notebook = '20230101-120042'
        music_json['SP'] = {
            'ANOTHER': {
                'notes': 1000,
                'timestamps': [ts_notebook],
                'history': {
                    ts_notebook: {
                        'clear_type': {'value': 'CLEAR', 'new': False},
                        'dj_level': {'value': 'A', 'new': False},
                        'score': {'value': 1000, 'new': False},
                        'miss_count': {'value': 10, 'new': False},
                        'options': None,
                        'playspeed': None,
                    }
                },
                'best': {},
            }
        }

        # 同一分の alllog エントリ（末尾 00 秒）
        entry = self._make_entry('20230101-120000')
        added, skipped = merge_entries_into_music(music_json, [entry])
        self.assertEqual(added, 0)
        self.assertEqual(skipped, 1)
        # 元のエントリは保持
        self.assertIn(ts_notebook, music_json['SP']['ANOTHER']['history'])

    def test_different_minutes_both_added(self):
        music_json = {}
        entries = [
            self._make_entry('20230101-120000'),
            self._make_entry('20230101-130000'),
        ]
        added, skipped = merge_entries_into_music(music_json, entries)
        self.assertEqual(added, 2)
        self.assertEqual(skipped, 0)

    def test_timestamps_sorted_after_merge(self):
        music_json = {}
        entries = [
            self._make_entry('20230101-130000'),
            self._make_entry('20230101-110000'),
        ]
        merge_entries_into_music(music_json, entries)
        ts_list = music_json['SP']['ANOTHER']['timestamps']
        self.assertEqual(ts_list, sorted(ts_list))

    def test_best_updated_on_new_score(self):
        music_json = {}
        entries = [
            self._make_entry('20230101-120000', score=900, prev_score=800),
            self._make_entry('20230101-130000', score=1000, prev_score=900),
        ]
        merge_entries_into_music(music_json, entries)
        best = music_json['SP']['ANOTHER']['best']
        self.assertEqual(best['score']['value'], 1000)
        self.assertEqual(best['score']['timestamp'], '20230101-130000')

    def test_latest_is_most_recent(self):
        music_json = {}
        entries = [
            self._make_entry('20230101-120000'),
            self._make_entry('20230101-130000'),
        ]
        merge_entries_into_music(music_json, entries)
        latest = music_json['SP']['ANOTHER']['latest']
        self.assertEqual(latest['timestamp'], '20230101-130000')

    def test_speed_modified_play_not_in_best(self):
        """速度変更ありのプレイ (playspeed != None) は best 判定から除外される"""
        music_json = {}
        # 通常速度で score=900
        merge_entries_into_music(music_json, [self._make_entry('20230101-120000', score=900, prev_score=800)])

        # 速度変更ありのプレイ (score=9999) を手動で history に追加
        ts_speed = '20230101-130042'
        music_json['SP']['ANOTHER']['timestamps'].append(ts_speed)
        music_json['SP']['ANOTHER']['history'][ts_speed] = {
            'clear_type': {'value': 'F-COMBO', 'new': True},
            'dj_level': {'value': 'AAA', 'new': True},
            'score': {'value': 9999, 'new': True},
            'miss_count': {'value': 0, 'new': True},
            'options': {'arrange': None, 'flip': None, 'assist': None,
                        'battle': False, 'allscratch': None, 'regularspeed': None},
            'playspeed': 1.5,  # 速度変更あり
        }

        # 速度変更なしエントリを1件追加してマージ再計算をトリガー
        merge_entries_into_music(music_json, [self._make_entry('20230101-140000', score=950, prev_score=900)])

        best = music_json['SP']['ANOTHER']['best']
        # 速度変更ありの 9999 は反映されず、通常速度の最高値 950 が best
        self.assertEqual(best['score']['value'], 950)
        # latest は速度変更なしの最新プレイ
        self.assertEqual(best['latest'], '20230101-140000')


class TestGenerateAchievement(unittest.TestCase):
    def _make_target(self, entries):
        """指定エントリから target dict を構築する。"""
        target = {'notes': 1000, 'timestamps': [], 'history': {}}
        for ts, opts, ct, dj, sc in entries:
            target['timestamps'].append(ts)
            target['history'][ts] = {
                'clear_type': {'value': ct, 'new': False},
                'dj_level': {'value': dj, 'new': False},
                'score': {'value': sc, 'new': False},
                'miss_count': {'value': 10, 'new': False},
                'options': opts,
                'playspeed': None,
            }
        return target

    def test_version_string_is_numeric(self):
        """fromhistoriesgenerate_lastversion が数字を含む文字列であること。
        inf_notebook の versioncheck.py が re.search(r'\\d+', ...) で数字を抽出するため、
        数字を含まない文字列（例: 'migration'）は AttributeError を引き起こす。
        """
        target = self._make_target([
            ('20230101-120000',
             {'arrange': None, 'flip': None, 'assist': None, 'battle': False, 'allscratch': None, 'regularspeed': None},
             'CLEAR', 'A', 500),
        ])
        ach = generate_achievement(target)
        import re
        version = ach.get('fromhistoriesgenerate_lastversion', '')
        self.assertIsNotNone(
            re.search(r'\d+', version),
            f"fromhistoriesgenerate_lastversion={version!r} must contain digits"
        )

    def test_fixed_clear_type(self):
        target = self._make_target([
            ('20230101-120000',
             {'arrange': None, 'flip': None, 'assist': None, 'battle': False, 'allscratch': None, 'regularspeed': None},
             'H-CLEAR', 'AA', 500),
        ])
        ach = generate_achievement(target)
        self.assertEqual(ach['fixed']['clear_type'], 'H-CLEAR')
        self.assertEqual(ach['fixed']['dj_level'], 'AA')
        self.assertIsNone(ach['S-RANDOM']['clear_type'])

    def test_s_random_tracked(self):
        target = self._make_target([
            ('20230101-120000',
             {'arrange': 'S-RAN/S-RAN', 'flip': None, 'assist': None, 'battle': False, 'allscratch': None, 'regularspeed': None},
             'CLEAR', 'A', 500),
        ])
        ach = generate_achievement(target)
        self.assertEqual(ach['S-RANDOM']['clear_type'], 'CLEAR')
        self.assertIsNone(ach['fixed']['clear_type'])

    def test_max_flag(self):
        target = self._make_target([
            ('20230101-120000',
             {'arrange': None, 'flip': None, 'assist': None, 'battle': False, 'allscratch': None, 'regularspeed': None},
             'F-COMBO', 'AAA', 2000),  # notes=1000 なので MAX = 2000
        ])
        ach = generate_achievement(target)
        self.assertTrue(ach['fixed'].get('MAX'))

    def test_fcombo_aaa_flag(self):
        target = self._make_target([
            ('20230101-120000',
             {'arrange': None, 'flip': None, 'assist': None, 'battle': False, 'allscratch': None, 'regularspeed': None},
             'F-COMBO', 'AAA', 500),
        ])
        ach = generate_achievement(target)
        self.assertTrue(ach['fixed'].get('F-COMBO & AAA'))

    def test_random_not_in_fixed(self):
        target = self._make_target([
            ('20230101-120000',
             {'arrange': 'RAN/RAN', 'flip': None, 'assist': None, 'battle': False, 'allscratch': None, 'regularspeed': None},
             'H-CLEAR', 'AA', 500),
        ])
        ach = generate_achievement(target)
        self.assertIsNone(ach['fixed']['clear_type'])
        self.assertIsNone(ach['S-RANDOM']['clear_type'])

    def test_better_value_overwrites(self):
        target = self._make_target([
            ('20230101-120000',
             {'arrange': None, 'flip': None, 'assist': None, 'battle': False, 'allscratch': None, 'regularspeed': None},
             'CLEAR', 'A', 500),
            ('20230101-130000',
             {'arrange': None, 'flip': None, 'assist': None, 'battle': False, 'allscratch': None, 'regularspeed': None},
             'H-CLEAR', 'AA', 600),
        ])
        ach = generate_achievement(target)
        self.assertEqual(ach['fixed']['clear_type'], 'H-CLEAR')
        self.assertEqual(ach['fixed']['dj_level'], 'AA')


class TestShouldExclude(unittest.TestCase):
    def _entry(self, score=1000, miss_count=10):
        return {
            'score': score,
            'miss_count': miss_count,
        }

    def test_normal_entry_not_excluded(self):
        self.assertIsNone(should_exclude(self._entry()))

    def test_score_zero_excluded(self):
        self.assertIsNotNone(should_exclude(self._entry(score=0)))

    def test_score_9_excluded(self):
        self.assertIsNotNone(should_exclude(self._entry(score=9)))

    def test_score_10_not_excluded(self):
        self.assertIsNone(should_exclude(self._entry(score=10)))

    def test_miss_count_none_excluded(self):
        self.assertIsNotNone(should_exclude(self._entry(miss_count=None)))

    def test_miss_count_zero_not_excluded(self):
        # miss_count=0 はフルコンボ、除外しない
        self.assertIsNone(should_exclude(self._entry(miss_count=0)))


class TestNormalizeEntry(unittest.TestCase):
    def _entry_14(self):
        return ['10', 'SONG A', 'DPH', 900, 'AA', 'A', 'CLEAR', 'H-CLEAR',
                1200, 1350, 20, 15, 'OFF / OFF', '2024-06-01-12-30']

    def _entry_15(self):
        return ['10', 'SONG A', 'DPH', 900, 'AA', 'A', 'CLEAR', 'H-CLEAR',
                1200, 1350, 20, 15, '-3.2', 'OFF / OFF', '2024-06-01-12-30']

    def test_14_element(self):
        e = normalize_entry(self._entry_14())
        self.assertEqual(e['music'], 'SONG A')
        self.assertEqual(e['playtype'], 'DP')
        self.assertEqual(e['difficulty'], 'HYPER')
        self.assertEqual(e['timestamp'], '20240601-123000')
        self.assertEqual(e['score'], 1350)
        self.assertIsNone(e['options']['arrange'])

    def test_15_element(self):
        e = normalize_entry(self._entry_15())
        self.assertEqual(e['music'], 'SONG A')
        self.assertEqual(e['timestamp'], '20240601-123000')
        self.assertEqual(e['score'], 1350)

    def test_battle_sets_dp_battle(self):
        raw = ['10', 'SONG B', 'DPA', 900, 'A', 'A', 'CLEAR', 'CLEAR',
               1000, 1050, 10, 8, 'BATTLE, MIR / OFF', '2024-06-01-12-30']
        e = normalize_entry(raw)
        self.assertEqual(e['playtype'], 'DP BATTLE')

    def test_invalid_length(self):
        with self.assertRaises(ValueError):
            normalize_entry(['a', 'b', 'c'])


class TestMusicFilename(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(music_filename('A'), '41.json')

    def test_concon(self):
        self.assertEqual(music_filename('concon'), '636f6e636f6e.json')

    def test_roundtrip(self):
        name = 'テスト曲'
        fname = music_filename(name)
        decoded = bytes.fromhex(fname[:-5]).decode('utf-8')
        self.assertEqual(decoded, name)


class TestGenerateSummary(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write_music(self, music_name, data):
        save_music_json(self.tmpdir, music_name, data)

    def test_all_playtypes_always_present(self):
        """DP のみのデータでも summary に SP / DP / DP BATTLE キーが存在する"""
        self._write_music('DP Only Song', {
            'DP': {
                'ANOTHER': {
                    'notes': 1000,
                    'timestamps': ['20230101-120000'],
                    'history': {'20230101-120000': {
                        'clear_type': {'value': 'CLEAR', 'new': False},
                        'dj_level': {'value': 'A', 'new': False},
                        'score': {'value': 1000, 'new': False},
                        'miss_count': {'value': 10, 'new': False},
                        'options': None, 'playspeed': None,
                    }},
                    'best': {},
                }
            }
        })
        summary = generate_summary(self.tmpdir)
        entry = summary['musics']['DP Only Song']
        self.assertIn('SP', entry)
        self.assertIn('DP', entry)
        self.assertIn('DP BATTLE', entry)
        # SP と DP BATTLE はデータなしなので空 dict
        self.assertEqual(entry['SP'], {})
        self.assertEqual(entry['DP BATTLE'], {})
        # DP にはデータがある
        self.assertIn('ANOTHER', entry['DP'])

    def test_sp_only_song(self):
        """SP のみのデータでも DP / DP BATTLE キーが存在する"""
        self._write_music('SP Only Song', {
            'SP': {
                'HYPER': {
                    'notes': 800,
                    'timestamps': ['20230101-120000'],
                    'history': {'20230101-120000': {
                        'clear_type': {'value': 'H-CLEAR', 'new': False},
                        'dj_level': {'value': 'AA', 'new': False},
                        'score': {'value': 1400, 'new': False},
                        'miss_count': {'value': 5, 'new': False},
                        'options': None, 'playspeed': None,
                    }},
                    'best': {},
                }
            }
        })
        summary = generate_summary(self.tmpdir)
        entry = summary['musics']['SP Only Song']
        self.assertIn('SP', entry)
        self.assertIn('DP', entry)
        self.assertIn('DP BATTLE', entry)
        self.assertEqual(entry['DP'], {})
        self.assertEqual(entry['DP BATTLE'], {})


class TestIntegration(unittest.TestCase):
    """サンプルデータを使った統合テスト"""

    ALLLOG_PATH = 'docs/sample_data/inf_daken_counter/alllog.pkl'
    NOTEBOOK_SAMPLE_DIR = 'docs/sample_data/inf_notebook'

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_migration_completes(self):
        """alllog.pkl から移行が完走し、移行結果ファイルが生成される"""
        if not os.path.exists(self.ALLLOG_PATH):
            self.skipTest("alllog.pkl not found")

        entries, errors, excluded = load_alllog(self.ALLLOG_PATH)
        self.assertGreater(len(entries), 0)
        self.assertEqual(errors, 0)

        # 曲別グループ化
        music_entries = {}
        for entry in entries:
            music_entries.setdefault(entry['music'], []).append(entry)

        for music_name, ents in music_entries.items():
            music_json = {}
            added, skipped = merge_entries_into_music(music_json, ents)
            self.assertGreaterEqual(added, 0)
            save_music_json(self.tmpdir, music_name, music_json)

        # summary 生成
        summary = generate_summary(self.tmpdir)
        self.assertIn('musics', summary)
        self.assertGreater(len(summary['musics']), 0)

    def test_idempotent_migration(self):
        """同じデータを2回移行してもエントリが重複しない"""
        if not os.path.exists(self.ALLLOG_PATH):
            self.skipTest("alllog.pkl not found")

        entries, _, _excluded = load_alllog(self.ALLLOG_PATH)
        music_entries = {}
        for entry in entries:
            music_entries.setdefault(entry['music'], []).append(entry)

        total_added_first = 0
        for music_name, ents in music_entries.items():
            music_json = load_music_json(self.tmpdir, music_name)
            added, _ = merge_entries_into_music(music_json, ents)
            save_music_json(self.tmpdir, music_name, music_json)
            total_added_first += added

        # 2回目: すべてスキップされるはず
        total_added_second = 0
        total_skipped_second = 0
        for music_name, ents in music_entries.items():
            music_json = load_music_json(self.tmpdir, music_name)
            added, skipped = merge_entries_into_music(music_json, ents)
            save_music_json(self.tmpdir, music_name, music_json)
            total_added_second += added
            total_skipped_second += skipped

        self.assertEqual(total_added_second, 0)
        # skipped >= added_first (alllog 内部に重複エントリがある場合、
        # 1回目にスキップされたエントリも2回目にスキップされるため >=)
        self.assertGreaterEqual(total_skipped_second, total_added_first)

    def test_merge_with_existing_notebook_data(self):
        """既存 notebook データにマージしても元データが保持される"""
        if not os.path.exists(self.ALLLOG_PATH):
            self.skipTest("alllog.pkl not found")
        if not os.path.exists(self.NOTEBOOK_SAMPLE_DIR):
            self.skipTest("notebook sample dir not found")

        # 既存データをコピー
        for fname in os.listdir(self.NOTEBOOK_SAMPLE_DIR):
            src = os.path.join(self.NOTEBOOK_SAMPLE_DIR, fname)
            dst = os.path.join(self.tmpdir, fname)
            shutil.copy2(src, dst)

        # 既存ファイルの曲別タイムスタンプを記録
        original_timestamps = {}
        for fname in os.listdir(self.NOTEBOOK_SAMPLE_DIR):
            if not fname.endswith('.json') or fname in ('recent.json', 'summary.json'):
                continue
            with open(os.path.join(self.NOTEBOOK_SAMPLE_DIR, fname)) as f:
                data = json.load(f)
            for pt, diffs in data.items():
                for diff, d in diffs.items():
                    for ts in d.get('timestamps', []):
                        original_timestamps.setdefault(fname, set()).add(ts)

        # マージ実行
        entries, _, _excluded = load_alllog(self.ALLLOG_PATH)
        music_entries = {}
        for entry in entries:
            music_entries.setdefault(entry['music'], []).append(entry)

        for music_name, ents in music_entries.items():
            music_json = load_music_json(self.tmpdir, music_name)
            merge_entries_into_music(music_json, ents)
            save_music_json(self.tmpdir, music_name, music_json)

        # 元のタイムスタンプが全て保持されているか確認
        for fname, ts_set in original_timestamps.items():
            merged_path = os.path.join(self.tmpdir, fname)
            if not os.path.exists(merged_path):
                continue
            with open(merged_path) as f:
                merged = json.load(f)
            merged_ts = set()
            for pt, diffs in merged.items():
                for diff, d in diffs.items():
                    merged_ts.update(d.get('timestamps', []))
            missing = ts_set - merged_ts
            self.assertEqual(missing, set(),
                             f"{fname}: original timestamps missing after merge: {missing}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
