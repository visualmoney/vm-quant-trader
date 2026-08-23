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
import logging
import traceback

from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

# task 는 dict — 최소 "runnable"(호출가능) 키를 갖는다.
# runnable(task) 로 실행된다.
# 나머지 키는 runnable 이 소비할 페이로드
Task = Mapping[str, Any]


class TaskQueueWorker:
    """
    Runs posted tasks one at a time on a dedicated thread.
    입력 task 를 별도 스레드에서 차례로 수행하는 일꾼 (smtm 이식)

    Attributes
    ----------
    name : `str`
        Thread name, which shows up in logs and stack dumps.
    on_error : `callable`, optional
        Called with the exception when a task raises, or when
        'on_terminate' itself raises. The failure is logged either
        way; the worker abandons that task and takes the next one.
    on_terminate : `callable`, optional
        Called on the way out, once the stop sentinel has been read and
        the queue is drained. A task raising does not end the thread,
        so this does not fire for that. Without one, the exit is
        silent.
    """

    def __init__(
        self,
        name: str = 'fill-pump',
        on_error: Callable[[Exception], None] | None = None,
        on_terminate: Callable[[], None] | None = None,
    ):
        """
        initialize a worker thread with a FIFO queue.

        Parameters
        ----------
        name : `str`, optional
            Thread name, which shows up in logs and stack dumps.
        on_error : `callable`, optional
            Called with the exception when a task raises, or when
            'on_terminate' itself raises. The failure is logged either
            way; the worker abandons that task and takes the next one.
        on_terminate : `callable`, optional
            Called on the way out, once the stop sentinel has been read
            and the queue is drained. A task raising does not end the
            thread, so this does not fire for that. Without one, the
            exit is silent.
        """
        self.name = name
        self.on_error = on_error
        self.on_terminate = on_terminate
        self._task_queue = queue.Queue()
        self._thread = None

    def post_task(self, task: Task) -> None:
        """
        Queue a task for execution.

        Parameters
        ----------
        task : Task
            Must carry a 'runnable' key holding a callable, which is
            invoked with the task itself as its only argument.
        """
        if task is None:
            raise ValueError("task 는 None 이 될 수 없습니다. - None task 는 종료 센티넬")
        if not callable(task.get("runnable")):
            raise ValueError("task 에 호출 가능한 'runnable' 키 필요")
        self._task_queue.put(task)

    def __loop(self) -> None:
        """None 센티넬을 만날 때까지 큐를 소비한다."""
        while True:
            task = self._task_queue.get()
            try:
                # "None 센티넬을 만날 때
                if task is None:
                    break  # while 루프 종료
                # get runnable and call it with the task as argument
                runnable = task['runnable']
                try:
                    runnable(task)
                except Exception as error:  # noqa: BLE001
                    logger.error("Worker[%s] task Exception:\n%s",
                                 self.name, traceback.format_exc())
                    if self.on_error is not None:
                        self.on_error(error)
            finally:
                self._task_queue.task_done()  # task 완료 표시
        # end while

        if self.on_terminate is not None:
            try:
                self.on_terminate()
            except Exception as err:  # noqa: BLE001
                logger.error("Worker[%s] task Exception on terminate:\n%s",
                             self.name, traceback.format_exc())
                if self.on_error is not None:
                    self.on_error(err)

    def start(self) -> None:
        """
        Start the worker thread, if it is not already running.
        """
        # 이미 돌고 있으면 무동작 (멱등).
        if self._thread is not None:
            return

        self._thread = threading.Thread(
            target=self.__loop, name=self.name, daemon=False
        )
        self._thread.start()

    def stop(self, timeout: float | None = None) -> bool:
        """
        Finish the queued tasks, then shut the thread down.

        The poison pill goes to the back of the queue, so everything
        already posted runs first: a fill collected but not yet handed
        back is never dropped on shutdown.

        A thread that outlives the timeout keeps its reference, so
        'is_running()' still answers truthfully and 'start()' refuses
        to raise a second consumer against the same queue.

        Parameters
        ----------
        timeout : `float`, optional
            Seconds to wait for the thread to end. Without one, waits
            indefinitely.

        Returns
        -------
        `Boolean`
            Whether the thread ended. False only when a timeout was
            given and it expired with the thread still running.
        """
        if self._thread is None:
            return True
        thread = self._thread
        self._task_queue.put(None)
        thread.join(timeout)
        if thread.is_alive():
            logger.error("Worker[%s] %s초 안에 종료하지 못했다.", self.name, timeout)
            return False
        self._thread = None
        return True

    def join_tasks(self, timeout: float | None = None) -> bool:
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
        if self._thread is None:
            # 소비자가 없으면 기다려도 줄지 않는다 -- 큐가 비었는지로 답한다.
            return self._task_queue.unfinished_tasks == 0
        if timeout is None:
            self._task_queue.join()
            return True

        # 여기서 timeout 은 None 이 아니다 -- None 은 위에서 이미 반환했다.
        waited = 0.0
        step = 0.01
        while waited < timeout:
            if self._task_queue.unfinished_tasks == 0:
                return True
            self._thread.join(step)
            waited += step
        return self._task_queue.unfinished_tasks == 0

    def is_running(self) -> bool:
        """
        Return whether the worker thread is alive.

        Returns
        -------
        `Boolean`
            Whether the thread exists and is running.
        """
        return self._thread is not None and self._thread.is_alive()

    def get_thread(self) -> threading.Thread | None:
        """
        Return the worker thread, if it exists.

        Returns
        -------
        `threading.Thread` or `None`
            The thread, or None if it has not been started or has ended.
        """
        return self._thread
