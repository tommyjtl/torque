"""Exercise the local Infinite Mac asset cache without network access."""
import importlib.util
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

PATH = Path(__file__).resolve().parents[1] / "projects/retro-infinite-proxy/serve.py"
spec = importlib.util.spec_from_file_location("retro_infinite_proxy", PATH)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class InfiniteRetroCacheTests(unittest.TestCase):
    def test_local_embed_cache_and_path_restriction(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            stack.enter_context(patch.object(proxy, "CACHE", Path(root)))
            response = MagicMock()
            response.__enter__.return_value.headers = {"Content-Type": "application/javascript"}
            response.__enter__.return_value.read.return_value = b"asset"
            upstream = stack.enter_context(patch.object(proxy.urllib.request, "urlopen", return_value=response))
            server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(worker.join, 3)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            opener = urllib.request.build_opener()
            base = f"http://127.0.0.1:{server.server_port}"
            with opener.open(base + "/embed?disk=BeOS") as result:
                self.assertIn(b"main-Bw9bLu8v.js", result.read())
                self.assertEqual(result.headers["Cross-Origin-Embedder-Policy"], "require-corp")
            for _ in range(2):
                with opener.open(base + "/assets/0/test.js") as result:
                    self.assertEqual(result.read(), b"asset")
            self.assertEqual(upstream.call_count, 1)
            request = upstream.call_args.args[0]
            self.assertEqual(request.full_url, "https://www.infinitemac.org/assets/0/test.js")
            with self.assertRaises(urllib.error.HTTPError) as missing:
                opener.open(base + "/unrelated")
            self.assertEqual(missing.exception.code, 404)
            missing.exception.close()
            self.assertEqual(upstream.call_count, 1)


if __name__ == "__main__":
    unittest.main()
