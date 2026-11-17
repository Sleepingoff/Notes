import lzma
from pathlib import Path
import tempfile
import unittest
import unicodedata

from answer_archive import AnswerArchive, DEFAULT_PATH, SYMBOL_MASKS, encode


class AnswerArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = AnswerArchive()

    def test_all_sources_and_semesters_present(self):
        archive = self.archive
        self.assertEqual(len(archive.sources), 15)
        self.assertEqual(len(archive.records), 4421)
        self.assertEqual({(r.year, r.term) for r in archive.records},
                         {(year, term) for year in range(2014, 2021) for term in (1, 2)})
        self.assertEqual(sum(s['bytes'] for s in archive.sources), 992507)
        self.assertLess(DEFAULT_PATH.stat().st_size, 50000)
        self.assertTrue(all(len(s['sha256']) == 64 for s in archive.sources))
        # The supplied 2020 documents list face-to-face courses only.
        self.assertEqual(sum(r.year == 2020 for r in archive.records), 12)

    def test_single_and_multiple_answers_match_source_examples(self):
        key, = self.archive.find(2014, 2, '생물과학', grade=1)
        self.assertEqual([key.choices(n) for n in range(1, 6)], [(4,), (2,), (1,), (1, 3), (4,)])
        key, = self.archive.find(2020, 2, '영유아교사론')
        self.assertEqual(key.choices(3), (1, 2, 3, 4))
        key, = self.archive.find(2020, 2, '놀이지도', grade=1)
        self.assertEqual(key.choices(20), (1, 2))
        key, = self.archive.find(2020, 1, '아동관찰및행동연구')
        self.assertEqual([key.choices(n) for n in range(31, 36)], [(3,), (2,), (4,), (4,), (1,)])

    def test_course_names_and_grades_are_not_conflated(self):
        keys = self.archive.find(2020, 2, unicodedata.normalize('NFD', '놀이 지도'))
        self.assertEqual({r.grade for r in keys}, {1, 4})
        self.assertNotEqual(keys[0].masks, keys[1].masks)
        self.assertEqual(self.archive.find(2020, 2, '존재하지않는과목'), ())

    def test_invalid_original_cell_is_preserved_without_guessing(self):
        key, = self.archive.find(2019, 1, '6시그마경영', grade=3)
        self.assertEqual(len(key.masks), 25)
        self.assertEqual(key.issues[0]['raw'], '23323f')
        self.assertEqual(key.issues[0]['questions'], [16, 20])
        self.assertTrue(all(key.choices(n) == () for n in range(16, 21)))
        self.assertEqual(key.choices(21), (2,))
        self.assertEqual(sum(m == 0 for r in self.archive.records for m in r.masks), 5)
        empty, = self.archive.find(2014, 2, '사회복지현장실습', grade=4)
        self.assertEqual(empty.masks, ())
        with self.assertRaises(IndexError):
            key.choices(0)
        with self.assertRaises(IndexError):
            key.choices(26)

    def test_all_choice_combinations_roundtrip_across_byte_boundaries(self):
        combinations = list(range(16)) * 3 + [1, 2, 4]
        records = [{'year': 2014 + n % 7, 'term': n % 2 + 1, 'grade': n % 4 + 1,
                    'subject': '과목', 'source': 0, 'masks': combinations[:n]}
                   for n in (0, 1, 3, 4, 5, 15, 16, 17, 35, 51)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.bin'
            path.write_bytes(encode(records, [{'file': 'test'}], []))
            decoded = AnswerArchive(path)
        for original, restored in zip(records, decoded.records):
            self.assertEqual(tuple(original['masks']), restored.masks)
        self.assertEqual(len(set(SYMBOL_MASKS.values())), 15)

    def test_corrupt_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.bin'
            raw = bytearray(DEFAULT_PATH.read_bytes())
            raw[len(raw) // 2] ^= 0x80
            path.write_bytes(raw)
            with self.assertRaises(lzma.LZMAError):
                AnswerArchive(path)
            path.write_bytes(b'BAD!')
            with self.assertRaises(ValueError):
                AnswerArchive(path)


if __name__ == '__main__':
    unittest.main()
