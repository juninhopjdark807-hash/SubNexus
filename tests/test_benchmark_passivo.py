from __future__ import annotations

from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from benchmark_passivo.config import DEFAULT_CONFIG
from benchmark_passivo.controller import BenchmarkController
from benchmark_passivo.server import start_server


class BenchmarkControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.logs = Path(self.temp.name)
        self.config = deepcopy(DEFAULT_CONFIG)
        self.config["trial"]["exit_after_finish"] = False
        self.controller = BenchmarkController(self.config, self.logs)
        self.assertTrue(self.controller.begin_trial("unit_test"))
        self.sequence = 0

    def tearDown(self):
        self.controller.close()
        self.temp.cleanup()

    def emit(self, name, data=None, tab_id=7, source_ms=None):
        self.sequence += 1
        self.controller.ingest_event(
            {
                "name": name,
                "source": "unit_test",
                "source_timestamp_ms": source_ms or time.time() * 1000,
                "sequence": self.sequence,
                "tab_id": tab_id,
                "data": data or {},
            },
            extension_id="test-extension",
        )

    def complete_request(self, endpoint, request_id, status=200, tab_id=7):
        self.emit(
            "browser.request.started",
            {
                "request_id": request_id,
                "method": "POST",
                "url": f"https://dtv-cms-ui.tbxnet.com/{endpoint}",
            },
            tab_id=tab_id,
        )
        self.emit(
            "browser.request.completed",
            {
                "request_id": request_id,
                "method": "POST",
                "url": f"https://dtv-cms-ui.tbxnet.com/{endpoint}",
                "status_code": status,
            },
            tab_id=tab_id,
        )

    def mutation(self, action, endpoint, request_id, status=200, tab_id=7):
        self.emit(f"cms.{action}.intent", {"trusted": True}, tab_id=tab_id)
        self.complete_request(endpoint, request_id, status=status, tab_id=tab_id)

    def test_two_edits_are_distinct(self):
        self.emit("cms.edit.intent", {"trusted": True, "content_id": "abc123def456"})
        self.emit("cms.edit.intent", {"trusted": True, "content_id": "abc123def456"})
        trial = self.controller._trial
        self.assertIn("edit_1.intent", trial["markers"])
        self.assertIn("edit_2.intent", trial["markers"])
        self.assertNotIn("more_than_two_edit_actions", trial["quality_flags"])

    def test_validate_media_does_not_complete_final_validate(self):
        self.mutation("validate_media", "api/validate-media", "request-media")
        trial = self.controller._trial
        self.assertTrue(trial["active"])
        self.assertIn("validate_media.completed", trial["markers"])
        self.assertNotIn("validate.completed", trial["markers"])

    def test_final_validate_success_finishes_and_writes_summary(self):
        self.mutation("validate_media", "api/validate-media", "request-media")
        self.mutation("approve", "api/approve", "request-approve")
        self.mutation("validate", "api/validate", "request-validate")

        self.assertFalse(self.controller.trial_active)
        with self.controller.store.summary_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            rows = list(csv.DictReader(file, delimiter=";"))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["end_reason"], "validate_response_success")
        self.assertEqual(row["end_confidence"], "endpoint_pattern")
        self.assertTrue(row["validate_media_completed_at_s"])
        self.assertTrue(row["approve_completed_at_s"])
        self.assertTrue(row["validate_completed_at_s"])
        self.assertTrue(row["validate_processing_seconds"])

    def test_generic_mutating_request_is_flagged(self):
        self.mutation("validate", "api/contents/action", "request-generic")
        trial = self.controller._trial
        self.assertFalse(trial["active"])
        self.assertIn(
            "validate_generic_network_correlation",
            trial["quality_flags"],
        )

    def test_http_error_does_not_finish(self):
        self.mutation("validate", "api/validate", "request-error", status=500)
        trial = self.controller._trial
        self.assertTrue(trial["active"])
        self.assertNotIn("validate.completed", trial["markers"])
        self.assertIn("validate_http_500", trial["quality_flags"])

    def test_full_path_is_redacted_in_raw_log(self):
        self.emit(
            "cms.upload.file_selected",
            {
                "filename": r"C:\\Users\\Analyst\\Downloads\\secret.vtt",
                "trusted": True,
            },
        )
        lines = self.controller.store.raw_path.read_text(encoding="utf-8").splitlines()
        event = json.loads(lines[-1])
        serialized = json.dumps(event)
        self.assertNotIn("Analyst", serialized)
        self.assertIn("secret.vtt", serialized)
        self.assertIn("path_hash", event["data"])

    def test_complete_expected_trace_is_quality_valid(self):
        content = {"trusted": True, "content_id": "abc123def456"}
        self.emit("cms.search.intent", content)
        self.emit("cms.edit.intent", content)
        self.emit("cms.download.intent", content)
        self.emit("browser.download.created", {"download_id": 1})
        self.emit("browser.download.completed", {"download_id": 1})
        self.controller.record_internal("filesystem.download.ready", {"download_id": 1})
        self.controller.record_internal(
            "windows.foreground.changed", {"app": "subtitle_edit"}
        )
        self.controller.record_internal(
            "filesystem.subtitle.changed", {"filename": "subtitle.vtt"}
        )
        self.controller.record_internal(
            "windows.foreground.changed", {"app": "browser"}
        )
        self.emit("cms.edit.intent", content)
        self.emit("cms.upload.open.intent", content)
        self.emit("cms.upload.file_selected", content)
        self.emit("cms.upload.language_selected", content)
        self.emit("cms.upload.submit.intent", content)
        self.complete_request("api/upload", "request-upload")
        self.emit("cms.play.intent", content)
        self.emit("cms.player_select.intent", content)
        self.emit("browser.player_target.created", {})
        self.emit("player.ready", {})
        self.emit("player.play", {})
        self.mutation("validate_media", "api/validate-media", "request-media")
        self.mutation("approve", "api/approve", "request-approve")
        self.mutation("validate", "api/validate", "request-validate")

        with self.controller.store.summary_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            row = list(csv.DictReader(file, delimiter=";"))[-1]
        self.assertEqual(row["quality_valid"], "yes", row["quality_flags"])
        self.assertEqual(row["quality_flags"], "")
        self.assertTrue(row["qc_seconds"])
        self.assertTrue(row["download_transfer_seconds"])

    def test_untrusted_click_is_not_a_marker(self):
        self.emit("cms.approve.intent", {"trusted": False})
        trial = self.controller._trial
        self.assertNotIn("approve.intent", trial["markers"])
        self.assertIn("untrusted_dom_event_ignored", trial["quality_flags"])


class CollectorServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        config = deepcopy(DEFAULT_CONFIG)
        config["trial"]["exit_after_finish"] = False
        self.controller = BenchmarkController(config, Path(self.temp.name))
        self.server, self.thread = start_server("127.0.0.1", 0, self.controller)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.controller.close()
        self.temp.cleanup()

    def post(self, path, payload, token=""):
        headers = {
            "Content-Type": "application/json",
            "X-SubNexus-Benchmark": "1",
        }
        if token:
            headers["X-SubNexus-Session"] = token
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_handshake_and_authenticated_event_batch(self):
        status, hello = self.post(
            "/api/v1/hello",
            {"extension_id": "test", "extension_version": "0.1.0"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(hello["session_token"])

        self.controller.begin_trial("unit_test")
        status, response = self.post(
            "/api/v1/events",
            {
                "events": [
                    {
                        "sequence": 42,
                        "name": "cms.edit.intent",
                        "source_timestamp_ms": time.time() * 1000,
                        "data": {"trusted": True},
                    }
                ]
            },
            token=hello["session_token"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["accepted_sequences"], [42])
        self.assertIn("edit_1.intent", self.controller._trial["markers"])

    def test_event_batch_rejects_invalid_token(self):
        with self.assertRaises(HTTPError) as caught:
            self.post("/api/v1/events", {"events": []}, token="wrong")
        self.assertEqual(caught.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
