import path from "node:path";
import fs from "node:fs/promises";
import { createViolation } from "./content-model.mjs";

const asArray = (value) => (Array.isArray(value) ? value : []);

function addIssue(issues, severity, code, message, suggestion, recommendedActionOverride) {
  const recommendedAction = recommendedActionOverride
    ?? (/MISSING/.test(code)
      ? "provide_required_input"
      : /INVALID|UNSUPPORTED|DUPLICATE|NON_CANONICAL|CONFLICT/.test(code)
        ? "correct_input"
        : "review");
  issues.push(createViolation({
    code,
    field: "renderer_inputs",
    actual: null,
    capacity: null,
    severity,
    recoverable: true,
    recommended_action: recommendedAction,
    message,
    suggestion,
  }));
}

function portableBasename(filePath) {
  return String(filePath).replaceAll("\\", "/").split("/").at(-1) ?? "";
}

function portableExtension(filePath) {
  return path.posix.extname(portableBasename(filePath)).toLowerCase();
}

function portableStem(filePath) {
  const name = portableBasename(filePath);
  const extension = path.posix.extname(name);
  return name.slice(0, name.length - extension.length);
}

function convertMsysPath(projectPath) {
  const match = String(projectPath).match(/^\/([a-zA-Z])(?:\/(.*))?$/);
  if (!match) return undefined;
  return `${match[1].toUpperCase()}:/${match[2] ?? ""}`;
}

function normalizePlatform(value) {
  const platform = String(value ?? process.platform).toLowerCase();
  if (["windows", "win32"].includes(platform)) return "win32";
  if (["linux", "darwin"].includes(platform)) return platform;
  return platform;
}

function affectedWatcherVersion(version) {
  return String(version ?? "").trim() === "5.4.4";
}

