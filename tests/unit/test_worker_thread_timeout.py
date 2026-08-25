"""M7 — the UI thread must never wait for the worker pool for ever.

`ready_event.wait()` had no timeout: if the pool failed to start, the whole
window froze with no message. And the `pool_manager is None` fallback returned
silently, so the job simply disappeared. Both now fail loudly.
"""

import uuid

import pytest

from src.core.worker_thread import WorkerPoolThread


@pytest.fixture
def thread(qt_app):
    t = WorkerPoolThread()
    t._POOL_READY_TIMEOUT = 0.2  # keep the test fast; behaviour is identical
    yield t


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    return app


def test_await_pool_gives_up_instead_of_hanging(thread):
    """ready_event is never set: the call must return, not block."""
    import time

    started = time.monotonic()
    assert thread._await_pool("test") is False
    assert time.monotonic() - started < 5.0, "l'appel doit rendre la main"


def test_await_pool_rejects_a_missing_pool(thread):
    """Event set but the pool never materialised — previously a silent return."""
    thread.ready_event.set()
    thread.pool_manager = None
    assert thread._await_pool("test") is False


def test_submit_job_reports_the_failure_to_the_ui(thread):
    failures = []
    thread.job_failed.connect(lambda jid, msg: failures.append((jid, msg)))
    started = []
    thread.job_started.connect(lambda jid: started.append(jid))

    job_id = uuid.uuid4()
    thread.submit_job(job_id, [], None)

    assert failures, "l'échec doit remonter à l'interface, pas disparaître"
    assert failures[0][0] == str(job_id)
    assert "redémarrez" in failures[0][1].lower()
    assert not started, "un job non soumis ne doit pas être annoncé comme démarré"


def test_submit_finalize_reports_the_failure_to_the_ui(thread):
    failures = []
    thread.finalize_failed.connect(lambda jid, msg: failures.append((jid, msg)))

    job_id = uuid.uuid4()
    thread.submit_finalize(job_id, [], None)

    assert failures and failures[0][0] == str(job_id)
    assert "redémarrez" in failures[0][1].lower()


def test_the_timeout_is_generous_by_default():
    """Starting a ProcessPoolExecutor on a loaded Windows machine is slow: the
    bound exists to avoid a freeze, not to cut short a legitimate startup."""
    assert WorkerPoolThread._POOL_READY_TIMEOUT >= 15.0
