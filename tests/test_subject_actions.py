import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

import worker
from annotation_data import AnnotationStore
from background_jobs import enqueue, init_jobs, list_jobs, run_stage, update_job
from catalog import Catalog
from lecture_data import LectureStore
from study_data import QuizStore


class SubjectActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.catalog = init_jobs(self.base)
        self.a = self.catalog.add_subject('First')
        self.b = self.catalog.add_subject('Second')
        self.quiz = QuizStore(self.catalog)
        self.ink = AnnotationStore(self.catalog)
        self.lectures = LectureStore(self.catalog)
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((20, 20), 'Question')
            self.pdf = pdf.tobytes()
        self.materials = []
        self.tasks = []
        for name in ('extract.py', 'extract_references.py', 'extraction_format.py', 'exam_info.py'):
            (self.base / name).write_text('# fixture')
        for subject in (self.a, self.b):
            item, _ = self.catalog.register(subject, 'bank', 'test.pdf', self.pdf)
            self.materials.append(item)
            with patch('background_jobs.ensure_worker'):
                self.tasks.append(enqueue(self.base, item))
            self.quiz.save_answers(item['id'], '1')
            self.quiz.select(item['id'], '1:1', 1)
            self.quiz.replace_links(item['id'], '1:1', [], [], 'Saved note')
            self.ink.save(subject, 'chapter', 0, 'r1', [])
            self.lectures.plan(subject)
            (self.catalog.root / 'subjects' / subject / 'file.txt').write_text('fixture')

    def test_rename_keeps_identity_and_data(self):
        self.catalog.rename_subject(self.a, '  Renamed  ')
        self.assertEqual(self.catalog.subjects()[0]['name'], 'Renamed')
        self.assertEqual(self.catalog.subjects()[0]['id'], self.a)
        self.assertTrue(self.catalog.pdf_path(self.materials[0]).is_file())
        self.assertEqual(self.quiz.answers(self.materials[0]['id']), {'1': 1})

    def test_duplicate_blank_and_missing_names_do_not_mutate_data(self):
        for identifier, name in ((self.a, 'Second'), (self.a, '  '), ('missing', 'New')):
            with self.subTest(identifier=identifier, name=name), self.assertRaises(ValueError):
                self.catalog.rename_subject(identifier, name)
        self.assertEqual([row['name'] for row in self.catalog.subjects()], ['First', 'Second'])

    def test_delete_cleans_only_the_target_subject(self):
        self.catalog.delete_subject(self.a)
        self.assertEqual([row['id'] for row in self.catalog.subjects()], [self.b])
        self.assertFalse((self.catalog.root / 'subjects' / self.a).exists())
        self.assertTrue(self.catalog.pdf_path(self.materials[1]).is_file())
        self.assertEqual(self.quiz.answers(self.materials[1]['id']), {'1': 1})
        self.assertEqual([row['subject_id'] for row in list_jobs(self.base)], [self.b])
        with self.catalog.connect() as db:
            for table in ('answer_keys', 'quiz_attempts', 'practice_rounds', 'practice_migrations', 'explanations', 'explanation_notes'):
                self.assertFalse(db.execute(f'SELECT 1 FROM {table} WHERE material=?', (self.materials[0]['id'],)).fetchone())
            for table, column in (('page_annotations', 'subject'), ('lecture_plans', 'subject_id')):
                self.assertFalse(db.execute(f'SELECT 1 FROM {table} WHERE {column}=?', (self.a,)).fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM practice_attempts').fetchone()[0], 1)

    def test_delete_works_before_optional_tables_exist(self):
        fresh = Catalog(self.base / 'fresh')
        subject = fresh.add_subject('Empty')
        fresh.delete_subject(subject)
        self.assertEqual(fresh.subjects(), [])
        with self.assertRaises(ValueError):fresh.delete_subject(subject)

    def test_running_extraction_is_cancelled_without_touching_other_jobs(self):
        task = self.tasks[0]
        update_job(self.catalog, task['id'], status='running')
        script = self.base / 'slow.py'
        script.write_text('import time\nprint("started", flush=True)\ntime.sleep(60)\n')
        log_path = self.base / 'stage.log'
        def delete_when_started():
            for _ in range(300):
                if log_path.exists() and 'started' in log_path.read_text():
                    self.catalog.delete_subject(self.a)
                    return
                threading.Event().wait(.01)
            raise AssertionError('child did not start')
        deleting = threading.Thread(target=delete_when_started)
        deleting.start()
        with log_path.open('w') as log:
            result = run_stage(self.catalog, task['id'], [sys.executable, '-u', str(script)], self.base, log, os.environ.copy())
        deleting.join(timeout=5)
        self.assertFalse(deleting.is_alive())
        self.assertIsNone(result)
        self.assertEqual(len(list_jobs(self.base)), 1)

    def test_worker_removes_files_recreated_during_cancellation(self):
        class StopWorker(Exception):pass
        def cancelled(base, task):
            self.catalog.delete_subject(task['subject_id'])
            directory = self.catalog.root / 'subjects' / task['subject_id']
            directory.mkdir(parents=True)
            (directory / 'late-output.txt').write_text('race fixture')
        with patch('worker.process_job', side_effect=cancelled), patch('worker.time.sleep', side_effect=StopWorker):
            with self.assertRaises(StopWorker):worker.main(self.base)
        self.assertFalse((self.catalog.root / 'subjects' / self.a).exists())
        self.assertFalse((self.catalog.root / 'subjects' / self.b).exists())


if __name__ == '__main__':unittest.main()
