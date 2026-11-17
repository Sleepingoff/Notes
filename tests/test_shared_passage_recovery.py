import copy
import unittest

from extraction_format import validate_result


def extraction(group):
    return {'questions': [{'number': n, 'stem': f'{n}번 문제', 'choices': ['보기 1', '보기 2'], 'image_ids': []}
                          for n in (7, 8, 9)], 'references': [], 'shared_passages': [group]}


class SharedPassageRecoveryTests(unittest.TestCase):
    def test_unscoped_passage_keeps_questions_and_original_for_manual_review(self):
        group = {'source_label': '공통 자료', 'questions': [], 'text': '공통 지문 원문', 'image_ids': []}
        result = validate_result(extraction(group))
        self.assertEqual(len(result['questions']), 3)
        self.assertTrue(all(q['shared_text'] == '' for q in result['questions']))
        self.assertEqual(result['_warnings'][0]['original_values'], group)
        self.assertEqual(result['_warnings'][0]['questions'], [7, 8, 9])
        self.assertIn('직접 수정', result['_warnings'][0]['message'])
        # Reusing the validated extraction cache must not duplicate the warning.
        self.assertEqual(len(validate_result(copy.deepcopy(result))['_warnings']), 1)

    def test_empty_placeholder_passage_does_not_fail_the_entire_page(self):
        result = validate_result(extraction({'source_label': '', 'questions': [], 'text': '', 'image_ids': []}))
        self.assertEqual(len(result['questions']), 3)
        self.assertEqual(result['_warnings'], [])

    def test_explicit_single_number_and_range_are_applied_only_to_their_questions(self):
        for label, affected in (('(7)', {7}), ('7번', {7}), ('※ (7~8)', {7, 8})):
            with self.subTest(label=label):
                result = validate_result(extraction({'source_label': label, 'questions': [], 'text': '공통 원문', 'image_ids': []}))
                self.assertEqual({q['number'] for q in result['questions'] if q['shared_text']}, affected)
        with self.assertRaises(ValueError):
            validate_result(extraction({'source_label': '(8~7)', 'questions': [], 'text': '원문', 'image_ids': []}))


if __name__ == '__main__':
    unittest.main()
