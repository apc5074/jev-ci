"""Bounded concurrency, retries, and spend controls for semantic scoring (P5-07).

Shared by Jev and GPT clients. Does **not** change scientific scores — only
scheduling, retry transport, and cash-spend gates.

Rules (overall.md §21 / phase5 P5-07):

- Max **16** concurrent in-flight requests per scheduler instance.
- Retry only HTTP **429 / 500 / 502 / 503 / 529** and network timeouts.
- At most **3** retries after the first attempt (4 attempts total).
- Backoff **1s / 2s / 4s**, or longer when ``Retry-After`` is supplied.
- Final failure is left unscored (caller persists failure); never invent a score.
- Optional estimated spending ceiling reserves cost **before** each paid call (separate from ranking scores).
- In-flight requests with the same cache key are coalesced.
- Optional ``max_rpm`` queues starts so a free/new-account rate limit is
  respected instead of silently switching providers.
"""

from __future__ import annotations

import re
import math
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Mapping, Sequence, TypeVar

MAX_CONCURRENCY = 16
MAX_RETRIES = 3  # after the first attempt
BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 529})

_HTTP_STATUS_RE = re.compile(r"HTTP\s+(\d{3})", re.IGNORECASE)
_RETRY_AFTER_RE = re.compile(r"Retry-After['\"=\s:]+(\d+(?:\.\d+)?)", re.IGNORECASE)
_RATE_LIMIT_RE = re.compile(r"rate limit|temporar(?:y|ily) limited", re.IGNORECASE)

T = TypeVar("T")


class SchedulerError(Exception):
    """Scheduler / spend-gate failure."""


