import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import pymupdf
from background_jobs import enqueue, get_job, process_job, update_job
from question_editing import completed_page
from study_data import load_questions


def question(number, stem='문제 내용'):
    return f'{number}) {stem}\n\n- [ ] 첫 보기\n- [ ] 둘째 보기\n'


class ManualRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = Path(__file__).resolve().parents[1]
        shutil.copy2(source / 'server.py', self.root / 'server.py')
        for name in ('extract.py', 'extract_references.py', 'extraction_format.py', 'exam_info.py'):
            (self.root / name).write_text('# fixture')
        spec = importlib.util.spec_from_file_location('manual_test_server', self.root / 'server.py')
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.handler = self.server.Handler.__new__(self.server.Handler)
        self.handler.send = lambda data, status=200, **kwargs: setattr(self, 'response', data)
        self.subject = self.server.CAT.add_subject('Test')
        with pymupdf.open() as pdf:
            pdf.new_page();pdf.new_page();pdf.new_page()
            self.item, _ = self.server.CAT.register(self.subject, 'bank', 'test.pdf', pdf.tobytes())
        self.bank = self.item['id']
        with patch('background_jobs.ensure_worker'):
            self.task = enqueue(self.root, self.item)
        update_job(self.server.CAT, self.task['id'], status='failed', current_page=2, completed=1, error='2페이지 처리 실패')
        self.job = Path(self.task['output_path'])
        page = self.job / 'page-001'
        (page / 'output').mkdir(parents=True)
        (page / 'state.json').write_text('{"text": true, "references": true}')
        (page / 'output/questions-with-images.md').write_text(question(1), encoding='utf-8')

    def get(self, path, **params):
        self.handler.path = path + '?' + urlencode(params)
        self.handler.get()
        return self.response

    def post(self, path, **data):
        self.handler.post(path, data)
        return self.response

    def test_failed_bank_keeps_successfully_extracted_questions_playable_and_editable(self):
        data = self.get('/api/subject', id=self.subject)
        self.assertTrue(data['banks'][0]['ready'])
        self.assertEqual(data['banks'][0]['incompletePages'], [2, 3])
        quiz = self.get('/api/quiz', bank=self.bank)
        self.assertEqual([q['id'] for q in quiz['questions']], ['1:1'])
        self.post('/api/answers', bank=self.bank, raw='1')
        record = self.post('/api/select', bank=self.bank, round=quiz['rounds'][0]['id'], question='1:1', value=1)
        self.assertEqual(record['correct'], 1)
        self.post('/api/question/edit', bank=self.bank, page=1, number=1, text=question(1, '수정한 문제'))
        self.assertIn('수정한 문제', self.get('/api/question/raw', bank=self.bank, page=1, number=1)['text'])
        self.assertTrue(self.get('/api/question/zip', bank=self.bank).startswith(b'PK'))

    def test_manual_pages_become_playable_and_complete_job_without_losing_old_records(self):
        self.server.QUIZ.save_answers(self.bank, '121')
        self.server.QUIZ.select(self.bank, '1:1', 1)
        round_id = self.server.QUIZ.rounds(self.bank)[0]['id']
        original_record = self.server.QUIZ.records(round_id)['1:1']
        data = self.get('/api/question/raw', bank=self.bank, page=2, mode='page')
        self.assertEqual(data['text'], '')
        self.assertEqual(data['suggestedNumber'], 2)
        self.post('/api/question/edit', bank=self.bank, page=2, mode='page', text=question(2))
        self.assertEqual(len(load_questions(self.job)), 2)
        self.assertTrue(completed_page(self.job, 2))
        self.assertEqual(get_job(self.root, self.task['id'])['status'], 'failed')
        self.assertEqual(get_job(self.root, self.task['id'])['completed'], 2)
        self.post('/api/question/edit', bank=self.bank, page=3, mode='page', text=question(3))
        repaired = get_job(self.root, self.task['id'])
        self.assertEqual(repaired['status'], 'done')
        self.assertEqual(repaired['completed'], 3)
        self.assertEqual(self.server.QUIZ.records(round_id)['1:1'], original_record)
        quiz = self.get('/api/quiz', bank=self.bank)
        self.assertEqual([q['number'] for q in quiz['questions']], [1, 2, 3])
        record = self.post('/api/select', bank=self.bank, round=round_id, question='2:2', value=2)
        self.assertEqual(record['correct'], 1)
        # Retry must reuse manually completed pages instead of invoking the model.
        with patch('background_jobs.run_stage', side_effect=AssertionError('manual page re-extracted')):
            process_job(self.root, repaired)
        self.assertIn('2) 문제 내용', (self.job / 'page-002/output/questions-with-images.md').read_text())

    def test_a_bank_without_any_successful_page_can_be_written_from_scratch(self):
        (self.job / 'page-001/output/questions-with-images.md').unlink()
        self.assertFalse(self.get('/api/subject', id=self.subject)['banks'][0]['ready'])
        data = self.get('/api/question/raw', bank=self.bank, page=1, mode='page')
        self.assertEqual(data['suggestedNumber'], 1)
        self.post('/api/question/edit', bank=self.bank, page=1, mode='page', text=question(1))
        self.assertTrue(self.get('/api/subject', id=self.subject)['banks'][0]['ready'])
        self.assertEqual(len(self.get('/api/quiz', bank=self.bank)['questions']), 1)

    def test_invalid_draft_and_running_page_do_not_overwrite_successful_work(self):
        for invalid in ('', '문제 번호 없음', '2) 문제\n- [ ] 하나', question(2) + question(2)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.post('/api/question/edit', bank=self.bank, page=2, mode='page', text=invalid)
        self.assertFalse(completed_page(self.job, 2))
        update_job(self.server.CAT, self.task['id'], status='running')
        with self.assertRaisesRegex(ValueError, '추출 중'):
            self.post('/api/question/edit', bank=self.bank, page=2, mode='page', text=question(2))
        self.assertEqual([q['number'] for q in load_questions(self.job)], [1])

    def test_partial_text_and_image_crops_are_available_on_failed_pages(self):
        folder = self.job / 'page-002'
        (folder / 'output').mkdir(parents=True)
        (folder / 'output/questions.md').write_text(question(2), encoding='utf-8')
        (folder / 'extraction-warnings.json').write_text(json.dumps([{'message': '공통 지문', 'original_values': {'text': '원문'}}]))
        data = self.get('/api/question/raw', bank=self.bank, page=2, mode='page')
        self.assertEqual(data['text'], question(2))
        self.assertEqual(data['warnings'][0]['original_values']['text'], '원문')
        crop = self.post('/api/question/crop', bank=self.bank, page=2, bbox=[0, 0, 500, 500])
        self.assertTrue((folder / 'output' / crop['file']).exists())
        self.assertTrue(self.get('/api/question/page', bank=self.bank, page=2).startswith(b'\x89PNG'))


if __name__ == '__main__':
    unittest.main()