export function validateRendererInputs(input = {}) {
  const explicitRequestedRenderer = input.requested_renderer === undefined
    ? undefined
    : String(input.requested_renderer).toLowerCase();
  const legacyRenderer = input.renderer === undefined ? undefined : String(input.renderer).toLowerCase();
  if (explicitRequestedRenderer && legacyRenderer && explicitRequestedRenderer !== legacyRenderer) {
    throw new RangeError(`Conflicting renderer fields: requested_renderer=${explicitRequestedRenderer}, renderer=${legacyRenderer}`);
  }
  const requestedRenderer = explicitRequestedRenderer ?? legacyRenderer ?? "slidep";
  if (!["slidep", "tencent-pptx"].includes(requestedRenderer)) {
    throw new RangeError(`Unsupported renderer: ${requestedRenderer}`);
  }
  const effectiveRenderer = "slidep";
  const compatibilityMode = requestedRenderer !== effectiveRenderer;
  const platform = normalizePlatform(input.platform);
  const rendererVersion = input.renderer_version === undefined ? undefined : String(input.renderer_version).trim();
  const projectPath = input.project_path === undefined ? undefined : String(input.project_path).trim();
  const sourceFiles = asArray(input.source_files).map((file) => String(file).trim()).filter(Boolean);
  const liveWatchRequested = Boolean(input.live_watch_requested);
  const issues = [];

  let normalizedProjectPath = projectPath;
  if (!projectPath) {
    addIssue(
      issues,
      "error",
      "MISSING_PROJECT_PATH",
      "没有提供 slidep 项目路径。",
      "传入渲染器实际使用的项目根目录；Windows 使用盘符绝对路径。",
    );
  }
  const msysSuggestion = platform === "win32" && projectPath ? convertMsysPath(projectPath) : undefined;
  if (msysSuggestion) {
    normalizedProjectPath = msysSuggestion;
    addIssue(
      issues,
      "error",
      "MSYS_PROJECT_PATH_UNSUPPORTED",
      `slidep 在 Windows 下不能安全使用 MSYS 路径 ${projectPath}。`,
      `改用盘符绝对路径 ${msysSuggestion}，并在启动前确认该目录存在。`,
    );
  } else if (platform === "win32" && projectPath && !/^[a-zA-Z]:[\\/]/.test(projectPath)) {
    addIssue(
      issues,
      "error",
      "PROJECT_PATH_NOT_DRIVE_ABSOLUTE",
      `Windows 下的项目路径不是盘符绝对路径：${projectPath}。`,
      "传入 F:/path/to/project 或 F:\\path\\to\\project，不要传 Git Bash 的 /f/... 形式。",
    );
  } else if (["linux", "darwin"].includes(platform) && projectPath && !projectPath.startsWith("/")) {
    addIssue(
      issues,
      "error",
      "PROJECT_PATH_NOT_POSIX_ABSOLUTE",
      `POSIX 平台下的项目路径不是绝对路径：${projectPath}。`,
      "传入 /absolute/path/to/project；不要使用 Windows 盘符路径或相对路径。",
    );
  }
  if (input.project_exists === false) {
    addIssue(
      issues,
      "error",
      "PROJECT_DIRECTORY_NOT_FOUND",
      `项目目录不存在：${normalizedProjectPath ?? "（未提供）"}。`,
      "在启动 slidep 前先检查项目目录和 slides 子目录；不要把 spawn ENOENT 误判为 Node 可执行文件缺失。",
    );
  }

  const pageSources = sourceFiles.map((file) => ({
    file,
    extension: portableExtension(file),
    page_id: portableStem(file),
  }));
  if (!pageSources.length) {
    addIssue(
      issues,
      "error",
      "NO_PAGE_SOURCES",
      "没有提供任何页面源文件。",
      "在启动渲染器前列出 slides 目录中的全部 XX_slug.slide 文件。",
    );
  }
  const unsupported = pageSources.filter((source) => ![".slide", ".jsx"].includes(source.extension));
  if (unsupported.length) {
    addIssue(
      issues,
      "error",
      "UNSUPPORTED_SLIDE_SOURCE_EXTENSION",
      `发现不支持的页面源：${unsupported.map((source) => source.file).join(", ")}。`,
      "slidep 页面源统一使用 XX_slug.slide；构建器或辅助代码不要作为页面源传入。",
    );
  }
  const jsxSources = pageSources.filter((source) => source.extension === ".jsx");
  if (jsxSources.length) {
    addIssue(
      issues,
      "error",
      "NON_CANONICAL_SLIDE_SOURCE",
      `发现 ${jsxSources.length} 个 .jsx 页面源；当前 slidep 契约以 .slide 为唯一规范扩展名。`,
      "只保留对应的 .slide 文件，不要为同一页同时生成 .slide 与 .jsx。",
    );
  }

  const byPageId = new Map();
  for (const source of pageSources.filter((item) => [".slide", ".jsx"].includes(item.extension))) {
    const key = source.page_id.toLowerCase();
    const current = byPageId.get(key) ?? [];
    current.push(source.file);
    byPageId.set(key, current);
  }
  const duplicatePageIds = [...byPageId.entries()]
    .filter(([, files]) => files.length > 1)
    .map(([pageId, files]) => ({ page_id: pageId, files }));
  if (duplicatePageIds.length) {
    addIssue(
      issues,
      "error",
      "DUPLICATE_PAGE_ID",
      `页面 ID 重复：${duplicatePageIds.map((item) => `${item.page_id} ← ${item.files.join(" | ")}`).join("; ")}。`,
      "在调用 slidep-start 前快速失败；每个 stem 只能对应一个 XX_slug.slide 页面源。",
    );
  }

  const slideSources = pageSources.filter((source) => source.extension === ".slide");
  const unordered = slideSources.filter((source) => !/^\d{2}(?:_|$)/.test(portableBasename(source.file)));
  if (unordered.length) {
    addIssue(
      issues,
      "warning",
      "NON_CANONICAL_PAGE_NAME",
      `以下页面文件没有两位序号前缀：${unordered.map((source) => source.file).join(", ")}。`,
      "使用 01_cover.slide、02_agenda.slide 等名称，确保页序稳定。",
    );
  }

  let watcherKnownUnreliable = false;
  if (liveWatchRequested && platform === "win32" && affectedWatcherVersion(rendererVersion)) {
    watcherKnownUnreliable = true;
    addIssue(
      issues,
      "warning",
      "SLIDEP_WATCHER_UNRELIABLE",
      `slidep ${rendererVersion} 在 Windows 的已知复测中不会响应 slides 目录的实时新增或修改事件。`,
      "不要依赖实时 watcher；完成一批页面修改后 stop/start，让 initial scan 重新编译，并在交付前验证 PPTX 页数。",
    );
  } else if (liveWatchRequested && platform === "win32" && !rendererVersion) {
    addIssue(
      issues,
      "warning",
      "SLIDEP_VERSION_REQUIRED_FOR_WATCH",
      "请求了 Windows 实时监听，但没有提供 slidep 版本，无法排除已知 watcher 故障。",
      "提供 renderer_version；在确认修复前使用批量修改后重启的安全模式。",
    );
  }

  const hasError = issues.some((issue) => issue.severity === "error");
  const hasWarning = issues.some((issue) => issue.severity === "warning");
  const canonicalSources = slideSources
    .filter((source) => !duplicatePageIds.some((duplicate) => duplicate.files.includes(source.file)))
    .map((source) => source.file);
  return {
    requested_renderer: requestedRenderer,
    effective_renderer: effectiveRenderer,
    compatibility_mode: compatibilityMode,
    renderer_version: rendererVersion,
    platform,
    status: hasError ? "invalid" : hasWarning ? "warning" : "valid",
    project_path: projectPath,
    normalized_project_path: normalizedProjectPath,
    canonical_extension: ".slide",
    source_count: sourceFiles.length,
    canonical_sources: canonicalSources,
    duplicate_page_ids: duplicatePageIds,
    issues,
    safe_execution_plan: {
      compile_mode: watcherKnownUnreliable || (liveWatchRequested && platform === "win32" && !rendererVersion)
        ? "batch_restart_initial_scan"
        : liveWatchRequested
          ? "live_watch"
          : "batch_initial_scan",
      rely_on_live_watcher: liveWatchRequested && !watcherKnownUnreliable && Boolean(rendererVersion),
      validate_before_start: true,
      fail_on_duplicate_page_id: true,
      use_only_extension: ".slide",
      restart_after_source_changes: watcherKnownUnreliable || (liveWatchRequested && platform === "win32" && !rendererVersion),
      verify_after_compile: ["pptx_exists", "slide_count_matches_unique_page_ids", "renderer_log_has_no_residual_failure"],
    },
  };
}

