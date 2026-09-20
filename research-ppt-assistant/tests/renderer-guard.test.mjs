import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { validateRendererInputs, verifyRendererInputsOnDisk } from "../server/renderer-guard.mjs";

// 凡是拿「本机临时目录」去校验真实文件系统的用例，声明的渲染器平台必须是宿主平台。
// 写死 win32 会踩两条平台假设：win32 分支要求盘符绝对路径（macOS/Linux 的 tmpdir 不满足），
// 且跨平台磁盘校验会先因 platform_mismatch 降级为 not_verifiable —— 也就是说这些用例在
// 非 Windows 主机上恒失败，而它们考的本来就不是 Windows 路径规则（那是另外几组 F:/ 用例）。
const HOST_PLATFORM = process.platform;

// 反过来，「平台不一致就降级告警」这条用例需要一个**确定不等于宿主**的平台才能触发。
const FOREIGN_PLATFORM = ["win32", "linux", "darwin"].find((platform) => platform !== process.platform);

test("renderer guard reports every input-family blocker", () => {
  const missing = validateRendererInputs();
  assert.equal(missing.status, "invalid");
  assert.ok(missing.issues.some((item) => item.code === "MISSING_PROJECT_PATH"));
  assert.ok(missing.issues.some((item) => item.code === "NO_PAGE_SOURCES"));

  const invalid = validateRendererInputs({
    platform: "windows",
    project_path: "relative/deck",
    project_exists: false,
    source_files: ["cover.txt", "cover.slide"],
  });
  for (const code of ["PROJECT_PATH_NOT_DRIVE_ABSOLUTE", "PROJECT_DIRECTORY_NOT_FOUND", "UNSUPPORTED_SLIDE_SOURCE_EXTENSION", "NON_CANONICAL_PAGE_NAME"]) {
    assert.ok(invalid.issues.some((item) => item.code === code), code);
  }
  assert.throws(() => validateRendererInputs({ requested_renderer: "unknown" }), /Unsupported renderer/);
});

test("renderer guard chooses safe live-watch modes by platform and version", () => {
  const unknownWindowsVersion = validateRendererInputs({
    platform: "win32",
    project_path: "F:/deck",
    project_exists: true,
    source_files: ["01_cover.slide"],
    live_watch_requested: true,
  });
  assert.equal(unknownWindowsVersion.status, "warning");
  assert.equal(unknownWindowsVersion.safe_execution_plan.compile_mode, "batch_restart_initial_scan");
  assert.ok(unknownWindowsVersion.issues.some((item) => item.code === "SLIDEP_VERSION_REQUIRED_FOR_WATCH"));

  const linuxWatch = validateRendererInputs({
    platform: "linux",
    renderer_version: "6.0.0",
    project_path: "/deck",
    project_exists: true,
    source_files: ["01_cover.slide"],
    live_watch_requested: true,
  });
  assert.equal(linuxWatch.status, "valid");
  assert.equal(linuxWatch.safe_execution_plan.compile_mode, "live_watch");
  assert.equal(linuxWatch.safe_execution_plan.rely_on_live_watcher, true);
});

test("verifyRendererInputsOnDisk catches fake source files against the real filesystem", async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "renderer-guard-"));
  try {
    // 项目目录存在，但声明的源文件不存在 → verified_missing + PAGE_SOURCE_FILE_NOT_FOUND
    const fake = await verifyRendererInputsOnDisk({
      platform: HOST_PLATFORM,
      project_path: dir,
      source_files: ["slides/01_cover.slide", "slides/02_agenda.slide"],
    });
    assert.equal(fake.status, "verified_missing");
    assert.equal(fake.verifyable, true);
    assert.ok(fake.issues.some((item) => item.code === "PAGE_SOURCE_FILE_NOT_FOUND"));

    // 项目目录本身缺失 → PROJECT_DIRECTORY_NOT_FOUND
    const missingDir = await verifyRendererInputsOnDisk({
      platform: HOST_PLATFORM,
      project_path: path.join(dir, "does-not-exist"),
      source_files: ["01_cover.slide"],
    });
    assert.equal(missingDir.status, "verified_missing");
    assert.ok(missingDir.issues.some((item) => item.code === "PROJECT_DIRECTORY_NOT_FOUND"));

    // 磁盘实际是 01.slide，声明却是 01_cover.slide → 触发 stem 错配提示
    await fs.mkdir(path.join(dir, "slides"), { recursive: true });
    await fs.writeFile(path.join(dir, "slides", "01.slide"), "");
    const stemMismatch = await verifyRendererInputsOnDisk({
      platform: HOST_PLATFORM,
      project_path: dir,
      source_files: ["slides/01_cover.slide"],
    });
    assert.equal(stemMismatch.status, "verified_missing");
    assert.ok(stemMismatch.issues.some((item) => item.code === "PAGE_SOURCE_STEM_MISMATCH"));

    // 真实存在的文件 → verified_ok
    const ok = await verifyRendererInputsOnDisk({
      platform: HOST_PLATFORM,
      project_path: dir,
      source_files: ["slides/01.slide"],
    });
    assert.equal(ok.status, "verified_ok");
    assert.equal(ok.verified_source_count, 1);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test("verifyRendererInputsOnDisk degrades to a warning across platforms instead of false-passing", async () => {
  const result = await verifyRendererInputsOnDisk({
    platform: FOREIGN_PLATFORM,
    project_path: "/deck",
    source_files: ["01_cover.slide"],
  });
  assert.equal(result.status, "not_verifiable");
  assert.equal(result.verifyable, false);
  assert.ok(result.issues.some((item) => item.code === "FILESYSTEM_VERIFY_SKIPPED"));
});
