import tempfile
import unittest
import uuid
from pathlib import Path

import pymupdf

from annotation_data import AnnotationStore, export_pdf
from catalog import Catalog
from lecture_data import LectureStore
from study_data import QuizStore


def pdf_bytes(text):
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((20, 20), text)
        return pdf.tobytes()


class LectureAutosaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.catalog = Catalog(Path(self.temp.name))
        self.subject = self.catalog.add_subject('Test')
        self.store = LectureStore(self.catalog)
        self.a, self.b = uuid.uuid4().hex, uuid.uuid4().hex
        self.order = [{'upload': 0, 'client_id': self.a, 'title': 'First', 'included': True},
                      {'upload': 1, 'client_id': self.b, 'title': 'Second', 'included': True}]
        self.pdfs = [pdf_bytes('First page'), pdf_bytes('Second page')]

    def test_auto_merge_generates_bookmarks_and_retries_are_idempotent(self):
        result = self.store.save(self.subject, self.order, self.pdfs)
        again = self.store.save(self.subject, self.order, self.pdfs)
        self.assertEqual(result['plan'], again['plan'])
        self.assertEqual(len(again['plan']), 2)
        with pymupdf.open(self.catalog.bundle(self.subject)['path']) as pdf:
            self.assertEqual(pdf.page_count, 2)
            self.assertEqual(pdf.get_toc(), [[1, 'First', 1], [1, 'Second', 2]])

    def test_excluded_sources_survive_restart_and_can_be_included_again(self):
        rows = self.store.save(self.subject, self.order, self.pdfs)['plan']
        rows[0]['included'] = False
        self.store.save(self.subject, rows, [])
        restarted = LectureStore(Catalog(self.catalog.root))
        restored = restarted.plan(self.subject)
        self.assertFalse(restored[0]['included'])
        self.assertEqual(self.catalog.bundle(self.subject)['pages'], 1)
        restored[0]['included'] = True
        restarted.save(self.subject, restored, [])
        with pymupdf.open(self.catalog.bundle(self.subject)['path']) as pdf:
            self.assertIn('First page', pdf[0].get_text())
            self.assertIn('Second page', pdf[1].get_text())

    def test_reorder_preserves_annotation_and_explanation_identity(self):
        rows = self.store.save(self.subject, self.order, self.pdfs)['plan']
        ink = AnnotationStore(self.catalog)
        ink.save(self.subject, self.a, 0, 'r1', [{'type': 'text', 'text': 'Saved note', 'x': .1, 'y': .1,
                 'size': .025, 'color': '#112233', 'width': .001, 'opacity': 1}])
        quiz = QuizStore(self.catalog)
        quiz.replace_links('bank', '1:1', self.catalog.bundle(self.subject)['chapters'], [1], 'Explain')
        rows.reverse();rows[0]['title'] = 'Renamed'
        self.store.save(self.subject, rows, [])
        bundle = self.catalog.bundle(self.subject)
        self.assertEqual(bundle['chapters'][1]['id'], self.a)
        self.assertEqual(quiz.links('bank', '1:1')[0]['chapter'], self.a)
        with pymupdf.open(stream=export_pdf(self.catalog, bundle), filetype='pdf') as pdf:
            self.assertIn('Saved note', pdf[1].get_text())
            self.assertEqual(pdf.get_toc()[0][1], 'Renamed')

    def test_excluding_every_source_keeps_plan_and_allows_restore(self):
        rows = self.store.save(self.subject, self.order, self.pdfs)['plan']
        for row in rows:row['included'] = False
        result = self.store.save(self.subject, rows, [])
        self.assertIsNone(result['bundle'])
        rows = LectureStore(self.catalog).plan(self.subject)
        rows[1]['included'] = True
        self.assertEqual(self.store.save(self.subject, rows, [])['bundle']['pages'], 1)

    def test_invalid_edit_does_not_replace_existing_bundle(self):
        rows = self.store.save(self.subject, self.order, self.pdfs)['plan']
        original = self.catalog.bundle(self.subject)['path'].read_bytes()
        rows[0]['title'] = ''
        with self.assertRaises(ValueError):self.store.save(self.subject, rows, [])
        self.assertEqual(self.catalog.bundle(self.subject)['path'].read_bytes(), original)
        self.assertEqual(self.store.plan(self.subject)[0]['title'], 'First')

    def test_existing_bundle_migration_keeps_chapter_ids(self):
        self.catalog.merge_lectures(self.subject, [{'title': 'Old', 'data': self.pdfs[0], 'chapter_id': self.a}])
        rows = self.store.plan(self.subject)
        self.assertEqual(rows[0]['chapter'], self.a)
        rows[0]['title'] = 'Updated'
        self.store.save(self.subject, rows, [])
        self.assertEqual(self.catalog.bundle(self.subject)['chapters'][0]['id'], self.a)

    def test_notes_save_without_any_linked_pages_and_can_be_cleared(self):
        quiz = QuizStore(self.catalog)
        quiz.replace_links('bank', '1:1', [], [], 'Memo without pages')
        self.assertEqual(QuizStore(self.catalog).note('bank', '1:1'), 'Memo without pages')
        self.assertEqual(quiz.links('bank', '1:1'), [])
        quiz.replace_links('bank', '1:1', [], [], '')
        self.assertEqual(quiz.note('bank', '1:1'), '')


if __name__ == '__main__':unittest.main()
