import json
from pathlib import Path
import tempfile
import unittest
from sandbox.task_spec import load_task


class TaskSpecTests(unittest.TestCase):
    def load(self, value):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'task.json'
            p.write_text(json.dumps(value))
            return load_task(p)

    def test_unrelated_question_is_preserved_without_fixture_rules(self):
        task = {'id': 'observatory', 'prompt': 'When did the observatory open?',
                'required_urls': ['https://example.org/observatory']}
        self.assertEqual(self.load(task), task)

    def test_answer_keys_and_world_rules_are_not_task_fields(self):
        with self.assertRaises(ValueError):
            self.load({'id': 'q', 'prompt': 'Question', 'required_urls': [], 'world_facts': {}})

    def test_invalid_questions_and_credential_urls_are_rejected(self):
        for prompt, urls in [('', []), ('Question', ['file:///etc/passwd']),
                             ('Question', ['https://user:secret@example.org/'])]:
            with self.subTest(urls=urls), self.assertRaises(ValueError):
                self.load({'id': 'q', 'prompt': prompt, 'required_urls': urls})
