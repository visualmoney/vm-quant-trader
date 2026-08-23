import threading

import pytest

from vmtrader.broker.live.worker import TaskQueueWorker


def _appender(sink):
    """
    Build a runnable that records the task's payload.

    Parameters
    ----------
    sink : `list`
        The list to append payloads to.

    Returns
    -------
    `callable`
        The runnable.
    """
    def run(task):
        sink.append(task['payload'])
    return run


def test_tasks_run_in_the_order_they_were_posted():
    """
    Tests FIFO ordering.

    With one thread there is no interleaving to test, so ordering is
    the whole contract: a later poll never books before an earlier one.
    """
    seen = []
    worker = TaskQueueWorker()
    worker.start()
    for i in range(50):
        worker.post_task({'runnable': _appender(seen), 'payload': i})
    worker.stop()
    assert seen == list(range(50))


def test_stop_runs_everything_already_queued():
    """
    Tests that shutdown drains rather than truncates.

    The poison pill is queued behind the pending tasks, so a fill that
    was collected but not yet handed back is not dropped.
    """
    seen = []
    worker = TaskQueueWorker()
    worker.start()
    for i in range(20):
        worker.post_task({'runnable': _appender(seen), 'payload': i})
    worker.stop()
    assert len(seen) == 20


def test_join_tasks_is_a_drain_barrier():
    """
    Tests that join_tasks waits for the queue without stopping the
    worker, which is how the main thread synchronises mid-cycle.
    """
    seen = []
    worker = TaskQueueWorker()
    worker.start()
    for i in range(10):
        worker.post_task({'runnable': _appender(seen), 'payload': i})
    assert worker.join_tasks(timeout=5.0) is True
    assert len(seen) == 10
    assert worker.is_running() is True
    worker.stop()


def test_a_failing_task_does_not_kill_the_worker():
    """
    Tests that one task raising leaves the rest to run and reports the
    exception, since one order failing to poll is not a reason to
    abandon the others.
    """
    seen = []
    errors = []
    worker = TaskQueueWorker(on_error=errors.append)
    worker.start()

    def explode(task):
        raise RuntimeError('venue timed out')

    worker.post_task({'runnable': explode})
    for i in range(3):
        worker.post_task({'runnable': _appender(seen), 'payload': i})
    worker.stop()

    assert seen == [0, 1, 2]
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


def test_worker_thread_is_gone_after_stop():
    """
    Tests that the worker leaves no thread behind.

    The worker is scoped to one rebalance cycle; a live process must
    not accumulate threads across cycles.
    """
    before = threading.active_count()
    worker = TaskQueueWorker()
    worker.start()
    assert worker.is_running() is True
    worker.stop(timeout=5.0)
    assert worker.is_running() is False
    assert threading.active_count() == before


def test_start_is_idempotent_and_stop_is_safe_when_not_running():
    """
    Tests that repeated starts do not spawn a second thread, and that
    an unstarted worker absorbs stop and drain calls rather than
    raising or blocking on a queue nobody is consuming.
    """
    worker = TaskQueueWorker()
    assert worker.join_tasks() is True
    worker.stop()
    worker.start()
    first = worker.get_thread()
    worker.start()
    assert worker.get_thread() is first
    worker.stop()
    assert worker.get_thread() is None


def test_on_terminate_fires_once_the_queue_is_drained():
    """
    Tests that the termination hook runs after the last task, not
    alongside it.

    The hook is the worker's only chance to report on a cycle it has
    finished, so what it observes must be the whole queue.
    """
    seen = []
    ended = []
    worker = TaskQueueWorker(on_terminate=lambda: ended.append(list(seen)))
    worker.start()
    for i in range(5):
        worker.post_task({'runnable': _appender(seen), 'payload': i})
    worker.stop()

    assert ended == [[0, 1, 2, 3, 4]]