async function listDirectory(dirPath) {
  try {
    return await fs.readdir(dirPath);
  } catch {
    return [];
  }
}

/**
 * 对 renderer_inputs 声明的项目目录与页面源文件做真实文件系统验证。
 *
 * 这是把 preflight 从"校验我声称的结构"升级为"接触磁盘真相"的一层：
 * - verified_ok       : 目录与全部源文件真实存在
 * - verified_missing  : 目录或部分源文件在磁盘上不存在（真实 error，绝不放行）
 * - not_verifiable    : 跨机 / 无权限 / 无法解析路径，无法验证（降级为 warning，绝不假通过）
 *
 * 保持纯同步的 validateRendererInputs 不动；本函数只由 runPreflight 这类 async 调用方接入。
 */
export async function verifyRendererInputsOnDisk(input = {}) {
  const platform = normalizePlatform(input.platform);
  const projectPath = input.project_path === undefined ? undefined : String(input.project_path).trim();
  const sourceFiles = asArray(input.source_files).map((file) => String(file).trim()).filter(Boolean);
  const issues = [];
  const sourceFileStatus = {};
  const availableSources = {};

  if (!projectPath) {
    return {
      verifyable: false,
      status: "not_verifiable",
      reason: "missing_project_path",
      project_path: null,
      project_dir_exists: false,
      source_file_status: {},
      verified_source_count: 0,
      missing_source_files: sourceFiles,
      available_sources: {},
      issues,
    };
  }

  let normalizedProjectPath = projectPath;
  const msys = platform === "win32" ? convertMsysPath(projectPath) : undefined;
  if (msys) normalizedProjectPath = msys;

  // 渲染器平台与当前运行主机不一致 → 无法在本地验证，降级告警，不假通过也不误报。
  const hostPlatform = normalizePlatform(process.platform);
  if (platform && hostPlatform !== platform) {
    addIssue(
      issues,
      "warning",
      "FILESYSTEM_VERIFY_SKIPPED",
      `preflight 运行主机(${hostPlatform}) 与渲染器平台(${platform}) 不一致，无法在本地验证文件存在性。`,
      "在渲染器所在主机上重跑 preflight，或人工确认源文件存在。",
      "review",
    );
    return {
      verifyable: false,
      status: "not_verifiable",
      reason: "platform_mismatch",
      project_path: normalizedProjectPath,
      project_dir_exists: null,
      source_file_status: {},
      verified_source_count: 0,
      missing_source_files: sourceFiles,
      available_sources: {},
      issues,
    };
  }

  let projectDirExists = null;
  try {
    await fs.access(normalizedProjectPath);
    projectDirExists = true;
  } catch (error) {
    if (error.code === "ENOENT") {
      projectDirExists = false;
    } else {
      // EACCES / EPERM / 其他：无法确认，降级告警。
      addIssue(
        issues,
        "warning",
        "FILESYSTEM_VERIFY_SKIPPED",
        `无法访问项目目录 ${normalizedProjectPath}：${error.code ?? error.message}。`,
        "检查目录权限或确认 preflight 与渲染器是否运行在同一主机。",
        "review",
      );
      return {
        verifyable: false,
        status: "not_verifiable",
        reason: error.code ?? "access_error",
        project_path: normalizedProjectPath,
        project_dir_exists: null,
        source_file_status: {},
        verified_source_count: 0,
        missing_source_files: sourceFiles,
        available_sources: {},
        issues,
      };
    }
  }

  if (projectDirExists === false) {
    addIssue(
      issues,
      "error",
      "PROJECT_DIRECTORY_NOT_FOUND",
      `项目目录不存在：${normalizedProjectPath}。`,
      "在启动 slidep 前先确认项目目录已创建。",
      "correct_input",
    );
    return {
      verifyable: true,
      status: "verified_missing",
      reason: "project_dir_missing",
      project_path: normalizedProjectPath,
      project_dir_exists: false,
      source_file_status: Object.fromEntries(sourceFiles.map((file) => [file, "missing"])),
      verified_source_count: 0,
      missing_source_files: sourceFiles,
      available_sources: {},
      issues,
    };
  }

  const missingSourceFiles = [];
  const verifiedSourceFiles = [];
  for (const file of sourceFiles) {
    const absolute = path.join(normalizedProjectPath, file);
    let exists = false;
    try {
      await fs.access(absolute);
      exists = true;
    } catch {
      exists = false;
    }
    sourceFileStatus[file] = exists ? "exists" : "missing";
    if (exists) verifiedSourceFiles.push(file);
    else missingSourceFiles.push(file);
  }

  if (missingSourceFiles.length) {
    // 尽力列出同级目录里真实存在的 .slide，帮助诊断"声明名 vs 磁盘名"不一致。
    for (const file of missingSourceFiles) {
      const dir = path.dirname(path.join(normalizedProjectPath, file));
      const listing = await listDirectory(dir);
      availableSources[file] = listing
        .filter((name) => [".slide", ".jsx"].includes(path.posix.extname(name).toLowerCase()))
        .sort();
    }
    const hint = Object.entries(availableSources)
      .filter(([, files]) => files.length)
      .map(([file, files]) => `${file} → 磁盘实际存在: ${files.join(", ")}`)
      .join("；");
    addIssue(
      issues,
      "error",
      "PAGE_SOURCE_FILE_NOT_FOUND",
      `以下页面源文件在项目目录中不存在：${missingSourceFiles.join(", ")}。`,
      hint
        ? `核对 source_files 名称与磁盘实际文件名是否一致（${hint}）。`
        : "核对 source_files 名称（含序号前缀与 slug）与磁盘实际文件名是否一致。",
      "correct_input",
    );

    // 声明文件缺失、但存在同序号前缀的实际文件 → 给出精确的 stem 错配提示。
    const stemMismatches = [];
    for (const file of missingSourceFiles) {
      const declaredStem = portableStem(file);
      const declaredPrefix = declaredStem.match(/^(\d{2})/)?.[1];
      if (!declaredPrefix) continue;
      const sibling = (availableSources[file] ?? []).find((name) => portableStem(name).startsWith(`${declaredPrefix}_`) || portableStem(name) === declaredPrefix);
      if (sibling) stemMismatches.push(`${file} 疑似应为 ${path.posix.join(path.posix.dirname(file), sibling)}`);
    }
    if (stemMismatches.length) {
      addIssue(
        issues,
        "warning",
        "PAGE_SOURCE_STEM_MISMATCH",
        `页面源文件 stem 可能与磁盘不一致：${stemMismatches.join("；")}。`,
        "按磁盘实际文件名修正 source_files；序号前缀须与渲染顺序一致。",
        "correct_input",
      );
    }
  }

  const status = missingSourceFiles.length ? "verified_missing" : "verified_ok";
  return {
    verifyable: true,
    status,
    reason: status === "verified_ok" ? "all_sources_present" : "source_files_missing",
    project_path: normalizedProjectPath,
    project_dir_exists: true,
    source_file_status: sourceFileStatus,
    verified_source_count: verifiedSourceFiles.length,
    missing_source_files: missingSourceFiles,
    available_sources: availableSources,
    issues,
  };
}
