"""
A single worker thread that runs queued tasks in order.

Derived from smtm's 'worker.py' (MIT, msaltnet), by way of the same
pattern in vm-quant-lab. The shape is deliberately plain: one thread,
one FIFO queue, a poison pill to stop. That is what makes it reasonable
to introduce a thread here at all -- there is no lock to get wrong,
only an order to reason about.

Two differences from the original are intentional. The thread is not a
daemon and 'stop()' joins it, because this worker belongs to a single
rebalance cycle and must be gone before the cycle is accounted for; and
a task that raises reports through a callback instead of killing the
worker, since one order failing to poll is not a reason to abandon the
others.

What it must never do is touch the portfolio. The engine's accounting
is single-writer by design, so tasks collect results and the main
thread books them.
"""

import queue
import threading


class TaskQueueWorker:
    """
    Runs posted tasks one at a time on a dedicated thread.

    Parameters
    ----------
    name : `str`, optional
        Thread name, which shows up in logs and stack dumps.
    on_error : `callable`, optional
        Called with the exception when a task raises. Without one,
        exceptions are swallowed after the task is abandoned.
    """

    def __init__(self, name='fill-pump', on_error=None):
        self.name = name
        self.on_error = on_error
        self.task_queue = queue.Queue()
        self.thread = None

    def post_task(self, task):
        """
        Queue a task for execution.

        Parameters
        ----------
        task : `dict`
            Must carry a 'runnable' key holding a callable, which is
            invoked with the task itself as its only argument.
        """
        self.task_queue.put(task)

    def start(self):
        """
        Start the worker thread, if it is not already running.
        """
        if self.thread is not None:
            return

        def loop():
            while True:
                task = self.task_queue.get()
                try:
                    if task is None:
                        break
                    runnable = task['runnable']
                    runnable(task)
                except Exception as err:  # noqa: BLE001
                    if self.on_error is not None:
                        self.on_error(err)
                finally:
                    self.task_queue.task_done()

        self.thread = threading.Thread(
            target=loop, name=self.name, daemon=False
        )
        self.thread.start()

    def join_tasks(self, timeout=None):
        """
        Block until every queued task has been run.

        Used as a drain barrier before the main thread books results.

        Parameters
        ----------
        timeout : `float`, optional
            Seconds to wait. Without one, waits indefinitely.

        Returns
        -------
        `Boolean`
            Whether the queue drained within the timeout.
        """
        if self.thread is None:
            return True
        if timeout is None:
            self.task_queue.join()
            return True

        deadline = threading.TIMEOUT_MAX if timeout is None else timeout
        waited = 0.0
        step = 0.01
        while waited < deadline:
            if self.task_queue.unfinished_tasks == 0:
                return True
            self.thread.join(step)
            waited += step
        return self.task_queue.unfinished_tasks == 0

    def stop(self, timeout=None):
        """
        Finish the queued tasks, then shut the thread down.

        The poison pill goes to the back of the queue, so everything
        already posted runs first: a fill collected but not yet handed
        back is never dropped on shutdown.

        Parameters
        ----------
        timeout : `float`, optional
            Seconds to wait for the thread to end.
        """
        if self.thread is None:
            return
        thread = self.thread
        self.task_queue.put(None)
        thread.join(timeout)
        self.thread = None

    def is_running(self):
        """
        Return whether the worker thread is alive.

        Returns
        -------
        `Boolean`
            Whether the thread exists and is running.
        """
        return self.thread is not None and self.thread.is_alive()
