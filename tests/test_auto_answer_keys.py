from pathlib import Path
import tempfile
import unittest

import pymupdf
from catalog import Catalog
from study_data import QuizStore


class AutoAnswerKeyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.catalog = Catalog(Path(temporary.name))
        self.quiz = QuizStore(self.catalog)
        with pymupdf.open() as pdf:
            pdf.new_page()
            self.pdf = pdf.tobytes()

    def bank(self, name, year, term):
        subject = self.catalog.add_subject(name)
        item, _ = self.catalog.register(subject, 'bank', 'test.pdf', self.pdf)
        self.catalog.update_exam(item['id'], year, term)
        return item['id']

    def test_unique_match_ignores_spaces_and_grades_multiple_answers(self):
        bank = self.bank('영유아 교사론', 2020, '2학기')
        self.assertTrue(self.quiz.apply_archive(bank))
        self.assertEqual(len(self.quiz.answers(bank)), 35)
        self.assertEqual(self.quiz.answers(bank)['3'], 'K')
        self.quiz.select(bank, '1:3', 2)
        round_id = self.quiz.rounds(bank)[0]['id']
        self.assertEqual(self.quiz.records(round_id)['1:3']['correct'], 1)
        self.assertTrue(self.quiz.apply_archive(bank))

    def test_separate_grade_keys_are_never_chosen_arbitrarily(self):
        bank = self.bank('놀이지도', 2020, '2학기')
        self.assertFalse(self.quiz.apply_archive(bank))
        self.assertEqual(self.quiz.answers(bank), {})
        with self.catalog.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM answer_keys WHERE material=?', (bank,)).fetchone())

    def test_missing_year_term_and_subject_are_not_guessed(self):
        for index, (name, year, term) in enumerate((('Unknown', 2019, '2학기'), ('UNIX 시스템', 2020, '2학기'),
                                                  ('UNIX시스템', 2019, ''), ('UNIX 시 스템', 0, '2학기'))):
            # Different spelling keeps each catalog subject name unique.
            bank = self.bank(name, year, term)
            with self.subTest(index=index):
                self.assertFalse(self.quiz.apply_archive(bank))
                self.assertEqual(self.quiz.answers(bank), {})

    def test_manual_keys_including_explicit_clear_are_preserved(self):
        bank = self.bank('UNIX 시스템', 2019, '2학기')
        self.quiz.save_answers(bank, '12A?')
        self.assertFalse(self.quiz.apply_archive(bank))
        self.assertEqual(self.quiz.answers(bank), {'1': 1, '2': 2, '3': 'A', '4': None})
        self.quiz.save_answers(bank, '')
        self.assertFalse(self.quiz.apply_archive(bank))
        self.assertEqual(self.quiz.answers(bank), {})

    def test_metadata_changes_refresh_only_automatic_keys_and_keep_graded_history(self):
        bank = self.bank('UNIX 시스템', 2019, '2학기')
        self.assertTrue(self.quiz.apply_archive(bank))
        old = self.quiz.answers(bank)
        choice = old['1'] if isinstance(old['1'], int) else 1
        self.quiz.select(bank, '1:1', choice)
        round_id = self.quiz.rounds(bank)[0]['id']
        previous = self.quiz.records(round_id)['1:1']
        self.catalog.update_exam(bank, 2018, '2학기')
        self.assertTrue(self.quiz.apply_archive(bank))
        self.assertNotEqual(self.quiz.answers(bank), old)
        self.assertEqual(self.quiz.records(round_id)['1:1'], previous)
        self.catalog.update_exam(bank, 2020, '2학기')
        self.assertFalse(self.quiz.apply_archive(bank))
        self.assertEqual(self.quiz.answers(bank), {})
        self.assertEqual(self.quiz.records(round_id)['1:1'], previous)

    def test_manual_edit_of_an_automatic_key_is_preserved(self):
        bank = self.bank('UNIX 시스템', 2019, '2학기')
        self.assertTrue(self.quiz.apply_archive(bank))
        self.quiz.save_answers(bank, '11111')
        self.catalog.update_exam(bank, 2018, '2학기')
        self.assertFalse(self.quiz.apply_archive(bank))
        self.assertEqual(self.quiz.answers(bank), {str(n): 1 for n in range(1, 6)})

    def test_pending_records_are_graded_and_unknown_source_cells_remain_pending(self):
        bank = self.bank('6시그마 경영', 2019, '1학기')
        self.quiz.select(bank, '1:1', 3)
        self.quiz.select(bank, '1:16', 2)
        self.assertTrue(self.quiz.apply_archive(bank))
        records = self.quiz.records(self.quiz.rounds(bank)[0]['id'])
        self.assertEqual(records['1:1']['correct'], 1)
        self.assertIsNone(records['1:16']['correct'])
        self.assertIsNone(self.quiz.answers(bank)['16'])

    def test_empty_source_answer_rows_are_not_applied(self):
        bank = self.bank('사회복지현장실습', 2014, '2학기')
        self.assertFalse(self.quiz.apply_archive(bank))
        self.assertEqual(self.quiz.answers(bank), {})

    def test_existing_answer_table_migrates_as_manual(self):
        fresh = Catalog(self.catalog.root / 'legacy')
        with fresh.connect() as db:
            db.execute('CREATE TABLE answer_keys(material TEXT PRIMARY KEY, answers TEXT NOT NULL)')
            db.execute('INSERT INTO answer_keys VALUES(?,?)', ('legacy', '{"1": 2}'))
        migrated = QuizStore(fresh)
        self.assertEqual(migrated.answers('legacy'), {'1': 2})
        with fresh.connect() as db:
            self.assertEqual(db.execute('SELECT origin FROM answer_keys').fetchone()['origin'], 'manual')


if __name__ == '__main__':
    unittest.main()
