import copy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import estrai_video as app

CONFIG = json.loads(Path(app.__file__).with_name("config.json").read_text())


def page(videos, more=False, cursor=100):
    return {"data": {"videos": videos, "has_more": more, "cursor": cursor,
                     "search_id": "search-1"}, "error": {"code": "ok"}}


class FakeClient:
    def __init__(self, pages, limit=100):
        self.pages, self.limit, self.calls, self.bodies = iter(pages), limit, 0, []

    def fetch(self, body, fields):
        if self.calls >= self.limit:
            raise app.BudgetReached()
        self.calls += 1
        self.bodies.append(copy.deepcopy(body))
        return next(self.pages)


class Tests(unittest.TestCase):
    def test_dates_cover_leap_day_and_month_ends_once(self):
        start, end = date(2024, 1, 31), date(2024, 4, 1)
        days = []
        for first, last in app.date_windows(start, end):
            a, b = (datetime.strptime(s, "%Y%m%d").date() for s in (first, last))
            self.assertLessEqual((b-a).days, 29)
            days.extend(a + timedelta(days=i) for i in range((b-a).days+1))
        self.assertEqual(days, [start + timedelta(days=i) for i in range((end-start).days+1)])
        self.assertIn(date(2024, 2, 29), days)

    def test_single_day(self):
        self.assertEqual(list(app.date_windows(date(2024, 1, 1), date(2024, 1, 1))), [("20240101", "20240101")])

    def test_invalid_configuration(self):
        for changes in [{"end_date": "2020-01-01"}, {"query": {}}, {"max_count": 101},
                        {"max_requests": True}, {"fields": ["username"]}, {"is_random": True}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                app.validate({**CONFIG, **changes})

    @patch.object(app.time, "sleep")
    def test_pagination_dedup_and_window_reset(self, sleep):
        client = FakeClient([page([{"id": 1}], True), page([{"id": 1}, {"id": 2}]), page([{"id": 3}])])
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "run"
            summary = app.collect(CONFIG, client, out)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["unique_videos"], 3)
            self.assertEqual(summary["completed_windows"], 2)
            self.assertEqual(client.bodies[1]["cursor"], 100)
            self.assertEqual(client.bodies[1]["search_id"], "search-1")
            self.assertNotIn("cursor", client.bodies[2])
            self.assertNotIn("search_id", client.bodies[2])
            self.assertEqual(len((out / "videos.jsonl").read_text().splitlines()), 3)

    @patch.object(app.time, "sleep")
    def test_empty_page_can_have_more(self, sleep):
        client = FakeClient([page([], True), page([{"id": 2}])])
        config = {**CONFIG, "end_date": CONFIG["start_date"]}
        with tempfile.TemporaryDirectory() as temp:
            summary = app.collect(config, client, Path(temp) / "run")
            self.assertEqual(summary["unique_videos"], 1)

    @patch.object(app.time, "sleep")
    def test_budget_retains_partial_results(self, sleep):
        client = FakeClient([page([{"id": 1}], True)], limit=1)
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "run"
            summary = app.collect(CONFIG, client, out)
            self.assertEqual(summary["status"], "partial_budget")
            self.assertTrue((out / "pages/000001.json").exists())

    @patch.object(app.time, "sleep")
    def test_stuck_cursor_is_reported(self, sleep):
        client = FakeClient([page([], True), page([], True)])
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "run"
            with self.assertRaises(RuntimeError):
                app.collect(CONFIG, client, out)
            self.assertEqual(json.loads((out / "riepilogo.json").read_text())["status"], "error")

    def test_dry_run_never_instantiates_client(self):
        with patch.object(app, "Client", side_effect=AssertionError("Rete vietata")):
            with patch("builtins.print"):
                self.assertEqual(app.main(["--dry-run"]), 0)

    def test_actual_http_body_is_json(self):
        client = app.Client("test-key", "test-secret", 10)
        client.token, client.expiry = "dummy", float("inf")
        response = Mock(ok=True, status_code=200)
        response.json.return_value = page([])
        client.session = Mock()
        client.session.post.return_value = response
        body = app.make_body(CONFIG, "20261004", "20261102")
        client.fetch(body, CONFIG["fields"])
        kwargs = client.session.post.call_args.kwargs
        self.assertEqual(kwargs["json"], body)
        self.assertNotIn("data", kwargs)

    def test_http_200_api_error_is_failure(self):
        client = app.Client("test-key", "test-secret", 10)
        client.token, client.expiry = "dummy", float("inf")
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"error": {"code": "invalid_params"}}
        client.session = Mock()
        client.session.post.return_value = response
        with self.assertRaisesRegex(RuntimeError, "invalid_params"):
            client.fetch({}, ["id"])

    def test_token_refresh_uses_server_expiry(self):
        client = app.Client("test-key", "test-secret", 10)
        response = Mock(ok=True)
        response.json.return_value = {"access_token": "dummy", "expires_in": 7200}
        client.session = Mock()
        client.session.post.return_value = response
        with patch.object(app.time, "monotonic", return_value=1000):
            client.authenticate()
        self.assertEqual(client.expiry, 8140)

    def test_429_stops_without_retry_loop(self):
        client = app.Client("test-key", "test-secret", 10)
        client.token, client.expiry = "dummy", float("inf")
        client.session = Mock()
        client.session.post.return_value = Mock(ok=False, status_code=429)
        with self.assertRaisesRegex(RuntimeError, "429"):
            client.fetch({}, ["id"])
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
