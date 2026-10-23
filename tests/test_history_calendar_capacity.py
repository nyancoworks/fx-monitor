"""Lossless canonical32 history above the former 2 MiB boundary."""
import base64
from copy import deepcopy
import gzip
import hashlib
import json
import unittest
from unittest.mock import patch

from diagnostics.monitoring_result_history import (append_generation, pack_generation,
    restore_generation, MAX_PLAIN_BYTES)
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot


CLOCK = 1800000000


def outlook(clock, *, large=False):
    value = build_scheduled_outlook({}, {}, evaluated_at=clock)
    if large:
        for row in value['rows']:
            row['synthetic_history_note'] = 's'*140000
    return value


class HistoryCalendarCapacityTests(unittest.TestCase):
    def test_valid_32_above_old_limit_roundtrips_without_dropping_fields(self):
        value = outlook(CLOCK, large=True); before = deepcopy(value)
        snapshot = {'evaluated_at': CLOCK, 'scheduled_outlook': value}
        self.assertEqual(validate_strategy_snapshot(snapshot), [])
        self.assertGreater(len(json.dumps(value['rows']).encode()), 2*1024*1024)
        packed = pack_generation(value['rows'], evaluated_at=CLOCK)
        restored = restore_generation(packed)
        self.assertEqual(restored['rows'], value['rows'])
        self.assertEqual(value, before)

    def test_existing_v1_generations_and_source_rows_are_not_rewritten(self):
        history = [pack_generation(outlook(CLOCK-i*3600)['rows'], evaluated_at=CLOCK-i*3600)
                   for i in (3, 2, 1)]
        before = deepcopy(history)
        value = outlook(CLOCK, large=True)
        result = append_generation(history, value['rows'], evaluated_at=CLOCK)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[:2], before[1:])
        self.assertEqual(history, before)
        self.assertEqual(restore_generation(result[-1])['rows'], value['rows'])
        self.assertEqual(append_generation(result, value['rows'], evaluated_at=CLOCK), result)

    def test_new_decoded_limit_and_compression_bomb_remain_bounded(self):
        value = outlook(CLOCK)
        value['rows'][0]['synthetic_history_note'] = 's'*MAX_PLAIN_BYTES
        with self.assertRaisesRegex(ValueError, 'size limit'):
            pack_generation(value['rows'], evaluated_at=CLOCK)
        compressed = gzip.compress(b' '* (MAX_PLAIN_BYTES+1), mtime=0)
        bad = {'evaluated_at': CLOCK, 'sha256': hashlib.sha256(compressed).hexdigest(),
               'gzip_base64': base64.b64encode(compressed).decode()}
        with self.assertRaisesRegex(ValueError, 'oversized'):
            restore_generation(bad)

    def test_encoder_and_reader_share_the_existing_encoded_limit(self):
        value = outlook(CLOCK); packed = pack_generation(value['rows'], evaluated_at=CLOCK)
        with patch('diagnostics.monitoring_result_history.MAX_ENCODED_BYTES', 10):
            with self.assertRaisesRegex(ValueError, 'compressed generation'):
                pack_generation(value['rows'], evaluated_at=CLOCK)
            with self.assertRaisesRegex(ValueError, 'compressed generation'):
                restore_generation(packed)


if __name__ == '__main__':
    unittest.main()
