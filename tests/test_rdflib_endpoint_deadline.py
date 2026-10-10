"""The rdflib endpoint's deadline middleware cancels a busy query and leaves the server usable."""
import asyncio
import importlib.util
import time
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "serve_rdflib", Path(__file__).resolve().parents[1] / "docker/rdflib-endpoint/serve_rdflib.py")
serve = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(serve)


def _call(middleware, path="/sparql"):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    asyncio.run(middleware({"type": "http", "path": path}, receive, send))
    return sent


class DeadlineTests(unittest.TestCase):
    def test_busy_query_is_cancelled_with_504(self):
        async def busy(scope, receive, send):
            while True:             # pure-Python busy loop, like an rdflib evaluation
                sum(range(1000))

        started = time.monotonic()
        sent = _call(serve.DeadlineMiddleware(busy, 0.3))
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual(sent[0]["status"], 504)

    def test_fast_query_is_untouched_and_leaves_nothing_pending(self):
        async def fast(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = serve.DeadlineMiddleware(fast, 0.2)
        self.assertEqual(_call(middleware)[0]["status"], 200)
        time.sleep(0.4)             # a late timer must not raise anything in this thread
        self.assertEqual(middleware.cancelled, 0)

    def test_other_paths_bypass_the_deadline(self):
        async def ready(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        self.assertEqual(_call(serve.DeadlineMiddleware(ready, 0.1), "/ready")[0]["status"], 200)


if __name__ == "__main__":
    unittest.main()


class SingleDecodeTests(unittest.TestCase):
    def test_form_post_is_decoded_once(self):
        import types
        from urllib.parse import urlencode
        module = types.SimpleNamespace()
        serve.single_decode(module)
        query = "SELECT * WHERE { <http://dbpedia.org/resource/Max_%28Album%29> ?p ?o }"
        (value,) = [v for k, v in module.parse.parse_qsl(urlencode({"query": query})) if k == "query"]
        self.assertEqual(module.parse.unquote(value), query)
