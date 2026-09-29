"""本机普通数据路径的校验和身份统一；不跟随链接来绕过校验。"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path


class UnsupportedRuntimeDataPath(ValueError):
  """数据路径不在当前平台支持范围内。"""


def _reject(path: Path, reason: str) -> None:
  raise UnsupportedRuntimeDataPath(f"Unsupported runtime data path: {path} ({reason})")


def _check_components(path: Path) -> None:
  for component in (*reversed(path.parents), path):
    try:
      info = component.lstat()
    except FileNotFoundError:
      continue
    if stat.S_ISLNK(info.st_mode) or (
      getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
      _reject(component, "links and reparse points are not supported")
    if component != path:
      if not stat.S_ISDIR(info.st_mode):
        _reject(component, "parent is not a directory")
    elif not stat.S_ISREG(info.st_mode):
      _reject(component, "not a regular file")
    elif info.st_nlink != 1:
      _reject(component, "hard links are not supported")


def _check_windows_path(path: Path) -> None:
  import win32file

  # 拒绝 UNC 网络共享与 NT 设备路径（如 \\server\share 或 \\.\...）
  if str(path).startswith("\\\\"):
    _reject(path, "network and device paths are not supported")
  # 拒绝驱动器相对路径（如 C:foo.db），Windows 盘符隐式当前目录易产生歧义
  if path.drive and not path.root:
    _reject(path, "drive-relative paths are not supported")
  for part in path.parts[1:] if path.anchor else path.parts:
    # 拒绝尾随点/空格（Win32 会静默剥离产生别名穿透）、
    # NTFS 备用数据流冒号以及 DOS 保留设备名
    if part not in (".", "..") and (
      part.endswith((".", " ")) or ":" in part or Path(part).is_reserved()
    ):
      _reject(path, "ambiguous Windows filename")
  absolute = path.absolute()
  # 校验物理驱动器类型，排除映射网络驱动器（DRIVE_REMOTE=4）等锁行为不可靠的介质
  if win32file.GetDriveType(absolute.anchor) not in (2, 3, 6):
    _reject(path, "only local disk paths are supported")


@dataclass(frozen=True)
class DataPath:
  path: Path
  identity: tuple[int, int] | tuple[int, int, str]


def resolve_data_path(value: str | Path) -> DataPath:
  """检查原路径的所有父目录，再用平台最终路径与文件身份统一别名。

  要求目录树由应用使用者管理；运行期间不可重命名、替换数据或锁文件。
  本接口不作为防御恶意并发文件系统修改的安全边界。
  """
  path = Path(value).expanduser()

  # 1. 展开前的语法与结构检查：
  # 在 resolve() 自动消除 '..'、剥离尾随点/空格或转换驱动器相对路径前，
  # 先拦截用户原始输入中的危险表达。
  if os.name == "nt":
    _check_windows_path(path)
  elif str(path).startswith("//"):
    _reject(path, "network paths are not supported")
  _check_components(path.absolute())

  # 2. 展开为规范绝对路径后的落地检查：
  # 消除相对跳转后，再次验证最终落地的物理驱动器（如是否落在网络映射盘）与完整路径组件。
  path = path.resolve()
  if os.name == "nt":
    _check_windows_path(path)
  _check_components(path)

  # 3. 预创建父目录（不创建数据库本身），并确保新落盘目录结构符合规范
  path.parent.mkdir(parents=True, exist_ok=True)
  _check_components(path)
  path = path.resolve()

  # 4. 获取操作系统底层唯一文件身份：
  # 已存在文件用 (st_dev, st_ino)；尚未创建的新文件用父目录身份与文件名组合。
  try:
    info = path.stat()
  except FileNotFoundError:
    parent = path.parent.stat()
    identity = (parent.st_dev, parent.st_ino, path.name)
  else:
    identity = (info.st_dev, info.st_ino)
  return DataPath(path, identity)
