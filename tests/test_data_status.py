import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from webapp.data_status import _read_last_non_empty_line  # noqa: E402


class ReadLastLineTests(unittest.TestCase):
    def _check(self, content: bytes, expected, chunk_size=1024):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.csv")
            with open(path, "wb") as f:
                f.write(content)
            self.assertEqual(_read_last_non_empty_line(path, chunk_size=chunk_size), expected)

    def test_trailing_newlines_and_crlf(self):
        self._check(b"date,close\n2026-11-12,100\n", "2026-11-12,100")
        self._check(b"date,close\r\n2026-11-12,100\r\n\r\n", "2026-11-12,100")
        self._check(b"only line", "only line")

    def test_empty_and_missing(self):
        self._check(b"", None)
        self._check(b"\n\r\n", None)
        self.assertIsNone(_read_last_non_empty_line(os.path.join(ROOT, "no_such_file.csv")))

    def test_line_longer_than_chunk(self):
        long_line = "2026-11-12," + "9" * 50
        self._check(f"head\n{long_line}\n".encode(), long_line, chunk_size=8)
        self._check(long_line.encode() + b"\n\n", long_line, chunk_size=8)

    def test_utf8_text(self):
        self._check("코드,이름\n005930,삼성전자\n".encode("utf-8"), "005930,삼성전자")


if __name__ == "__main__":
    unittest.main()
