import json
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from fx_common import NoCredentialRedirect, SetupError, discover_models, load_catalog, select_model


class DiscoveryTests(unittest.TestCase):
    def test_authenticated_discovery_parses_ids_without_inference(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'data': [
            {'id': 'google/gemma-4-31b-it'}, {'id': 'google/gemma-4-31b-it'}]}).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with patch('fx_common.urllib.request.build_opener', return_value=opener):
            result = discover_models('fixture-token')
        self.assertEqual(result, {'google/gemma-4-31b-it'})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.modular.com/v1/models')
        self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-token')
        self.assertIsNone(request.data)
        self.assertEqual(opener.open.call_count, 1)

    def test_error_bodies_and_keys_are_not_echoed(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError('https://api.modular.com/v1/models', 401,
                                                        'fixture-token', {}, None)
        with patch('fx_common.urllib.request.build_opener', return_value=opener):
            with self.assertRaises(SetupError) as error:
                discover_models('fixture-token')
        self.assertIn('HTTP 401', str(error.exception))
        self.assertNotIn('fixture-token', str(error.exception))

    def test_credential_redirect_is_refused(self):
        with self.assertRaises(SetupError):
            NoCredentialRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example/models')

    def test_invalid_catalog_response_is_not_used(self):
        for data in [b'not JSON', b'[]', b'{"data":{}}', b'{"data":[{"id":null}]}']:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = data
            opener = MagicMock()
            opener.open.return_value = response
            with patch('fx_common.urllib.request.build_opener', return_value=opener):
                with self.assertRaises(SetupError):
                    discover_models('fixture-token')

    def test_default_falls_back_to_visible_compatible_model(self):
        catalog = load_catalog()
        self.assertEqual(select_model(catalog, {'google/gemma-4-31b-it', 'minimax/minimax-m3'}), 'google/gemma-4-31b-it')
        self.assertEqual(select_model(catalog, {'deepseek/deepseek-v4.1-flash', 'google/gemma-4-31b-it'}), 'deepseek/deepseek-v4.1-flash')

    def test_invisible_explicit_model_and_unknown_metadata_are_rejected(self):
        catalog = load_catalog()
        for requested in [catalog['default_model'], 'unknown/new-model']:
            with self.assertRaises(SetupError):
                select_model(catalog, {'google/gemma-4-31b-it', 'unknown/new-model'}, requested)
        with self.assertRaises(SetupError):
            select_model(catalog, {'minimax/minimax-m3', 'qwen/qwen3.8-27b'})


if __name__ == '__main__':
    unittest.main()