def test_a_raising_on_terminate_does_not_strand_the_thread():
    """
    Tests that a failing termination hook still lets the thread die.

    The hook runs outside the queue loop, so an exception there must
    not skip the exit: a non-daemon thread left alive holds up
    interpreter shutdown, and the cycle never ends.
    """
    before = threading.active_count()
    errors = []

    def explode():
        raise RuntimeError('terminate hook failed')

    worker = TaskQueueWorker(on_error=errors.append, on_terminate=explode)
    worker.start()
    worker.stop(timeout=5.0)

    assert worker.is_running() is False
    assert worker.get_thread() is None
    assert threading.active_count() == before
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


def test_post_task_rejects_a_task_that_cannot_be_run():
    """
    Tests that a malformed task fails at the call site.

    None is the shutdown sentinel, so a caller must never post one, and
    a task with no callable would only fail later on the worker thread,
    where the traceback is detached from whoever posted it.
    """
    worker = TaskQueueWorker()

    with pytest.raises(ValueError):
        worker.post_task(None)
    with pytest.raises(ValueError):
        worker.post_task({'payload': 1})
    with pytest.raises(ValueError):
        worker.post_task({'runnable': 'not callable'})


def test_join_tasks_reports_whether_the_queue_drained():
    """
    Tests both halves of the drain barrier's return value.

    The main thread books results on the strength of this answer, so a
    queue that has not drained must say so rather than let the caller
    read a half-filled buffer.
    """
    seen = []
    release = threading.Event()
    worker = TaskQueueWorker()
    worker.start()

    def blocked(task):
        release.wait(5.0)
        seen.append(task['payload'])

    worker.post_task({'runnable': blocked, 'payload': 0})
    try:
        assert worker.join_tasks(timeout=0.05) is False
    finally:
        release.set()

    assert worker.join_tasks() is True
    assert seen == [0]
    worker.stop()


def test_failures_are_absorbed_when_no_on_error_is_registered():
    """
    Tests the default configuration, where both callbacks are absent.

    'on_error' is optional, so neither a task raising nor the
    termination hook raising may depend on it being there: the queue
    must still drain and the thread must still end.
    """
    before = threading.active_count()
    seen = []

    def explode(task):
        raise RuntimeError('venue timed out')

    def explode_on_terminate():
        raise RuntimeError('terminate hook failed')

    worker = TaskQueueWorker(on_terminate=explode_on_terminate)
    worker.start()
    worker.post_task({'runnable': explode})
    for i in range(3):
        worker.post_task({'runnable': _appender(seen), 'payload': i})
    worker.stop(timeout=5.0)

    assert seen == [0, 1, 2]
    assert worker.is_running() is False
    assert threading.active_count() == before


def test_stop_reports_a_thread_that_would_not_end():
    """
    Tests that a shutdown which times out says so, and leaves the
    worker in a state that admits it.

    A stuck poll must not be able to make the worker look finished:
    the reference is kept, so 'is_running()' stays truthful and
    'start()' cannot raise a second consumer that would race the first
    one for the queue.
    """
    release = threading.Event()
    worker = TaskQueueWorker(name='stuck')
    worker.start()
    stuck = worker.get_thread()
    worker.post_task({'runnable': lambda task: release.wait(5.0)})

    try:
        assert worker.stop(timeout=0.05) is False
        assert worker.is_running() is True
        assert worker.get_thread() is stuck
        worker.start()
        assert worker.get_thread() is stuck
    finally:
        release.set()

    assert worker.stop(timeout=5.0) is True
    assert worker.get_thread() is None


def test_join_tasks_does_not_call_an_unconsumed_queue_drained():
    """
    Tests that the drain barrier looks at the queue, not at the thread.

    Nothing runs a task posted after the worker has stopped, so
    answering True there would let the main thread book results that
    were never collected.
    """
    worker = TaskQueueWorker()
    worker.start()
    assert worker.stop() is True

    worker.post_task({'runnable': lambda task: None})
    assert worker.join_tasks() is False
    assert worker.join_tasks(timeout=0.05) is False
