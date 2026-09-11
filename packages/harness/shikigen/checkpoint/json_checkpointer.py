import base64
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
  WRITES_IDX_MAP,
  BaseCheckpointSaver,
  ChannelVersions,
  Checkpoint,
  CheckpointMetadata,
  CheckpointTuple,
)


class JsonCheckpointer(BaseCheckpointSaver):
  def __init__(self, base_dir: str = "~/.shikigen/checkpoints"):
    super().__init__()
    self._base_dir = Path(base_dir).expanduser()

  @staticmethod
  def _path_component(value: str) -> str:
    """Encode an identifier so it is always safe to use in a file path."""
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=") or "_"

  @staticmethod
  def _encode_blob(type_: str, blob: bytes) -> dict[str, str]:
    return {
      "type": type_,
      "blob": base64.b64encode(blob).decode("ascii"),
    }

  @staticmethod
  def _decode_blob(encoded: dict[str, str]) -> tuple[str, bytes]:
    return (
      encoded["type"],
      base64.b64decode(encoded["blob"], validate=True),
    )

  @staticmethod
  def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

  @staticmethod
  def _read_json_file(path: Path) -> Any | None:
    try:
      return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
      return None

  async def aput(
    self,
    config: RunnableConfig,
    checkpoint: Checkpoint,
    metadata: CheckpointMetadata,
    new_versions: ChannelVersions,
  ) -> RunnableConfig:
    thread_id = config["configurable"]["thread_id"]
    checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
    checkpoint_id = checkpoint["id"]
    parent_id = config["configurable"].get("checkpoint_id")

    type_, blob = self.serde.dumps_typed(checkpoint)
    serialized_metadata = self.serde.dumps_typed(metadata)

    metadata_type, metadata_blob = serialized_metadata
    content = json.dumps(
      {
        "thread_id": thread_id,
        "checkpoint_ns": checkpoint_ns,
        "checkpoint_id": checkpoint_id,
        "parent_id": parent_id,
        "checkpoint": self._encode_blob(type_, blob),
        "metadata": self._encode_blob(metadata_type, metadata_blob),
      },
      ensure_ascii=False,
      indent=2,
    )

    path = self._base_dir / self._path_component(
      f"checkpoints_table-{thread_id}-{checkpoint_ns}-{checkpoint_id}.json"
    )

    self._write_file(path, content)

    return {
      "configurable": {
        "thread_id": thread_id,
        "checkpoint_ns": checkpoint_ns,
        "checkpoint_id": checkpoint_id,
      }
    }

  async def aput_writes(
    self,
    config: RunnableConfig,
    writes: Sequence[tuple[str, Any]],
    task_id: str,
    task_path: str = "",
  ) -> None:
    thread_id = config["configurable"]["thread_id"]
    checkpoint_ns = config["configurable"]["checkpoint_ns"]
    checkpoint_id = config["configurable"]["checkpoint_id"]

    rows = []

    for idx, (channel, value) in enumerate(writes):
      type_, blob = self.serde.dumps_typed(value)
      final_idx = WRITES_IDX_MAP.get(channel, idx)

      rows.append(
        {
          "thread_id": thread_id,
          "checkpoint_ns": checkpoint_ns,
          "checkpoint_id": checkpoint_id,
          "task_id": task_id,
          "task_path": task_path,
          "final_idx": final_idx,
          "channel": channel,
          "type_": type_,
          "blob": base64.b64encode(blob).decode("ascii"),
        }
      )

    content = json.dumps(
      rows,
      ensure_ascii=False,
      indent=2,
    )

    path = self._base_dir / self._path_component(
      f"writes_table-{thread_id}-{checkpoint_ns}-{checkpoint_id}.json"
    )
    self._write_file(path, content)

  async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
    configurable = {
      **config["configurable"],
      "checkpoint_ns": config["configurable"].get("checkpoint_ns", ""),
    }
    normalized_config: RunnableConfig = {"configurable": configurable}

    async for checkpoint_tuple in self.alist(normalized_config, limit=1):
      return checkpoint_tuple
    return None

  async def alist(
    self,
    config: RunnableConfig | None,
    *,
    filter: dict[str, Any] | None = None,
    before: RunnableConfig | None = None,
    limit: int | None = None,
  ) -> AsyncIterator[CheckpointTuple]:
    configurable = config["configurable"] if config else {}
    thread_id = configurable.get("thread_id")
    checkpoint_ns = configurable.get("checkpoint_ns")
    checkpoint_id = configurable.get("checkpoint_id")
    before_id = before["configurable"].get("checkpoint_id") if before else None

    contents = []
    if self._base_dir.is_dir():
      for path in self._base_dir.iterdir():
        if not path.is_file():
          continue
        content = self._read_json_file(path)
        if isinstance(content, dict) and "checkpoint" in content:
          contents.append(content)

    contents.sort(
      key=lambda item: item["checkpoint_id"],
      reverse=True,
    )

    yielded = 0
    for content in contents:
      if thread_id is not None and content.get("thread_id") != thread_id:
        continue
      if checkpoint_ns is not None and content.get("checkpoint_ns") != checkpoint_ns:
        continue
      if checkpoint_id is not None and content.get("checkpoint_id") != checkpoint_id:
        continue
      if before_id is not None and content.get("checkpoint_id") >= before_id:
        continue

      metadata = self.serde.loads_typed(self._decode_blob(content["metadata"]))
      if filter and not all(
        metadata.get(key) == value for key, value in filter.items()
      ):
        continue
      if limit is not None and yielded >= max(limit, 0):
        return

      content_thread_id = content["thread_id"]
      content_checkpoint_ns = content["checkpoint_ns"]
      content_checkpoint_id = content["checkpoint_id"]
      writes_path = self._base_dir / self._path_component(
        "writes_table-"
        f"{content_thread_id}-{content_checkpoint_ns}-{content_checkpoint_id}.json"
      )
      writes_content = self._read_json_file(writes_path) or []
      pending_writes = [
        (
          write["task_id"],
          write["channel"],
          self.serde.loads_typed(
            (write["type_"], base64.b64decode(write["blob"], validate=True))
          ),
        )
        for write in writes_content
      ]

      parent_id = content.get("parent_id")
      parent_config = None
      if parent_id:
        parent_config = {
          "configurable": {
            "thread_id": content_thread_id,
            "checkpoint_ns": content_checkpoint_ns,
            "checkpoint_id": parent_id,
          }
        }

      yield CheckpointTuple(
        config={
          "configurable": {
            "thread_id": content_thread_id,
            "checkpoint_ns": content_checkpoint_ns,
            "checkpoint_id": content_checkpoint_id,
          }
        },
        checkpoint=self.serde.loads_typed(self._decode_blob(content["checkpoint"])),
        metadata=metadata,
        parent_config=parent_config,
        pending_writes=pending_writes,
      )
      yielded += 1

  async def adelete_thread(self, thread_id: str) -> None:
    if not self._base_dir.is_dir():
      return

    checkpoint_keys = set()
    paths_to_delete = []

    for path in self._base_dir.iterdir():
      if not path.is_file():
        continue

      content = self._read_json_file(path)
      if isinstance(content, dict) and content.get("thread_id") == thread_id:
        paths_to_delete.append(path)
        checkpoint_keys.add((content["checkpoint_ns"], content["checkpoint_id"]))
      elif (
        isinstance(content, list)
        and content
        and content[0].get("thread_id") == thread_id
      ):
        paths_to_delete.append(path)

    paths_to_delete.extend(
      self._base_dir
      / self._path_component(
        f"writes_table-{thread_id}-{checkpoint_ns}-{checkpoint_id}.json"
      )
      for checkpoint_ns, checkpoint_id in checkpoint_keys
    )

    for path in set(paths_to_delete):
      path.unlink(missing_ok=True)
