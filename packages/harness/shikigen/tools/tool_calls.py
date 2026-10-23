"""将同步和跨循环调用转交给工具库所属的事件循环。"""

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future


class _SubmittedCall[T]:
  def __init__(
    self,
    loop: asyncio.AbstractEventLoop,
    operation: Callable[[], Awaitable[T]],
    check_open: Callable[[], None],
  ):
    self.future: Future[T] = Future()
    self._loop = loop
    self._task: asyncio.Task[T] | None = None
    loop.call_soon_threadsafe(self._start, operation, check_open)

  def _start(self, operation, check_open):
    try:
      check_open()

      async def run():
        return await operation()

      self._task = self._loop.create_task(run())
      self._task.add_done_callback(self._finished)
    except Exception as error:
      self.future.set_exception(error)

  def _finished(self, task: asyncio.Task[T]):
    if task.cancelled():
      self.future.set_exception(asyncio.CancelledError())
    elif (error := task.exception()) is not None:
      self.future.set_exception(error)
    else:
      self.future.set_result(task.result())

  def cancel(self):
    # 不取消 concurrent Future：它必须在实际任务完成清理后才结束。
    self._loop.call_soon_threadsafe(self._cancel)

  def _cancel(self):
    if self._task is not None and not self._task.done() and not self._task.cancelling():
      self._task.cancel()

  def wait(self) -> T:
    while True:
      try:
        # Windows 的无限期 Condition.wait 会延迟主线程处理 Ctrl+C。
        # 短等待只用于响应中断，执行预算仍由 ToolExecutor 统一控制。
        return self.future.result(timeout=0.1)
      except TimeoutError:
        if self.future.done():
          return self.future.result()


class ToolCallBridge:
  def __init__(self):
    self._loop: asyncio.AbstractEventLoop | None = None
    self._closed = False

  def bind(self):
    loop = asyncio.get_running_loop()
    if self._loop is None:
      self._loop = loop
    elif self._loop is not loop:
      raise RuntimeError("Tool library configuration belongs to another event loop")

  def check_open(self):
    if self._closed:
      raise RuntimeError("Tool library is closed")

  def close(self):
    self.bind()
    self._closed = True

  def _submit[T](self, operation: Callable[[], Awaitable[T]]) -> _SubmittedCall[T]:
    self.check_open()
    if self._loop is None or not self._loop.is_running():
      raise RuntimeError("Tool library event loop is not running")
    return _SubmittedCall(self._loop, operation, self.check_open)

  async def call[T](self, operation: Callable[[], Awaitable[T]]) -> T:
    self.check_open()
    if self._loop is None:
      self.bind()
    if asyncio.get_running_loop() is self._loop:
      return await operation()
    submitted = self._submit(operation)
    future = asyncio.wrap_future(submitted.future)
    try:
      # 调用方的取消通过任务传递，不能提前结束等待结果的 Future。
      return await asyncio.shield(future)
    except asyncio.CancelledError:
      submitted.cancel()
      while not future.done():
        try:
          await asyncio.shield(future)
        except (asyncio.CancelledError, Exception):
          pass
      # 取走任务异常，避免调用方取消后产生未读取异常的日志。
      if not future.cancelled():
        future.exception()
      raise

  def call_sync[T](self, operation: Callable[[], Awaitable[T]]) -> T:
    self.check_open()
    try:
      loop = asyncio.get_running_loop()
    except RuntimeError:
      loop = None
    if loop is not None and loop is self._loop:
      raise RuntimeError("Use ainvoke() in the tool library event loop")
    submitted = self._submit(operation)
    try:
      return submitted.wait()
    except KeyboardInterrupt:
      submitted.cancel()
      try:
        submitted.wait()
      except (asyncio.CancelledError, Exception):
        pass
      raise
