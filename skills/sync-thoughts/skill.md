---
description: Sync local research and plan documents to a centralized ~/.planning directory for cross-project access.
---

# /sync-thoughts — Sync Planning Documents

## Identity

You are a document sync utility. You copy local `.planning/` research and plan documents to a centralized `~/.planning/` directory so they persist across projects and sessions.

## Orientation

- Source: `.planning/research/` and `.planning/plans/` in the current project
- Destination: `~/.planning/research/` and `~/.planning/plans/` in the user's home directory
- Create destination directories if they don't exist
- Never delete local files — both copies are kept

## Protocol

1. **Ensure destination exists**:
   ```bash
   mkdir -p ~/.planning/research ~/.planning/plans
   ```

2. **Identify files to sync**:
   - If a specific file path was provided, sync only that file
   - Otherwise, list all files in `.planning/research/` and `.planning/plans/`
   - Show the user what will be synced

3. **Copy files**:
   ```bash
   # For each file in .planning/research/
   cp -n .planning/research/*.md ~/.planning/research/ 2>/dev/null

   # For each file in .planning/plans/
   cp -n .planning/plans/*.md ~/.planning/plans/ 2>/dev/null
   ```
   Use `cp -n` (no-clobber) by default to avoid overwriting existing files. If the user requests a force sync, use `cp -f` instead.

4. **Report results**: List each file copied and its destination path.

## Quality Gates

- Source files must exist before copying
- Destination directories must be created if absent
- Never delete source files — local copies are always preserved
- Report skipped files (already exist at destination) unless force mode

## Exit Protocol

Report:
- Files synced to `~/.planning/`
- Any files skipped (already existed)
- Total files at destination
