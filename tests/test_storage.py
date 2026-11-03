import os
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp import storage


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = temp.name
        self.path = os.path.join(self.dir, "watch_202611.csv")

    def write_bytes(self, data: bytes) -> None:
        with open(self.path, "wb") as f:
            f.write(data)

    def read_bytes(self) -> bytes:
        with open(self.path, "rb") as f:
            return f.read()

    def backups(self) -> list[str]:
        backup_dir = os.path.join(self.dir, storage.BACKUP_DIRNAME)
        return sorted(os.listdir(backup_dir)) if os.path.isdir(backup_dir) else []


class AppendRowTests(StorageTestCase):
    def test_creates_file(self):
        storage.append_row(self.path, {"code": "005930", "메모": "첫 행"})
        df = storage.read_csv(self.path, dtype=str)
        self.assertEqual(df["code"].tolist(), ["005930"])
        self.assertEqual(self.backups(), [])

    def test_keeps_existing_rows(self):
        storage.append_row(self.path, {"code": "005930"})
        storage.append_row(self.path, {"code": "000660"})
        df = storage.read_csv(self.path, dtype=str)
        self.assertEqual(df["code"].tolist(), ["005930", "000660"])

    def test_reads_cp949_file_without_losing_rows(self):
        self.write_bytes("code,메모\n005930,기존 메모\n".encode("cp949"))
        storage.append_row(self.path, {"code": "000660", "메모": "새 메모"})
        df = storage.read_csv(self.path, dtype=str)
        self.assertEqual(df["메모"].tolist(), ["기존 메모", "새 메모"])

    def test_unreadable_file_is_not_overwritten(self):
        original = b"\xff\xfe\x00\x81invalid"
        self.write_bytes(original)
        with mock.patch.object(storage, "READ_ENCODINGS", ("utf-8-sig",)):
            with self.assertRaises(storage.CsvReadError):
                storage.append_row(self.path, {"code": "005930"})
        self.assertEqual(self.read_bytes(), original)
        self.assertEqual(self.backups(), [])

    def test_malformed_file_is_not_overwritten(self):
        original = 'code,memo\n005930,"닫히지 않은 따옴표\n'.encode("utf-8")
        self.write_bytes(original)
        with self.assertRaises(storage.CsvReadError):
            storage.append_row(self.path, {"code": "000660"})
        self.assertEqual(self.read_bytes(), original)


class WriteCsvTests(StorageTestCase):
    def test_backs_up_previous_version(self):
        storage.write_csv(self.path, pd.DataFrame({"code": ["005930"]}))
        before = self.read_bytes()
        storage.write_csv(self.path, pd.DataFrame({"code": ["000660"]}))
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        with open(os.path.join(self.dir, storage.BACKUP_DIRNAME, backups[0]), "rb") as f:
            self.assertEqual(f.read(), before)

    def test_failed_write_keeps_original_and_no_temp_file(self):
        storage.write_csv(self.path, pd.DataFrame({"code": ["005930"]}))
        before = self.read_bytes()
        with mock.patch.object(storage.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                storage.write_csv(self.path, pd.DataFrame({"code": ["000660"]}))
        self.assertEqual(self.read_bytes(), before)
        self.assertEqual(sorted(os.listdir(self.dir)), [storage.BACKUP_DIRNAME, "watch_202611.csv"])

    def test_backup_retention_only_touches_same_file(self):
        other = os.path.join(self.dir, "watch.csv")
        storage.write_csv(other, pd.DataFrame({"code": ["1"]}))
        storage.write_csv(other, pd.DataFrame({"code": ["2"]}))
        storage.write_csv(self.path, pd.DataFrame({"code": ["1"]}))
        with mock.patch.object(storage, "BACKUP_KEEP_COUNT", 2):
            for i in range(5):
                storage.write_csv(self.path, pd.DataFrame({"code": [str(i)]}))
        backups = self.backups()
        self.assertEqual(len([b for b in backups if b.startswith("watch_202611_")]), 2)
        self.assertEqual(len([b for b in backups if not b.startswith("watch_202611_")]), 1)


class ReadCsvTests(StorageTestCase):
    def test_empty_file_returns_empty_frame(self):
        self.write_bytes(b"")
        self.assertTrue(storage.read_csv(self.path).empty)

    def test_missing_file_raises(self):
        with self.assertRaises(storage.CsvReadError):
            storage.read_csv(self.path)

    def test_keeps_leading_zero_with_str_dtype(self):
        self.write_bytes("﻿code\n005930\n".encode("utf-8"))
        self.assertEqual(storage.read_csv(self.path, dtype=str)["code"].tolist(), ["005930"])


class HoldingsTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.dir, "holdings.csv")

    def test_missing_file_gives_default_columns(self):
        self.assertIn("종목코드", storage.load_holdings_source_df(self.path).columns)

    def test_add_row_uses_existing_column_names(self):
        self.write_bytes("﻿ticker,name,buy_price,shares\n005930,삼성전자,100,1\n".encode("utf-8"))
        storage.add_holding_row(self.path, "660", "SK하이닉스", "200", "2", "메모")
        df = storage.read_csv(self.path, dtype=str)
        self.assertEqual(df["ticker"].tolist(), ["005930", "000660"])
        self.assertEqual(df["shares"].tolist(), ["1", "2"])
        self.assertEqual(df["메모"].tolist()[1], "메모")

    def test_add_row_does_not_overwrite_unreadable_file(self):
        original = "종목코드,메모\n005930,\"닫히지 않음\n".encode("utf-8")
        self.write_bytes(original)
        with self.assertRaises(storage.CsvReadError):
            storage.add_holding_row(self.path, "000660", "SK하이닉스", "200", "2", "")
        self.assertEqual(self.read_bytes(), original)


class MergeLegacyRecordTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.target = os.path.join(self.dir, "ma_break.csv")
        self.first = os.path.join(self.dir, "MA10_J_Break.csv")
        self.second = os.path.join(self.dir, "MA240_J_Break.csv")
        self.legacy_dir = os.path.join(self.dir, storage.BACKUP_DIRNAME, storage.LEGACY_RECORD_DIRNAME)

    def write_legacy(self):
        pd.DataFrame({"종목코드": ["005930", "000660"], "메모": ["가", ""]}).to_csv(self.first, index=False, encoding="utf-8-sig")
        pd.DataFrame({"종목코드": ["068270"], "메모": ["나"]}).to_csv(self.second, index=False, encoding="utf-8-sig")

    def test_merges_rows_with_pattern_and_moves_originals(self):
        self.write_legacy()
        self.assertEqual(storage.merge_legacy_record_files(self.target), 3)
        merged = storage.read_csv(self.target, dtype=str)
        self.assertEqual(merged["패턴"].tolist(), ["주봉 10이평 돌파 매매", "주봉 10이평 돌파 매매", "주봉 240이평 돌파 매매"])
        self.assertEqual(merged["종목코드"].tolist(), ["005930", "000660", "068270"])
        self.assertFalse(os.path.exists(self.first))
        self.assertEqual(sorted(os.listdir(self.legacy_dir)), ["MA10_J_Break.csv", "MA240_J_Break.csv"])

    def test_existing_target_is_left_alone(self):
        self.write_legacy()
        pd.DataFrame({"패턴": ["x"]}).to_csv(self.target, index=False, encoding="utf-8-sig")
        self.assertEqual(storage.merge_legacy_record_files(self.target), 0)
        self.assertEqual(len(storage.read_csv(self.target, dtype=str)), 1)
        self.assertTrue(os.path.exists(self.first))

    def test_no_legacy_files_creates_nothing(self):
        self.assertEqual(storage.merge_legacy_record_files(self.target), 0)
        self.assertFalse(os.path.exists(self.target))

    def test_unreadable_file_changes_nothing(self):
        self.write_legacy()
        with open(self.second, "wb") as f:
            f.write('종목코드,메모\n068270,"닫히지 않음\n'.encode("utf-8"))
        with self.assertRaises(storage.CsvReadError):
            storage.merge_legacy_record_files(self.target)
        self.assertFalse(os.path.exists(self.target))
        self.assertTrue(os.path.exists(self.first))
        self.assertTrue(os.path.exists(self.second))


class WatchFileOptionTests(StorageTestCase):
    def test_backup_folder_and_temp_files_are_not_listed(self):
        path = os.path.join(self.dir, "watch_202001.csv")
        storage.write_csv(path, pd.DataFrame({"code": ["1"]}))
        storage.write_csv(path, pd.DataFrame({"code": ["2"]}))
        open(os.path.join(self.dir, ".tmp_abc.csv"), "w").close()
        labels = [label for label, _ in storage.interest_watch_file_options(self.dir)]
        self.assertEqual(labels.count("202001"), 1)
        self.assertEqual(len(labels), 2)  # 현재월 + 202001


if __name__ == "__main__":
    unittest.main()
