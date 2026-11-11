import importlib.util
import http.server
import json
import pathlib
import threading
import unittest


MODULE = pathlib.Path(__file__).with_name("optimize.py")
spec = importlib.util.spec_from_file_location("optimize", MODULE)
optimize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(optimize)


class RankingTests(unittest.TestCase):
    def test_http_status_rejects_fast_region_block(self):
        self.assertFalse(optimize.expected_status("chat", 403))
        self.assertFalse(optimize.expected_status("api", 403))
        self.assertTrue(optimize.expected_status("chat", 200))
        self.assertTrue(optimize.expected_status("api", 401))

    def test_complete_stable_node_beats_slightly_faster_spiky_node(self):
        results = {
            "stable": {"chat": [1.14, 1.15, 1.16], "api": [1.02, 1.03, 1.04]},
            "spiky": {"chat": [1.00, 1.02, 1.60], "api": [0.95, 0.96, 1.25]},
            "failed": {"chat": [0.5, None, 0.5], "api": [0.5, 0.5, 0.5]},
        }
        self.assertEqual(optimize.choose_best(results), "stable")

    def test_one_success_does_not_establish_stability(self):
        with self.assertRaises(RuntimeError):
            optimize.choose_best({"new": {"chat": [0.5], "api": [0.5]}})

    def test_failed_final_check_restores_original_selection(self):
        selected = []

        def select(name):
            selected.append(name)

        with self.assertRaises(RuntimeError):
            optimize.apply_with_rollback("new", "old", select, lambda: False)
        self.assertEqual(selected, ["new", "old"])

    def test_failed_selection_verification_restores_original(self):
        selected = []

        def select(name):
            selected.append(name)
            if name == "new":
                raise RuntimeError("GET verification timed out after PUT")

        with self.assertRaises(RuntimeError):
            optimize.apply_with_rollback("new", "old", select, lambda: True)
        self.assertEqual(selected, ["new", "old"])

    def test_shortlist_samples_regions_not_only_fast_blocked_hk(self):
        ordered = ["HK - A", "HK - B", "HK - C", "SG - A", "JP - A", "US - A"]
        chosen = optimize.shortlist_candidates(ordered, 4, "US - B")
        self.assertIn("US - A", chosen)
        self.assertIn("JP - A", chosen)
        self.assertIn("SG - A", chosen)
        self.assertIn("US - B", chosen)

    def test_shortlist_keeps_fastest_other_region(self):
        ordered = ["DE - fastest", "Tokyo HK relay", "HK - A", "JP - A", "SG - A", "US - A"]
        chosen = optimize.shortlist_candidates(ordered, 5, "US - B")
        self.assertEqual(chosen[0], "DE - fastest")
        self.assertIn("US - A", chosen)
        self.assertNotIn("Tokyo HK relay", chosen)

    def test_external_selection_is_not_overwritten_on_failure(self):
        state = {"now": "old"}

        def select(name):
            state["now"] = name

        def check():
            state["now"] = "manual"
            return False

        with self.assertRaises(RuntimeError):
            optimize.apply_with_rollback("new", "old", select, check, lambda: state["now"])
        self.assertEqual(state["now"], "manual")

    def test_route_check_rejects_rule_pointing_elsewhere(self):
        class FakeCore:
            def get(self, _path):
                return {"rules": [
                    {"type": "DomainSuffix", "payload": "chatgpt.com", "proxy": "DIRECT"},
                    {"type": "DomainSuffix", "payload": "openai.com", "proxy": "openAI"},
                ]}

        with self.assertRaisesRegex(RuntimeError, "chatgpt.com"):
            optimize.route_counters(FakeCore(), "openAI")

    def test_fresh_node_table_prioritizes_prior_success_without_exposing_config(self):
        ordered = ["HK - fast", "US - good", "JP - slow"]
        table = {"US - good": {"ok": True, "worst": 1.4}, "HK - fast": {"ok": False}}
        candidates = optimize.cached_candidates(ordered, "JP - slow", table)
        self.assertEqual(candidates[0], "US - good")
        self.assertIn("JP - slow", candidates)
        self.assertNotIn("HK - fast", candidates)

    def test_windows_controller_and_cache_location(self):
        self.assertEqual(optimize.controller_candidates("Windows")[:2],
                         ["http://127.0.0.1:9090", "http://127.0.0.1:9097"])
        self.assertEqual(optimize.controller_candidates("Windows", "localhost:1234"),
                         ["http://127.0.0.1:1234"])
        with self.assertRaisesRegex(RuntimeError, "local HTTP"):
            optimize.controller_candidates("Windows", "https://example.com:9090")
        path = optimize.table_path("Windows", {"LOCALAPPDATA": r"C:\Users\Ada\AppData\Local"})
        self.assertEqual(path.name, "nodes.json")
        self.assertEqual(path.parent.name, "clash-network-optimize")
        self.assertIn("AppData", str(path))

    def test_local_tcp_controller_uses_secret_without_shell_argument(self):
        seen = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen["path"] = self.path
                seen["authorization"] = self.headers.get("Authorization")
                data = json.dumps({"version": "test"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            core = optimize.Core("http://127.0.0.1:%d" % server.server_port,
                                 optimize.Budget(), "private-test-token")
            self.assertEqual(core.get("/version"), {"version": "test"})
            self.assertEqual(seen, {"path": "/version", "authorization": "Bearer private-test-token"})
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_autodetect_group_from_shared_openai_rules(self):
        class FakeCore:
            def get(self, _path):
                return {"rules": [
                    {"type": "DomainSuffix", "payload": "chatgpt.com", "proxy": "AI"},
                    {"type": "DomainSuffix", "payload": "openai.com", "proxy": "AI"},
                ]}

        self.assertEqual(optimize.detect_group(FakeCore(), {"AI": {"type": "Selector"}}), "AI")


if __name__ == "__main__":
    unittest.main()
