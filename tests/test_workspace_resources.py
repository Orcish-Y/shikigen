"""工作目录资源的公开 HTTP 只读契约。"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime, open_runtime
from shikigen.tools.tool_registry import ToolRegistry

from app.server import create_app

PNG = bytes.fromhex(
  "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
  "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"
)


class WorkspaceResourceTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.root = Path(self.directory.name) / "workspace"
    self.root.mkdir()
    self.image = self.root / "预览 one.png"
    self.image.write_bytes(PNG)
    self.store = await ChatStore.open(Path(self.directory.name) / "runs.db")
    self.addAsyncCleanup(self.store.close)
    self.runtime = assemble_runtime(
      config=AppConfig(
        model=ModelConfig(), mcp=McpConfig(), workspace_root=str(self.root)
      ),
      agent=object(),
      chat_store=self.store,
    )
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)
    self.app = create_app(runtime=self.runtime)
    await self.enterAsyncContext(self.app.router.lifespan_context(self.app))
    self.client = await self.enterAsyncContext(
      httpx.AsyncClient(
        transport=httpx.ASGITransport(app=self.app), base_url="http://test"
      )
    )

  async def resolve(self, path):
    response = await self.client.get(
      "/api/workspace/resources/resolve", params={"path": path}
    )
    return response

  async def test_current_image_metadata_and_bytes_are_pure_read_facts(self):
    workspace = await self.client.get("/api/workspace")
    self.assertEqual(workspace.status_code, 200)
    self.assertEqual(workspace.headers["cache-control"], "no-store")
    identity = workspace.json()["data"]
    self.assertEqual(identity["root"], str(self.root.resolve()))
    response = await self.resolve(self.image.name)
    self.assertEqual(response.status_code, 200)
    resource = response.json()["data"]
    self.assertEqual(resource["workspace_id"], identity["workspace_id"])
    self.assertEqual(resource["absolute_path"], str(self.image.resolve()))
    self.assertEqual(resource["relative_path"], self.image.name)
    self.assertEqual(resource["kind"], "file")
    self.assertEqual(resource["size"], len(PNG))
    self.assertEqual(resource["mime_type"], "image/png")
    self.assertTrue(resource["can_preview"])
    self.assertTrue(resource["version"])
    image = await self.client.get(
      f"/api/workspace/resources/{resource['resource_id']}/image"
    )
    self.assertEqual(image.status_code, 200)
    self.assertEqual(image.content, PNG)
    self.assertEqual(image.headers["content-type"], "image/png")
    self.assertEqual(image.headers["cache-control"], "no-store")
    self.assertEqual(image.headers["x-content-type-options"], "nosniff")
    self.assertEqual(
      (await self.client.get("/api/threads", params={"limit": 20})).json()["data"], []
    )
    self.assertEqual(self.image.read_bytes(), PNG)

  async def test_relative_absolute_and_file_uri_have_same_current_identity(self):
    resources = [
      (await self.resolve(reference)).json()["data"]
      for reference in (
        self.image.name,
        str(self.image),
        self.image.as_uri(),
        self.image.as_uri().replace("file://", "file://localhost"),
      )
    ]
    self.assertEqual(len({resource["resource_id"] for resource in resources}), 1)
    initial_cwd = Path.cwd()
    try:
      os.chdir(self.directory.name)
      self.assertEqual(
        (await self.resolve(self.image.name)).json()["data"], resources[0]
      )
    finally:
      os.chdir(initial_cwd)

  async def test_invalid_missing_outside_directory_and_unreadable_paths(self):
    outside = Path(self.directory.name) / "outside.png"
    outside.write_bytes(PNG)
    for reference, status in (
      ("", 422),
      (" \n", 422),
      ("x\x00.png", 422),
      ("file:relative.png", 422),
      ("file:///bad%XX", 422),
      (self.image.as_uri() + "?x=1", 422),
      ("https://example.org/image.png", 422),
      ("missing.png", 404),
      ("../outside.png", 403),
      (str(outside), 403),
      (".", 422),
    ):
      with self.subTest(reference=reference):
        response = await self.resolve(reference)
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
    with patch.object(Path, "open", side_effect=PermissionError("denied")):
      self.assertEqual((await self.resolve(self.image.name)).status_code, 403)
    for url in (
      "/api/workspace/resources/resolve",
      "/api/workspace/resources/resolve?path=a&path=b",
      "/api/workspace/resources/resolve?path=a&root=b",
    ):
      response = await self.client.get(url)
      self.assertEqual(response.status_code, 422)
      self.assertEqual(response.headers["cache-control"], "no-store")

  async def test_version_change_deletion_and_old_startup_never_read_new_bytes(self):
    resource = (await self.resolve(self.image.name)).json()["data"]
    endpoint = f"/api/workspace/resources/{resource['resource_id']}/image"
    self.image.write_bytes(PNG + b"changed")
    self.assertEqual((await self.client.get(endpoint)).status_code, 409)
    updated = (await self.resolve(self.image.name)).json()["data"]
    self.assertNotEqual(updated["resource_id"], resource["resource_id"])
    self.assertNotEqual(updated["version"], resource["version"])
    self.image.unlink()
    self.assertEqual((await self.client.get(endpoint)).status_code, 404)
    other_runtime = assemble_runtime(
      config=self.runtime.config, agent=object(), chat_store=self.store
    )
    self.addAsyncCleanup(other_runtime.lifecycle.shutdown)
    other_app = create_app(runtime=other_runtime)
    async with (
      other_app.router.lifespan_context(other_app),
      httpx.AsyncClient(
        transport=httpx.ASGITransport(app=other_app), base_url="http://test"
      ) as other_client,
    ):
      self.assertNotEqual(
        (await other_client.get("/api/workspace")).json()["data"]["workspace_id"],
        resource["workspace_id"],
      )
      self.assertEqual((await other_client.get(endpoint)).status_code, 404)

  async def test_formats_limits_and_untrusted_suffix(self):
    formats = {
      "jpeg": (b"\xff\xd8\xff\xe0abc", "image/jpeg"),
      "gif": (b"GIF89aabc", "image/gif"),
      "webp": (b"RIFF\x00\x00\x00\x00WEBPabc", "image/webp"),
      "bmp": (b"BMabc", "image/bmp"),
      "svg": (
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>window.bad=1</script></svg>',
        "image/svg+xml",
      ),
    }
    for suffix, (image_bytes, mime) in formats.items():
      with self.subTest(suffix=suffix):
        (self.root / f"test.{suffix}").write_bytes(image_bytes)
        resource = (await self.resolve(f"test.{suffix}")).json()["data"]
        response = await self.client.get(
          f"/api/workspace/resources/{resource['resource_id']}/image"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], mime)
        self.assertEqual(response.content, image_bytes)
    for name, image_bytes in (
      ("fake.png", b"<html>not an image</html>"),
      ("bad.svg", b"<svg><broken></svg>"),
    ):
      (self.root / name).write_bytes(image_bytes)
      resource = (await self.resolve(name)).json()["data"]
      self.assertEqual(
        (
          await self.client.get(
            f"/api/workspace/resources/{resource['resource_id']}/image"
          )
        ).status_code,
        415,
      )
    large = self.root / "large.png"
    with large.open("wb") as file_stream:
      file_stream.write(PNG)
      file_stream.truncate(20 * 1024 * 1024 + 1)
    resource = (await self.resolve(large.name)).json()["data"]
    response = await self.client.get(
      f"/api/workspace/resources/{resource['resource_id']}/image"
    )
    self.assertEqual(response.status_code, 413)
    self.assertEqual(response.headers["cache-control"], "no-store")

  async def test_links_outside_and_link_retarget_are_rejected(self):
    outside = Path(self.directory.name) / "outside"
    outside.mkdir()
    (outside / "image.png").write_bytes(PNG)
    inside = self.root / "inside"
    inside.mkdir()
    (inside / "image.png").write_bytes(PNG)
    link = self.root / "link"

    def make_link(target):
      if os.name == "nt":
        result = subprocess.run(
          ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
      else:
        link.symlink_to(target, target_is_directory=True)

    make_link(inside)
    resource = (await self.resolve("link/image.png")).json()["data"]
    link.rmdir() if os.name == "nt" else link.unlink()
    make_link(outside)
    response = await self.resolve("link/image.png")
    self.assertEqual(response.status_code, 403)
    response = await self.client.get(
      f"/api/workspace/resources/{resource['resource_id']}/image"
    )
    self.assertEqual(response.status_code, 403)
    link.rmdir() if os.name == "nt" else link.unlink()
    second = self.root / "second"
    second.mkdir()
    (second / "image.png").write_bytes(PNG)
    make_link(second)
    self.assertEqual(
      (
        await self.client.get(
          f"/api/workspace/resources/{resource['resource_id']}/image"
        )
      ).status_code,
      409,
    )

  async def test_replaced_root_and_same_size_replaced_file_invalidate_identity(self):
    resource = (await self.resolve(self.image.name)).json()["data"]
    endpoint = f"/api/workspace/resources/{resource['resource_id']}/image"
    previous_time = self.image.stat().st_mtime_ns
    replacement = self.root / "replacement.png"
    replacement.write_bytes(PNG)
    os.utime(replacement, ns=(previous_time, previous_time))
    replacement.replace(self.image)
    self.assertEqual((await self.client.get(endpoint)).status_code, 409)
    self.root.rename(Path(self.directory.name) / "old-workspace")
    self.root.mkdir()
    response = await self.client.get("/api/workspace")
    self.assertEqual(response.status_code, 409)
    self.assertEqual(response.headers["cache-control"], "no-store")
    self.assertEqual((await self.resolve(self.image.name)).status_code, 409)

  async def test_owned_runtime_binds_the_same_root_for_resources_and_file_tools(self):
    (self.root / "note.txt").write_text("same workspace", encoding="utf-8")
    registry: ToolRegistry | None = None

    async def create_agent_fixture(**arguments):
      nonlocal registry
      registry = arguments["tool_registry"]
      return object()

    config = self.runtime.config.model_copy(
      update={
        "database": self.runtime.config.database.model_copy(
          update={"path": str(Path(self.directory.name) / "owned.db")}
        ),
        "checkpointer": self.runtime.config.checkpointer.model_copy(
          update={"type": "memory"}
        ),
        "workspace_root": "workspace",
      }
    )
    initial_cwd = Path.cwd()
    try:
      os.chdir(self.directory.name)
      with patch(
        "shikigen.runtime.composition.create_lead_agent", new=create_agent_fixture
      ):
        async with open_runtime(config) as runtime:
          os.chdir(initial_cwd)
          self.assertEqual(
            runtime.resources.describe_workspace()["root"], str(self.root.resolve())
          )
          self.assertEqual(runtime.config.workspace_root, str(self.root.resolve()))
          assert registry is not None
          self.assertEqual(
            registry.tools["read_file"].invoke({"path": "note.txt"}), "same workspace"
          )
          self.assertEqual(
            runtime.resources.resolve_resource("note.txt")["absolute_path"],
            str(self.root / "note.txt"),
          )
    finally:
      os.chdir(initial_cwd)
