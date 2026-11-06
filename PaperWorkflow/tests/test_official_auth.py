import json
import os
import subprocess
import unittest
from unittest.mock import patch

from utils.pdf_official_handler import OfficialMinerUProcessor


class OfficialAuthenticationTests(unittest.TestCase):
    def test_cached_cli_login_is_verified_without_an_environment_token_or_upload(self):
        with patch.dict(os.environ, {'MINERU_TOKEN': ''}), patch('utils.pdf_official_handler.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, 'Token is valid', '')
            result = OfficialMinerUProcessor({}).authentication()
        self.assertTrue(result['verified'])
        self.assertEqual(run.call_args.args[0], ['mineru-open-api', 'auth', '--verify'])
        self.assertLessEqual(run.call_args.kwargs['timeout'], 15)

    def test_configured_executable_and_key_match_extraction_precedence_and_stay_private(self):
        config = {'api': {'mineru': {'cli_command': ['/path with spaces/mineru', '--base-url', 'https://example.test'],
                                    'api_key': 'private-config-token'}}}
        with patch.dict(os.environ, {'MINERU_TOKEN': 'stale-parent-token'}), patch('utils.pdf_official_handler.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 1, 'invalid token private-config-token', '')
            result = OfficialMinerUProcessor(config).authentication()
        self.assertEqual(run.call_args.kwargs['env']['MINERU_TOKEN'], 'private-config-token')
        self.assertEqual(run.call_args.args[0][-2:], ['auth', '--verify'])
        self.assertNotIn('private-config-token', json.dumps(result))
        self.assertEqual(result['status'], 'invalid')

    def test_invalid_success_output_timeout_and_missing_executable_never_attest_auth(self):
        cases = [(subprocess.CompletedProcess([], 0, 'token is invalid', ''), 'invalid'),
                 (subprocess.TimeoutExpired('mineru', 15), 'unavailable'),
                 (FileNotFoundError(), 'missing_cli')]
        for response, expected in cases:
            with self.subTest(expected=expected), patch('utils.pdf_official_handler.subprocess.run') as run:
                if isinstance(response, Exception): run.side_effect = response
                else: run.return_value = response
                result = OfficialMinerUProcessor({}).authentication()
                self.assertEqual(result['status'], expected)
                self.assertFalse(result['verified'])

    def test_flash_mode_does_not_make_an_auth_network_request(self):
        with patch('utils.pdf_official_handler.shutil.which', return_value='/installed/mineru'), patch('utils.pdf_official_handler.subprocess.run') as run:
            result = OfficialMinerUProcessor({'api': {'mineru': {'extract_mode': 'flash'}}}).authentication()
        run.assert_not_called()
        self.assertTrue(result['ready'])
        self.assertFalse(result['verified'])
