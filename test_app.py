"""
Version: v1
Design, Author, Updated by: Girish Subramanya <girish.subramanya@daimlertruck.com>, VCP, B&I, DTICI
Date: 2025-12-23
"""
import unittest
import json
from app import app

class WorkflowGeneratorTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_index_page(self):
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'GitHub Workflow Generator', response.data)

    def test_generate_yaml(self):
        payload = {
            "name": "Test Workflow",
            "on": ["push", "pull_request"],
            "jobs": {
                "build": {
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"name": "Checkout", "uses": "actions/checkout@v3"},
                        {"name": "Run Test", "run": "echo 'Testing'"}
                    ]
                }
            }
        }

        response = self.app.post('/generate',
                                 data=json.dumps(payload),
                                 content_type='application/json')

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('yaml', data)

        yaml_content = data['yaml']
        self.assertIn('name: Test Workflow', yaml_content)
        self.assertIn('on:', yaml_content)
        self.assertIn('- push', yaml_content)
        self.assertIn('jobs:', yaml_content)
        self.assertIn('build:', yaml_content)
        self.assertIn('runs-on: ubuntu-latest', yaml_content)
        self.assertIn('steps:', yaml_content)
        self.assertIn('- name: Checkout', yaml_content)

if __name__ == '__main__':
    unittest.main()
