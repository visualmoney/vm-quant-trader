import threading

from vmtrader.broker.kis.worker import TaskQueueWorker


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
    Tests that repeated starts do not spawn a second thread and that
    stopping an unstarted worker is a no-op.
    """
    worker = TaskQueueWorker()
    worker.stop()
    worker.start()
    first = worker.thread
    worker.start()
    assert worker.thread is first
    worker.stop()
    assert worker.thread is None
