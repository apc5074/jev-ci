"""P5-07: concurrency, retries, spend ceiling, in-flight dedupe."""

from __future__ import annotations

import threading
import unittest
from typing import Any

from src.semantic_scheduler import (
    MAX_CONCURRENCY,
    MAX_RETRIES,
    BACKOFF_SECONDS,
    JobOutcome,
    RetryableError,
    ScoreJob,
    SpendCeilingExceeded,
    SpendController,
    classify_retryable,
    estimate_spend,
    run_score_batch,
    with_retries,
)


class RetryPolicyTests(unittest.TestCase):
    def test_backoff_sequence_and_retry_after(self) -> None:
        self.assertEqual(BACKOFF_SECONDS, (1.0, 2.0, 4.0))
        self.assertEqual(MAX_RETRIES, 3)
        self.assertEqual(MAX_CONCURRENCY, 16)

    def test_retries_429_with_backoff(self) -> None:
        sleeps: list[float] = []
        calls = {"n": 0}

        def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 4:
                raise RetryableError("HTTP 429 rate limit", http_status=429)
            return "ok"

        out = with_retries(flaky, sleep_fn=sleeps.append)
        self.assertEqual(out, "ok")
        self.assertEqual(calls["n"], 4)
        self.assertEqual(sleeps, [1.0, 2.0, 4.0])

    def test_respects_longer_retry_after(self) -> None:
        sleeps: list[float] = []
        calls = {"n": 0}

        def flaky() -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RetryableError(
                    "HTTP 429", http_status=429, retry_after_s=5.0
                )
            return "ok"

        with_retries(flaky, sleep_fn=sleeps.append)
        self.assertEqual(sleeps, [5.0])

    def test_non_retryable_raises_immediately(self) -> None:
        calls = {"n": 0}

        def bad() -> str:
            calls["n"] += 1
            raise RuntimeError("HTTP 400 bad request")

        with self.assertRaises(RuntimeError):
            with_retries(bad, sleep_fn=lambda _s: None)
        self.assertEqual(calls["n"], 1)

    def test_exhausted_retries_no_score_path(self) -> None:
        calls = {"n": 0}

        def always() -> str:
            calls["n"] += 1
            raise RetryableError("HTTP 503", http_status=503)

        with self.assertRaises(RetryableError):
            with_retries(always, sleep_fn=lambda _s: None)
        self.assertEqual(calls["n"], MAX_RETRIES + 1)

    def test_classify_timeout_message(self) -> None:
        err = classify_retryable(TimeoutError("Jev transport error: timed out"))
        self.assertIsInstance(err, RetryableError)


class SpendAndEstimateTests(unittest.TestCase):
    def test_estimate_skips_cached(self) -> None:
        jobs = [
            ScoreJob("a", "ka", estimate_input_tokens=100, estimate_cost_usd=0.01),
            ScoreJob("b", "kb", estimate_input_tokens=100, estimate_cost_usd=0.01),
        ]
        est = estimate_spend(jobs, cached_keys={"ka"}, spend_ceiling_usd=1.0)
        self.assertEqual(est.already_cached, 1)
        self.assertEqual(est.remaining_paid, 1)
        self.assertTrue(est.within_ceiling)

    def test_spend_ceiling_blocks_paid_call(self) -> None:
        spend = SpendController(ceiling_usd=0.05)
        spend.record_actual(0.04)
        with self.assertRaises(SpendCeilingExceeded):
            spend.allow_paid_call(0.02)


class ConcurrencyTests(unittest.TestCase):
    def test_concurrency_never_exceeds_cap(self) -> None:
        current = {"n": 0}
        peak = {"n": 0}
        lock = threading.Lock()

        def worker(job: ScoreJob) -> str:
            with lock:
                current["n"] += 1
                peak["n"] = max(peak["n"], current["n"])
            # Tiny critical section simulation
            import time

            time.sleep(0.02)
            with lock:
                current["n"] -= 1
            return job.job_id

        jobs = [
            ScoreJob(job_id=f"j{i}", cache_key=f"k{i}", estimate_cost_usd=0.0)
            for i in range(40)
        ]
        outcomes = run_score_batch(
            jobs,
            worker=worker,
            is_cached=lambda _j: False,
            max_concurrency=16,
            max_retries=0,
            sleep_fn=lambda _s: None,
        )
        self.assertEqual(len(outcomes), 40)
        self.assertTrue(all(o.ok for o in outcomes))
        self.assertLessEqual(peak["n"], MAX_CONCURRENCY)

    def test_inflight_dedupe_same_cache_key(self) -> None:
        calls = {"n": 0}
        lock = threading.Lock()

        def worker(job: ScoreJob) -> str:
            with lock:
                calls["n"] += 1
            import time

            time.sleep(0.05)
            return "shared"

        jobs = [
            ScoreJob(job_id="a", cache_key="same", estimate_cost_usd=0.0),
            ScoreJob(job_id="b", cache_key="same", estimate_cost_usd=0.0),
            ScoreJob(job_id="c", cache_key="same", estimate_cost_usd=0.0),
        ]
        outcomes = run_score_batch(
            jobs,
            worker=worker,
            is_cached=lambda _j: False,
            max_concurrency=16,
            max_retries=0,
            sleep_fn=lambda _s: None,
        )
        self.assertEqual(calls["n"], 1)
        self.assertEqual([o.result for o in outcomes], ["shared", "shared", "shared"])

    def test_resume_skips_cached_paid_path(self) -> None:
        paid = {"n": 0}

        def worker(job: ScoreJob) -> str:
            paid["n"] += 1
            return "paid"

        jobs = [
            ScoreJob("a", "ka"),
            ScoreJob("b", "kb"),
        ]
        outcomes = run_score_batch(
            jobs,
            worker=worker,
            is_cached=lambda j: j.cache_key == "ka",
            max_concurrency=4,
            max_retries=0,
            sleep_fn=lambda _s: None,
        )
        self.assertEqual(paid["n"], 2)  # cached path still calls worker once to load
        self.assertTrue(outcomes[0].from_cache)
        self.assertFalse(outcomes[1].from_cache)

    def test_failed_job_has_no_result_score(self) -> None:
        def worker(_job: ScoreJob) -> str:
            raise RetryableError("HTTP 500", http_status=500)

        jobs = [ScoreJob("a", "ka")]
        outcomes = run_score_batch(
            jobs,
            worker=worker,
            is_cached=lambda _j: False,
            max_concurrency=1,
            max_retries=1,
            sleep_fn=lambda _s: None,
        )
        self.assertEqual(len(outcomes), 1)
        self.assertFalse(outcomes[0].ok)
        self.assertIsNone(outcomes[0].result)
        self.assertIsNotNone(outcomes[0].error)

    def test_spend_ceiling_skips_without_score(self) -> None:
        spend = SpendController(ceiling_usd=0.0)

        def worker(_job: ScoreJob) -> str:
            return "should-not-run"

        jobs = [ScoreJob("a", "ka", estimate_cost_usd=0.01)]
        outcomes = run_score_batch(
            jobs,
            worker=worker,
            is_cached=lambda _j: False,
            max_concurrency=1,
            max_retries=0,
            spend=spend,
            sleep_fn=lambda _s: None,
        )
        self.assertFalse(outcomes[0].ok)
        self.assertTrue(outcomes[0].skipped_spend_ceiling)
        self.assertIsNone(outcomes[0].result)


if __name__ == "__main__":
    unittest.main()
