"""当前工作目录的只读资源；身份在每次 Runtime 装配时更新。"""

import hashlib
import mimetypes
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

MAX_IMAGE_BYTES = 20 * 1024 * 1024


class ResourceError(Exception):
  def __init__(self, status: int, message: str):
    super().__init__(message)
    self.status = status


def _file_version(file_stat: os.stat_result) -> str:
  coordinates = (
    file_stat.st_dev,
    file_stat.st_ino,
    file_stat.st_size,
    file_stat.st_mtime_ns,
    # CPython 3.12 Windows stat uses creation time while CRT fstat reports
    # last-write time as ctime. Never compare those incompatible coordinates.
    file_stat.st_ctime_ns if os.name != "nt" else None,
  )
  return hashlib.sha256(repr(coordinates).encode()).hexdigest()


def _image_mime(prefix: bytes) -> str | None:
  if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
    return "image/png"
  if prefix.startswith(b"\xff\xd8\xff"):
    return "image/jpeg"
  if prefix.startswith((b"GIF87a", b"GIF89a")):
    return "image/gif"
  if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
    return "image/webp"
  if prefix.startswith(b"BM"):
    return "image/bmp"
  if re.match(
    rb"(?:\xef\xbb\xbf)?\s*(?:<\?xml[^>]*>\s*)?(?:<!--.*?-->\s*)*<svg(?:\s|>)",
    prefix,
    re.S,
  ):
    return "image/svg+xml"
  return None


@dataclass(frozen=True)
class ResourceBinding:
  source: Path
  target: Path
  version: str


