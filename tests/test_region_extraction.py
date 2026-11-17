import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
import region_extraction as regions
import ai_settings


class RegionExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / 'source.pdf'
        with pymupdf.open() as doc:
            doc.new_page(width=200, height=300)
            doc.save(self.pdf)
        self.output = self.root / 'output'

    def run_extract(self, client):
        client.show.return_value = {'capabilities': ['vision']}
        return regions.extract(self.pdf, 1, 7, [0, 0, 1000, 500], [[100, 100, 300, 300]], self.output, self.root)

    @patch('region_extraction.ollama.Client')
    def test_selected_picture_is_attached_to_only_the_requested_problem(self, factory):
        client = factory.return_value
        client.chat.return_value = {'message': {'content': json.dumps({'stem': '문제', 'shared_text': '', 'choices': ['보기 가', '보기 나']})}}
        result = self.run_extract(client)
        self.assertIn('7) 문제', result['text'])
        self.assertIn('보기 가', result['text'])
        self.assertEqual(len(result['images']), 1)
        self.assertIn(result['images'][0], result['text'])
        with pymupdf.open(self.output / result['images'][0]) as image:
            self.assertGreater(image[0].rect.width, 0)
        images = client.chat.call_args.kwargs['messages'][0]['images']
        self.assertEqual(len(images), 2)
        self.assertTrue(images[0].startswith(b'\x89PNG'))

    @patch('region_extraction.ollama.Client')
    def test_invalid_ai_response_does_not_replace_or_write_question_files(self, factory):
        client = factory.return_value
        client.chat.return_value = {'message': {'content': json.dumps({'stem': '', 'shared_text': '', 'choices': []})}}
        self.output.mkdir()
        original = self.output / 'questions-with-images.md'
        original.write_text('기존 문제', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_extract(client)
        self.assertEqual(original.read_text(encoding='utf-8'), '기존 문제')
        self.assertEqual(list(self.output.glob('*.png')), [])

    def test_invalid_regions_are_rejected_before_ai_use(self):
        for box in ([0, 0, 0, 10], [-1, 0, 1, 2], [0, 0, 1001, 1000], [0, 0, float('nan'), 1], [False, 0, 1, 1]):
            with self.subTest(box=box), self.assertRaises(ValueError):
                regions.validate_box(box)


class AISettingsTests(unittest.TestCase):
    def test_saved_settings_round_trip_and_invalid_update_preserves_settings(self):
        with tempfile.TemporaryDirectory() as root:
            saved = ai_settings.save(root, {'model': 'qwen3-vl:4b'})
            self.assertEqual(ai_settings.load(root), saved)
            with self.assertRaises(ValueError):
                ai_settings.save(root, {'host': 'https://example.com'})
            self.assertEqual(ai_settings.load(root), saved)

    def test_cloud_and_non_vision_models_are_rejected(self):
        for info in ({'capabilities': ['completion']}, {'capabilities': ['vision'], 'remote_host': 'example.com'}):
            with self.subTest(info=info), self.assertRaises(ValueError):
                ai_settings.check_model(info)


if __name__ == '__main__':
    unittest.main()
