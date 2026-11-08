"""Exercise the v86 disk cache without network or browser dependencies."""
import importlib.util
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "projects/little-windows/serve.py"
spec = importlib.util.spec_from_file_location("little_windows_server", MODULE_PATH)
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class LittleWindowsCacheTests(unittest.TestCase):
    def test_fetch_cache_and_reject_invalid_parts(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            stack.enter_context(patch.object(server_module, "CACHE", Path(root) / "cache"))
            payload = b"x" * server_module.CHUNK
            response = unittest.mock.MagicMock()
            response.__enter__.return_value.read.return_value = payload
            upstream = stack.enter_context(patch.object(server_module.urllib.request, "urlopen", return_value=response))
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(server_module.Handler, directory=root))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(worker.join, 3)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            # The client uses an unpatched opener; only the handler's upstream
            # fetch is mocked.
            opener = urllib.request.build_opener()
            base = f"http://127.0.0.1:{server.server_port}"
            path = "/images/windows95-v3/0-262144.img"
            self.assertEqual(opener.open(base + path).read(), payload)
            self.assertEqual(opener.open(base + path).read(), payload)
            self.assertEqual(upstream.call_count, 1)
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(base + "/images/windows95-v3/1-262145.img")
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
            self.assertEqual(upstream.call_count, 1)
            with self.assertRaises(urllib.error.HTTPError) as removed:
                opener.open(base + "/images/windows2k-v2/0-262144.img")
            self.assertEqual(removed.exception.code, 404)
            removed.exception.close()
            self.assertEqual(upstream.call_count, 1)


if __name__ == "__main__":
    unittest.main()
