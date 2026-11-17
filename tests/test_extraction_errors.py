import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

import worker
from background_jobs import enqueue, get_job, init_jobs, list_jobs, process_job, retry_job, update_job
from extraction_errors import ExtractionError, failure_fields


class ExtractionFailureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.catalog = init_jobs(self.base)
        subject = self.catalog.add_subject('Test')
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((30, 30), 'Test question')
            data = pdf.tobytes()
        item, _ = self.catalog.register(subject, 'bank', 'test.pdf', data)
        for name in ('extract.py', 'extract_references.py', 'extraction_format.py', 'exam_info.py'):
            (self.base / name).write_text('# fixture\n')
        with patch('background_jobs.ensure_worker'):
            self.task = enqueue(self.base, item)

    def test_error_classification(self):
        cases = [
            ('ConnectionError: Failed to connect to Ollama', 'OLLAMA_UNAVAILABLE'),
            ('model qwen3-vl:8b-instruct not found', 'MODEL_NOT_FOUND'),
            ('model requires more system memory', 'OUT_OF_MEMORY'),
            ('ReadTimeout: timed out', 'EXTRACTION_TIMEOUT'),
            ('출력 길이 제한에 도달했습니다.', 'OUTPUT_LIMIT'),
            ('문제가 추출되지 않았습니다.', 'NO_QUESTIONS'),
            ('JSONDecodeError: expecting value', 'INVALID_EXTRACTION_DATA'),
            ('ModuleNotFoundError: no module named ollama', 'DEPENDENCY_MISSING'),
            ('PermissionError: denied', 'FILE_ACCESS_DENIED'),
            ('FileNotFoundError: missing input.pdf', 'SOURCE_MISSING'),
            ('FileDataError: cannot open broken document', 'INVALID_PDF'),
            ('unexpected failure', 'EXTRACTION_FAILED'),
        ]
        for detail, code in cases:
            with self.subTest(code=code):
                fields = failure_fields(detail, page=3)
                self.assertEqual(fields['error_code'], code)
                self.assertTrue(fields['error_message'].startswith('3페이지:'))
                self.assertEqual(fields['error'], detail)

    def test_old_schema_and_failed_record(self):
        with self.catalog.connect() as db:
            db.execute('ALTER TABLE extraction_jobs DROP COLUMN error_code')
            db.execute('ALTER TABLE extraction_jobs DROP COLUMN error_message')
            db.execute("UPDATE extraction_jobs SET status='failed',error='2페이지 처리 실패\nConnectionError: Failed to connect to Ollama'")
        task = get_job(self.base, self.task['id'])
        self.assertEqual(task['error_code'], 'OLLAMA_UNAVAILABLE')
        self.assertTrue(task['error_message'].startswith('2페이지:'))
        self.assertEqual(list_jobs(self.base)[0]['error_code'], task['error_code'])
        init_jobs(self.base)  # repeated migration keeps existing data
        self.assertEqual(get_job(self.base, task['id'])['material_id'], task['material_id'])

    def test_retry_clears_all_errors(self):
        update_job(self.catalog, self.task['id'], status='failed', **failure_fields('Connection refused'))
        with patch('background_jobs.ensure_worker') as start:
            retry_job(self.base, self.task['id'])
            start.assert_called_once()
        task = get_job(self.base, self.task['id'])
        self.assertEqual(task['status'], 'queued')
        for name in ('error', 'error_code', 'error_message'):
            self.assertEqual(task[name], '')

    def test_subprocess_error_retains_stage_page_and_log(self):
        (self.base / 'extract.py').write_text("raise ConnectionError('Failed to connect to Ollama')\n")
        with self.assertRaises(ExtractionError) as caught:
            process_job(self.base, self.task)
        fields = failure_fields(caught.exception)
        self.assertEqual(fields['error_code'], 'OLLAMA_UNAVAILABLE')
        self.assertEqual(fields['error_message'].count('1페이지:'), 1)
        self.assertIn('ConnectionError', fields['error'])
        self.assertTrue((Path(self.task['output_path']) / 'page-001/text.log').exists())

    def test_reference_and_missing_output_errors(self):
        self.assertEqual(failure_fields('unknown', stage='references')['error_code'], 'REFERENCE_EXTRACTION_FAILED')
        with self.assertRaises(ExtractionError) as caught:
            process_job(self.base, self.task)  # empty fixture script produces no file
        self.assertEqual(failure_fields(caught.exception)['error_code'], 'OUTPUT_MISSING')

    def test_worker_persists_structured_failure(self):
        class StopWorker(Exception):
            pass
        with patch('worker.process_job', side_effect=ExtractionError('OUTPUT_LIMIT', '응답이 너무 깁니다.', 'detail', page=1)), patch('worker.time.sleep', side_effect=StopWorker):
            with self.assertRaises(StopWorker):
                worker.main(self.base)
        task = get_job(self.base, self.task['id'])
        self.assertEqual(task['status'], 'failed')
        self.assertEqual(task['error_code'], 'OUTPUT_LIMIT')
        self.assertEqual(task['error_message'], '1페이지: 응답이 너무 깁니다.')
        self.assertEqual(task['error'], 'detail')

    def test_success_clears_error_codes(self):
        update_job(self.catalog, self.task['id'], **failure_fields('Connection refused'))
        folder = Path(self.task['output_path']) / 'page-001'
        (folder / 'output').mkdir(parents=True)
        (folder / 'state.json').write_text(json.dumps({'references': True}))
        (folder / 'output/questions-with-images.md').write_text('1) Question\n- [ ] Choice\n')
        process_job(self.base, self.task)
        task = get_job(self.base, self.task['id'])
        self.assertEqual(task['status'], 'done')
        self.assertEqual(task['error_code'], '')
        self.assertEqual(task['error_message'], '')


if __name__ == '__main__':
    unittest.main()
