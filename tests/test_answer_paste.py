from pathlib import Path
import tempfile
import unittest

from answer_archive import SYMBOL_MASKS
from catalog import Catalog
from study_data import QuizStore, answer_correct, parse_answers


class AnswerPasteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.catalog = Catalog(Path(temporary.name))
        self.quiz = QuizStore(self.catalog)

    def test_pasted_symbols_preserve_question_positions_and_legacy_input(self):
        self.assertEqual(parse_answers('1A?K4'), {'1': 1, '2': 'A', '3': None, '4': 'K', '5': 4})
        self.assertEqual(parse_answers('1, 2 3;4，9'), {'1': 1, '2': 2, '3': 3, '4': 4, '5': 9})
        for invalid in ('1L4', '10', '1[2,3]', '<script>'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_answers(invalid)

    def test_every_multiple_answer_symbol_accepts_exactly_its_choices(self):
        for symbol in 'ABCDEFGHIJK':
            for selected in range(1, 6):
                with self.subTest(symbol=symbol, selected=selected):
                    expected = selected <= 4 and bool(SYMBOL_MASKS[symbol] & (1 << (selected - 1)))
                    self.assertEqual(answer_correct(selected, symbol), int(expected))
        self.assertIsNone(answer_correct(1, None))
        self.assertIsNone(answer_correct(None, 'A'))

    def test_pasted_keys_grade_pending_answers_and_keep_historical_results(self):
        self.quiz.save_answers('bank', 'A?3')
        round_id = self.quiz.rounds('bank')[0]['id']
        self.quiz.select('bank', '1:1', 2, round_id)
        self.quiz.select('bank', '1:2', 4, round_id)
        self.quiz.select('bank', '1:3', 1, round_id)
        records = self.quiz.records(round_id)
        self.assertEqual(records['1:1']['correct'], 1)
        self.assertEqual(records['1:1']['answer'], 'A')
        self.assertIsNone(records['1:2']['correct'])
        self.assertEqual(records['1:3']['correct'], 0)
        self.quiz.save_answers('bank', '1K4')
        records = self.quiz.records(round_id)
        self.assertEqual(records['1:1']['answer'], 'A')
        self.assertEqual(records['1:1']['correct'], 1)
        self.assertEqual(records['1:2']['answer'], 'K')
        self.assertEqual(records['1:2']['correct'], 1)
        self.assertEqual(records['1:3']['answer'], 3)
        new_round = self.quiz.new_round('bank')
        self.quiz.select('bank', '1:1', 2, new_round)
        self.assertEqual(self.quiz.records(new_round)['1:1']['correct'], 0)
        self.assertEqual(self.quiz.answers('bank'), {'1': 1, '2': 'K', '3': 4})

    def test_legacy_attempt_migration_understands_pasted_multiple_answers(self):
        self.quiz.save_answers('bank', 'A?')
        with self.catalog.connect() as db:
            db.execute("INSERT INTO quiz_attempts VALUES('bank','1:1',2)")
            db.execute("INSERT INTO quiz_attempts VALUES('bank','1:2',3)")
        round_id = self.quiz.rounds('bank')[0]['id']
        records = self.quiz.records(round_id)
        self.assertEqual(records['1:1']['answer'], 'A')
        self.assertEqual(records['1:1']['correct'], 1)
        self.assertIsNone(records['1:2']['correct'])


if __name__ == '__main__':
    unittest.main()
