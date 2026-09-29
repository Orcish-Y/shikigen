"""运行数据的进程级所有权；旁路文件始终保留，原生锁才是占用权威。"""

import os
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from portalocker import LockFlags
from portalocker.exceptions import AlreadyLocked
from portalocker.portalocker import BaseLocker

from shikigen.app_config import AppConfig
from shikigen.runtime.data_paths import UnsupportedRuntimeDataPath, resolve_data_path


class RuntimeDataInUse(RuntimeError):
  """另一个 runtime 正在使用所请求的数据。"""


def _locker() -> BaseLocker:
  if os.name == "nt":
    from portalocker.portalocker import Win32Locker

    return Win32Locker()
  from portalocker.portalocker import PosixLocker

  return PosixLocker()


@contextmanager
def own_runtime_data(config: AppConfig) -> Generator[AppConfig]:
  """在任何数据库打开前取得全部锁，失败时按逆序回滚。"""
  chat_database_path = resolve_data_path(config.database.path)
  resources = [chat_database_path]
  checkpoint = None
  if config.checkpointer.type == "sqlite":
    checkpoint = resolve_data_path(config.checkpointer.path)
    resources.append(checkpoint)
  paths = {resource.identity: resource.path for resource in resources}
  for path in paths.values():
    if path.name.lower().endswith(".runtime.lock"):
      raise UnsupportedRuntimeDataPath(
        f"Unsupported runtime data path: {path} (reserved lock filename)"
      )
  resolved_config = config.model_copy(
    update={
      "database": config.database.model_copy(
        update={"path": str(chat_database_path.path)}
      ),
      "checkpointer": config.checkpointer.model_copy(
        update={"path": str(checkpoint.path)} if checkpoint else {}
      ),
    }
  )
  with ExitStack() as stack:
    acquired: set[tuple[int, int]] = set()
    for path in sorted(
      paths.values(), key=lambda path: (os.path.normcase(path), str(path))
    ):
      lock_path = resolve_data_path(Path(str(path) + ".runtime.lock")).path
      file = stack.enter_context(lock_path.open("a+b"))
      os.set_inheritable(file.fileno(), False)
      info = os.fstat(file.fileno())
      identity = (info.st_dev, info.st_ino)
      # 新数据库尚无文件身份；实际创建的旁路文件也能统一大小写别名。
      if identity in acquired:
        continue
      locker = _locker()
      try:
        locker.lock(file, LockFlags.EXCLUSIVE | LockFlags.NON_BLOCKING)
      except AlreadyLocked as error:
        raise RuntimeDataInUse(f"Runtime data is in use: {path}") from error
      stack.callback(locker.unlock, file)
      acquired.add(identity)
    yield resolved_config