class RetryableError(Exception):
    """Transient provider/transport error eligible for retry."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.retry_after_s = retry_after_s


class SpendCeilingExceeded(SchedulerError):
    """Hard spending ceiling would be exceeded by the next paid call."""


@dataclass
class SpendEstimate:
    total_jobs: int
    already_cached: int
    remaining_paid: int
    estimated_input_tokens: int
    estimated_list_price_usd: float
    estimated_platform_fee_usd: float
    estimated_total_usd: float
    spend_ceiling_usd: float | None
    within_ceiling: bool


@dataclass
class SpendController:
    """Cash-spend gate (orthogonal to scientific scores)."""

    ceiling_usd: float | None = None
    spent_usd: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        for value in (self.ceiling_usd, self.spent_usd):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise SchedulerError("spend values must be finite and nonnegative")

    def remaining_budget(self) -> float | None:
        if self.ceiling_usd is None:
            return None
        with self._lock:
            return max(0.0, float(self.ceiling_usd) - float(self.spent_usd))

    def allow_paid_call(self, estimated_cost_usd: float) -> None:
        if not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0:
            raise SchedulerError("estimated cost must be finite and nonnegative")
        with self._lock:
            projected = float(self.spent_usd) + max(0.0, float(estimated_cost_usd))
            if self.ceiling_usd is not None and projected > self.ceiling_usd + 1e-12:
                raise SpendCeilingExceeded(
                    f"spend ceiling ${self.ceiling_usd:.6f} would be exceeded "
                    f"(spent=${self.spent_usd:.6f}, next≈${estimated_cost_usd:.6f})"
                )

            # Reserve atomically before dispatch, including concurrent attempts.
            self.spent_usd = projected

    def settle(self, estimate: float, actual: float | None) -> None:
        # Unknown/failed charges retain their reservation conservatively.
        if actual is None:
            return
        if not math.isfinite(actual) or actual < 0:
            raise SchedulerError("actual cost must be finite and nonnegative")
        with self._lock:
            self.spent_usd += actual - estimate

    def record_actual(self, actual_cost_usd: float | None) -> None:
        if actual_cost_usd is None:
            return
        with self._lock:
            self.spent_usd += max(0.0, float(actual_cost_usd))


@dataclass(frozen=True)
class ScoreJob:
    """One shortlist candidate to score (or skip if already cached)."""

    job_id: str
    cache_key: str
    estimate_input_tokens: int = 0
    estimate_cost_usd: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class JobOutcome(Generic[T]):
    job_id: str
    cache_key: str
    ok: bool
    from_cache: bool
    attempts: int
    result: T | None = None
    error: str | None = None
    skipped_spend_ceiling: bool = False


def parse_http_status(message: str) -> int | None:
    match = _HTTP_STATUS_RE.search(message)
    if not match:
        return None
    return int(match.group(1))


def parse_retry_after_seconds(message: str) -> float | None:
    match = _RETRY_AFTER_RE.search(message)
    if not match:
        return None
    return float(match.group(1))


def is_network_timeout_message(message: str) -> bool:
    text = message.lower()
    return "timed out" in text or "timeout" in text


def classify_retryable(exc: BaseException) -> RetryableError | None:
    """Return a RetryableError if ``exc`` should be retried, else None."""
    if isinstance(exc, RetryableError):
        if exc.http_status in RETRYABLE_HTTP_STATUSES or (
            exc.http_status is None and is_network_timeout_message(str(exc))
        ):
            return exc
        return None
    message = str(exc)
    status = parse_http_status(message)
    retry_after = parse_retry_after_seconds(message)
    if status in RETRYABLE_HTTP_STATUSES:
        return RetryableError(
            message, http_status=status, retry_after_s=retry_after
        )
    if status is None and is_network_timeout_message(message):
        return RetryableError(message, http_status=None, retry_after_s=retry_after)
    name = type(exc).__name__
    if name in {"TimeoutError", "URLError"} and is_network_timeout_message(message):
        return RetryableError(message, retry_after_s=retry_after)
    return None


def backoff_seconds(
    attempt_index: int,
    *,
    retry_after_s: float | None = None,
) -> float:
    """``attempt_index`` is 0 for the first retry (after the initial failure)."""
    base = BACKOFF_SECONDS[min(attempt_index, len(BACKOFF_SECONDS) - 1)]
    if retry_after_s is None:
        return base
    return max(base, float(retry_after_s))


def with_retries(
    fn: Callable[[], T],
    *,
    max_retries: int = MAX_RETRIES,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_attempt: Callable[[int, BaseException | None], None] | None = None,
) -> T:
    """Run ``fn`` with the P5-07 retry policy. Non-retryable errors propagate."""
    if not 0 <= max_retries <= MAX_RETRIES:
        raise SchedulerError(f"max_retries must be between 0 and 3, got {max_retries}")
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            if on_attempt is not None:
                on_attempt(attempt, None)
            return fn()
        except BaseException as exc:  # noqa: BLE001 — classify then decide
            last_exc = exc
            retryable = classify_retryable(exc)
            if retryable is None or attempt >= max_retries:
                if on_attempt is not None:
                    on_attempt(attempt, exc)
                raise
            delay = backoff_seconds(
                attempt, retry_after_s=retryable.retry_after_s
            )
            if on_attempt is not None:
                on_attempt(attempt, retryable)
            sleep_fn(delay)
    assert last_exc is not None
    raise last_exc


def estimate_spend(
    jobs: Sequence[ScoreJob],
    *,
    cached_keys: set[str] | None = None,
    spend_ceiling_usd: float | None = None,
) -> SpendEstimate:
    cached = cached_keys or set()
    remaining = [j for j in jobs if j.cache_key not in cached]
    tokens = sum(max(0, j.estimate_input_tokens) for j in remaining)
    list_price = sum(max(0.0, j.estimate_cost_usd) for j in remaining)
    within = True if spend_ceiling_usd is None else list_price <= float(spend_ceiling_usd)
    return SpendEstimate(
        total_jobs=len(jobs),
        already_cached=len(jobs) - len(remaining),
        remaining_paid=len(remaining),
        estimated_input_tokens=tokens,
        estimated_list_price_usd=list_price,
        estimated_platform_fee_usd=0.0,
        estimated_total_usd=list_price,
        spend_ceiling_usd=spend_ceiling_usd,
        within_ceiling=within,
    )


class _RateLimiter:
    """Optional rolling RPM gate (queue/pause; never switches providers)."""

    def __init__(self, max_rpm: int | None) -> None:
        self.max_rpm = max_rpm
        self._lock = threading.Lock()
        self._starts: list[float] = []

    def acquire(self, sleep_fn: Callable[[float], None]) -> None:
        if self.max_rpm is None or self.max_rpm <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                window = now - 60.0
                self._starts = [t for t in self._starts if t >= window]
                if len(self._starts) < self.max_rpm:
                    self._starts.append(now)
                    return
                wait = 60.0 - (now - self._starts[0]) + 0.01
            sleep_fn(max(0.01, wait))


def run_score_batch(
    jobs: Sequence[ScoreJob],
    *,
    worker: Callable[[ScoreJob], T],
    is_cached: Callable[[ScoreJob], bool],
    max_concurrency: int = MAX_CONCURRENCY,
    max_rpm: int | None = None,
    spend: SpendController | None = None,
    max_retries: int = MAX_RETRIES,
    sleep_fn: Callable[[float], None] = time.sleep,
    record_spend: Callable[[T], float | None] | None = None,
) -> list[JobOutcome[T]]:
    """Run jobs with concurrency ≤16, in-flight cache-key dedupe, retries, spend gate.

    Cached jobs are resolved outside the pool (no paid call). Remaining jobs
    share a pool of size ``min(max_concurrency, MAX_CONCURRENCY)``.
    """
    if max_concurrency < 1:
        raise SchedulerError(f"max_concurrency must be >= 1, got {max_concurrency}")
    workers = min(int(max_concurrency), MAX_CONCURRENCY)

    spend_ctrl = spend or SpendController()
    limiter = _RateLimiter(max_rpm)
    lock = threading.Lock()
    inflight: dict[str, Future[JobOutcome[T]]] = {}
    outcomes: dict[str, JobOutcome[T]] = {}

    def _finish_cached(job: ScoreJob) -> None:
        try:
            result = worker(job)
            outcomes[job.job_id] = JobOutcome(
                job_id=job.job_id,
                cache_key=job.cache_key,
                ok=True,
                from_cache=True,
                attempts=0,
                result=result,
            )
        except Exception as exc:  # noqa: BLE001
            outcomes[job.job_id] = JobOutcome(
                job_id=job.job_id,
                cache_key=job.cache_key,
                ok=False,
                from_cache=True,
                attempts=0,
                error=str(exc),
            )

    outstanding: list[ScoreJob] = []
    for job in jobs:
        if is_cached(job):
            _finish_cached(job)
        else:
            outstanding.append(job)

    def _execute(job: ScoreJob) -> JobOutcome[T]:
        attempts = {"n": 0}

        def _attempt() -> T:
            limiter.acquire(sleep_fn)
            spend_ctrl.allow_paid_call(job.estimate_cost_usd)
            attempts["n"] += 1
            result = worker(job)
            actual = record_spend(result) if record_spend is not None else None
            spend_ctrl.settle(job.estimate_cost_usd, actual)
            return result

        try:
            result = with_retries(
                _attempt, max_retries=max_retries, sleep_fn=sleep_fn
            )
            return JobOutcome(
                job_id=job.job_id,
                cache_key=job.cache_key,
                ok=True,
                from_cache=False,
                attempts=attempts["n"],
                result=result,
            )
        except SpendCeilingExceeded as exc:
            return JobOutcome(
                job_id=job.job_id,
                cache_key=job.cache_key,
                ok=False,
                from_cache=False,
                attempts=attempts["n"],
                error=str(exc),
                skipped_spend_ceiling=True,
            )
        except Exception as exc:  # noqa: BLE001
            return JobOutcome(
                job_id=job.job_id,
                cache_key=job.cache_key,
                ok=False,
                from_cache=False,
                attempts=attempts["n"],
                error=str(exc),
            )

    if outstanding:
        with ThreadPoolExecutor(max_workers=workers) as executor:

            def _submit(job: ScoreJob) -> Future[JobOutcome[T]]:
                with lock:
                    existing = inflight.get(job.cache_key)
                    if existing is not None:
                        return existing

                    # Keep completed futures for this batch too: a fast worker
                    # must not allow a duplicate submitted later to pay again.
                    fut = executor.submit(_execute, job)
                    inflight[job.cache_key] = fut
                    return fut

            futures = [_submit(job) for job in outstanding]
            seen_futs: dict[Future[JobOutcome[T]], list[ScoreJob]] = {}
            for job, fut in zip(outstanding, futures):
                seen_futs.setdefault(fut, []).append(job)

            for fut, group in seen_futs.items():
                outcome = fut.result()
                for job in group:
                    outcomes[job.job_id] = JobOutcome(
                        job_id=job.job_id,
                        cache_key=job.cache_key,
                        ok=outcome.ok,
                        from_cache=outcome.from_cache,
                        attempts=outcome.attempts,
                        result=outcome.result,
                        error=outcome.error,
                        skipped_spend_ceiling=outcome.skipped_spend_ceiling,
                    )

    return [outcomes[j.job_id] for j in jobs if j.job_id in outcomes]
