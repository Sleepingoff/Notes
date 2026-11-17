import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from urllib.parse import urlencode


class AnswerTablesApiTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'server.py'
        shutil.copy2(Path(__file__).resolve().parents[1] / 'server.py', path)
        spec = importlib.util.spec_from_file_location('answer_tables_test_server', path)
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.handler = self.server.Handler.__new__(self.server.Handler)
        self.response = None
        def send(data, status=200, **kwargs):
            self.response = (data, status)
        self.handler.send = send

    def subject_data(self, subject):
        self.handler.path = '/api/subject?' + urlencode({'id': subject})
        self.handler.get()
        return self.response[0]

    def test_subject_name_ignores_spaces_and_returns_all_years_and_terms(self):
        subject = self.server.CAT.add_subject('  놀이  지도 ')
        keys = self.subject_data(subject)['answerKeys']
        self.assertTrue(keys)
        self.assertEqual({key['subject'] for key in keys}, {'놀이지도'})
        self.assertEqual({key['grade'] for key in keys if key['year'] == 2020 and key['term'] == 2}, {1, 4})
        key, = [key for key in keys if key['year'] == 2020 and key['term'] == 2 and key['grade'] == 1]
        self.assertEqual(key['answers'][19], [1, 2])
        self.assertEqual([(key['year'], key['term'], -key['grade']) for key in keys],
                         sorted([(key['year'], key['term'], -key['grade']) for key in keys], reverse=True))
        self.assertEqual(self.server.CAT.materials(subject, 'bank'), [])

    def test_renaming_refreshes_matches_and_unknown_subjects_have_no_keys(self):
        subject = self.server.CAT.add_subject('Not in the answer archive')
        self.assertEqual(self.subject_data(subject)['answerKeys'], [])
        self.handler.post('/api/subject/rename', {'id': subject, 'name': '6 시그마 경영'})
        self.assertTrue(self.response[0]['answerKeys'])
        keys = self.subject_data(subject)['answerKeys']
        key, = [key for key in keys if key['year'] == 2019 and key['term'] == 1 and key['grade'] == 3]
        self.assertEqual(key['answers'][15:20], [[]] * 5)
        self.assertEqual(key['issues'][0]['raw'], '23323f')

    def test_pasted_multiple_answers_are_accepted_by_the_select_api(self):
        subject = self.server.CAT.add_subject('Test')
        with pymupdf.open() as pdf:
            pdf.new_page()
            item, _ = self.server.CAT.register(subject, 'bank', 'test.pdf', pdf.tobytes())
        bank = item['id']
        self.handler.post('/api/answers', {'bank': bank, 'raw': 'AAAA?K'})
        self.assertEqual(self.response[0]['1'], 'A')
        self.assertIsNone(self.response[0]['5'])
        round_id = self.server.QUIZ.rounds(bank)[0]['id']
        for number, selected, expected in ((1, 1, 1), (2, 2, 1), (3, 3, 0), (4, 4, 0), (5, 1, None), (6, 4, 1)):
            with self.subTest(number=number):
                self.handler.post('/api/select', {'bank': bank, 'round': round_id,
                                                 'question': f'1:{number}', 'value': selected})
                self.assertEqual(self.response[0]['correct'], expected)

    def test_quiz_api_automatically_populates_a_unique_key(self):
        subject = self.server.CAT.add_subject('영유아 교사론')
        with pymupdf.open() as pdf:
            pdf.new_page()
            item, _ = self.server.CAT.register(subject, 'bank', 'test.pdf', pdf.tobytes())
        bank = item['id']
        self.server.CAT.update_exam(bank, 2020, '2학기')
        with patch.object(self.server, 'bank_task', return_value={'output_path': 'unused'}), patch.object(self.server, 'load_questions', return_value=[]):
            self.handler.path = '/api/quiz?' + urlencode({'bank': bank})
            self.handler.get()
        self.assertEqual(self.response[0]['answers']['3'], 'K')
        self.assertEqual(len(self.response[0]['answers']), 35)
        self.assertEqual(self.server.QUIZ.answers(bank), self.response[0]['answers'])

    def test_missing_subject_does_not_return_unrelated_keys(self):
        with self.assertRaises(ValueError):
            self.subject_data('missing')


if __name__ == '__main__':
    unittest.main()