class WorkspaceResources:
  def __init__(self, root: str | Path):
    self.root = Path(root).expanduser().resolve()
    if not self.root.is_dir():
      raise ValueError(f"Workspace root must be an existing directory: {self.root}")
    root_stat = self.root.stat()
    self._root_identity = (root_stat.st_dev, root_stat.st_ino)
    self.workspace_id = uuid.uuid4().hex
    self._bindings: dict[str, ResourceBinding] = {}
    self._identities: dict[tuple[Path, Path, str], str] = {}
    self._identity_lock = Lock()

  def _check_root(self) -> None:
    try:
      root_stat = self.root.stat()
      if (
        not stat.S_ISDIR(root_stat.st_mode)
        or self.root.resolve() != self.root
        or (root_stat.st_dev, root_stat.st_ino) != self._root_identity
      ):
        raise ResourceError(409, "工作目录已变化，请重新连接后端")
    except OSError as error:
      raise ResourceError(409, "工作目录已失效，请重新连接后端") from error

  def describe_workspace(self) -> dict[str, str]:
    self._check_root()
    return {"workspace_id": self.workspace_id, "root": str(self.root)}

  def _source_path(self, reference: str) -> Path:
    if (
      not reference.strip()
      or any(ord(character) < 32 for character in reference)
      or "\x7f" in reference
    ):
      raise ResourceError(422, "本地路径无效")
    path_text = reference
    if reference.lower().startswith("file:"):
      try:
        uri = urlsplit(reference)
        if uri.query or uri.fragment or uri.username or uri.password:
          raise ValueError("file URI cannot contain query, fragment or credentials")
        if re.search(r"%(?![0-9a-fA-F]{2})", uri.path):
          raise ValueError("Invalid URI escape")
        path_text = unquote(uri.path, errors="strict")
        if uri.netloc and uri.netloc.lower() != "localhost":
          if os.name != "nt":
            raise ResourceError(403, "文件 URI 指向工作目录外")
          path_text = f"//{uri.netloc}{path_text}"
        elif os.name == "nt" and re.match(r"^/[a-zA-Z]:/", path_text):
          path_text = path_text[1:]
        if not Path(path_text).is_absolute():
          raise ValueError("file URI must be absolute")
      except (ValueError, UnicodeError) as error:
        raise ResourceError(422, "文件 URI 无效") from error
    elif re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", reference) and not re.match(
      r"^[a-zA-Z]:[\\/]", reference
    ):
      raise ResourceError(422, "不支持的本地路径协议")
    if any(ord(character) < 32 or ord(character) == 127 for character in path_text):
      raise ResourceError(422, "本地路径无效")
    if os.name == "nt" and (
      path_text.startswith(("\\\\?\\", "\\\\.\\"))
      or ":" in path_text[2:]
      or any(character in '<>"|?*' for character in path_text)
    ):
      raise ResourceError(422, "不支持设备路径或文件数据流")
    candidate = Path(path_text)
    if not candidate.is_absolute():
      candidate = self.root / candidate
    # Reject lexical escape even if an outside link later leads back inside.
    try:
      Path(os.path.abspath(candidate)).relative_to(self.root)
    except ValueError as error:
      raise ResourceError(403, "路径必须位于当前工作目录内") from error
    return candidate

  def _target_path(self, source: Path) -> Path:
    self._check_root()
    try:
      relative = source.relative_to(self.root)
      cursor = self.root
      for component in relative.parts:
        cursor = cursor / component
        cursor.resolve().relative_to(self.root)
      target = source.resolve(strict=True)
      target.relative_to(self.root)
      return target
    except ValueError as error:
      raise ResourceError(403, "链接目标必须位于当前工作目录内") from error
    except FileNotFoundError as error:
      raise ResourceError(404, "本地文件不存在") from error
    except (OSError, RuntimeError) as error:
      raise ResourceError(403, "无法读取本地文件或链接") from error

  def resolve_resource(self, reference: str) -> dict[str, object]:
    source = self._source_path(reference)
    target = self._target_path(source)
    try:
      if not stat.S_ISREG(target.stat().st_mode):
        raise ResourceError(422, "只支持普通文件，目录和特殊文件不可预览")
      with target.open("rb") as file_stream:
        file_stat = os.fstat(file_stream.fileno())
        if not stat.S_ISREG(file_stat.st_mode):
          raise ResourceError(422, "只支持普通文件，目录和特殊文件不可预览")
        prefix = file_stream.read(8192)
        version = _file_version(file_stat)
        if (
          self._target_path(source) != target
          or _file_version(target.stat()) != version
          or _file_version(os.fstat(file_stream.fileno())) != version
        ):
          raise ResourceError(409, "文件在读取期间变化，请重试解析")
    except IsADirectoryError as error:
      raise ResourceError(422, "首版不支持目录资源") from error
    except FileNotFoundError as error:
      raise ResourceError(404, "本地文件不存在") from error
    except OSError as error:
      raise ResourceError(403, "无法读取本地文件") from error
    image_mime = _image_mime(prefix)
    resource_key = (source, target, version)
    with self._identity_lock:
      resource_id = self._identities.setdefault(resource_key, uuid.uuid4().hex)
    metadata: dict[str, object] = {
      "workspace_id": self.workspace_id,
      "resource_id": resource_id,
      "absolute_path": str(target),
      "relative_path": str(target.relative_to(self.root)),
      "name": target.name,
      "kind": "file",
      "mime_type": image_mime or mimetypes.guess_type(target.name)[0],
      "size": file_stat.st_size,
      "modified_at": datetime.fromtimestamp(file_stat.st_mtime, UTC).isoformat(),
      "version": version,
      "can_preview": image_mime is not None,
    }
    self._bindings[resource_id] = ResourceBinding(source, target, version)
    return dict(metadata)

  def read_image(self, resource_id: str) -> tuple[bytes, str]:
    binding = self._bindings.get(resource_id)
    if binding is None:
      raise ResourceError(404, "资源身份不存在或已失效，请重新解析引用")
    target = self._target_path(binding.source)
    if target != binding.target:
      raise ResourceError(409, "引用目标已变化，请重新解析")
    try:
      current_stat = target.stat()
      if (
        not stat.S_ISREG(current_stat.st_mode)
        or _file_version(current_stat) != binding.version
      ):
        raise ResourceError(409, "文件版本已变化，请重新解析")
      with target.open("rb") as file_stream:
        file_stat = os.fstat(file_stream.fileno())
        if (
          not stat.S_ISREG(file_stat.st_mode)
          or _file_version(file_stat) != binding.version
        ):
          raise ResourceError(409, "文件版本已变化，请重新解析")
        if file_stat.st_size > MAX_IMAGE_BYTES:
          raise ResourceError(413, "图片超过 20MiB，无法自动预览")
        image_bytes = file_stream.read(MAX_IMAGE_BYTES + 1)
        if len(image_bytes) > MAX_IMAGE_BYTES:
          raise ResourceError(413, "图片超过 20MiB，无法自动预览")
        if (
          self._target_path(binding.source) != binding.target
          or _file_version(os.fstat(file_stream.fileno())) != binding.version
          or _file_version(target.stat()) != binding.version
        ):
          raise ResourceError(409, "文件在读取期间变化，请重新解析")
    except FileNotFoundError as error:
      raise ResourceError(404, "本地文件不存在") from error
    except OSError as error:
      raise ResourceError(403, "无法读取本地图片") from error
    mime = _image_mime(image_bytes[:8192])
    if mime is None:
      raise ResourceError(415, "不支持该文件的图片格式")
    if mime == "image/svg+xml":
      try:
        if b"<!DOCTYPE" in image_bytes.upper() or b"<!ENTITY" in image_bytes.upper():
          raise ValueError("SVG document entities are unsupported")
        svg = ElementTree.fromstring(image_bytes)
        if svg.tag not in ("svg", "{http://www.w3.org/2000/svg}svg"):
          raise ValueError("Not an SVG document")
      except (ElementTree.ParseError, ValueError) as error:
        raise ResourceError(415, "SVG 格式无效或不支持") from error
    return image_bytes, mime
