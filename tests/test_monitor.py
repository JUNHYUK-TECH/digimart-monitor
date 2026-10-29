import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# These tests do not install or launch a browser or contact Digimart.
try:
    import playwright.sync_api
except ModuleNotFoundError:
    sys.modules['playwright']=types.ModuleType('playwright')
    api=types.ModuleType('playwright.sync_api')
    api.sync_playwright=MagicMock()
    sys.modules['playwright.sync_api']=api

import monitor


class MonitorTests(unittest.TestCase):
    def test_block_diagnostic_redacts_tokens(self):
        response=types.SimpleNamespace(status=403,headers={'server':'cloudflare'})
        page=types.SimpleNamespace(url='https://www.digimart.net/search?keywordAnd=Tyler&__cf_chl_rt_tk=SECRET')
        with self.assertRaises(monitor.AccessBlocked) as ctx:
            monitor.check_response(response,page,page.url)
        self.assertNotIn('SECRET',str(ctx.exception))
        self.assertTrue(json.loads(str(ctx.exception))['challenge'])

    def test_challenge_header_even_with_200(self):
        response=types.SimpleNamespace(status=200,headers={'cf-mitigated':'challenge'})
        page=types.SimpleNamespace(url='https://www.digimart.net/search')
        with self.assertRaises(monitor.AccessBlocked):
            monitor.check_response(response,page,page.url)

    def run_case(self,diagnostic=False,blocked=True):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'seen.json'
            result=Path(tmp)/'latest.json'
            state.write_text('["DS1"]')
            result.write_text(json.dumps({'status':'ok','checked_at':'2026-10-01T00:00:00Z'}))
            original_state=state.read_bytes()
            original_result=result.read_bytes()
            browser=MagicMock()
            factory=MagicMock()
            factory.return_value.__enter__.return_value.chromium.launch.return_value=browser
            item={'id':'DS2','keyword':'Tyler','title':'James Tyler','price':200000,'url':'https://example.test/DS2'}
            with patch.object(monitor,'STATE',state), patch.object(monitor,'RESULT',result), \
                 patch.object(monitor,'sync_playwright',factory), \
                 patch.object(monitor,'scrape',side_effect=monitor.AccessBlocked('403') if blocked else None,
                              return_value=([item],{'parsed':1})) as scrape:
                if blocked:
                    with self.assertRaises(RuntimeError):
                        monitor.main(diagnostic=diagnostic)
                    self.assertEqual(scrape.call_count,1)
                else:
                    monitor.main(diagnostic=diagnostic)
                browser.close.assert_called_once()
                if diagnostic or blocked:
                    self.assertEqual(state.read_bytes(),original_state)
                if diagnostic:
                    self.assertEqual(result.read_bytes(),original_result)
                    self.assertEqual(scrape.call_args.args[2],1)
                elif blocked:
                    data=json.loads(result.read_text())
                    self.assertEqual(data['failure_kind'],'access_blocked')
                    self.assertEqual(data['last_success_at'],'2026-10-01T00:00:00Z')
                    self.assertEqual(data['new'],[])
                else:
                    self.assertEqual(json.loads(state.read_text()),['DS1','DS2'])
                    self.assertEqual(len(json.loads(result.read_text())['new']),1)

    def test_block_preserves_seen_and_last_success(self):
        self.run_case()

    def test_diagnostic_failure_does_not_write(self):
        self.run_case(diagnostic=True)

    def test_diagnostic_success_does_not_write(self):
        self.run_case(diagnostic=True,blocked=False)

    def test_success_deduplicates_across_keywords(self):
        self.run_case(blocked=False)

    def test_existing_filters(self):
        self.assertTrue(monitor.allowed('Fender','Fender American Ultra Stratocaster',200000))
        self.assertFalse(monitor.allowed('Fender','Fender Player Mexico',200000))
        self.assertFalse(monitor.allowed('Gibson','Epiphone Gibson',200000))
        self.assertFalse(monitor.allowed('Tyler','James Tyler',100000))


if __name__ == '__main__':
    unittest.main()
