# slidep / tencent-pptx Compatibility

Use this reference only when slidep or tencent-pptx compiles the final PPTX. These rules protect the handoff between the research planner and the renderer; they do not claim to repair the renderer engine itself.

## Required preflight

Call `validate_renderer_inputs` after all page-source names are known and before `slidep-start`.

- `source_files` must contain every intended page source.
- Use exactly one `XX_slug.slide` file per page.
- A page ID is the case-insensitive filename stem. Any repeated stem is a blocking `DUPLICATE_PAGE_ID` error, even when extensions differ.
- `.jsx` is not a canonical page-source extension. Do not create `.slide` and `.jsx` copies of the same page.
- On Windows, pass a drive-letter absolute `project_path`, such as `F:/Workbuddy/deck` or `F:\Workbuddy\deck`. Do not pass Git Bash/MSYS forms such as `/f/Workbuddy/deck`.
- Check that the project directory exists before starting the renderer; an invalid working directory may surface as a misleading spawn `ENOENT`.

Do not start slidep when preflight status is `invalid`.

## Windows slidep 5.4.4

Controlled testing found that slidep 5.4.4 on Windows can complete its initial scan while failing to react to later file additions or modifications. Until the renderer is independently confirmed fixed:

1. Write or update page sources in a batch.
2. Run preflight and remove all blocking issues.
3. Stop the prior daemon if one exists.
4. Start slidep so the initial scan compiles the current source set.
5. Verify that the PPTX exists, its slide count equals the number of unique `.slide` stems, and the renderer log has no residual failure state.

Do not promise real-time compilation in this environment. `SLIDEP_WATCHER_UNRELIABLE` is a compatibility warning; the safe execution mode is `batch_restart_initial_scan`.

## Error interpretation

- `DUPLICATE_PAGE_ID`: remove or rename duplicates before compilation. Do not let the renderer enter reconciliation.
- `NON_CANONICAL_SLIDE_SOURCE`: replace `.jsx` page sources with `.slide`.
- `MSYS_PROJECT_PATH_UNSUPPORTED`: use the returned `normalized_project_path` suggestion after confirming the directory exists.
- `PROJECT_DIRECTORY_NOT_FOUND`: fix the project path before diagnosing Node or executable installation.
- `SLIDEP_WATCHER_UNRELIABLE`: use batch edits plus stop/start and verify the final deck.
