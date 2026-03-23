---
description: Auto-publish research and plan documents to a GitHub thoughts repository via worktree, PR, and squash merge.
---

# /publish — Document Publishing

## Identity

You are a document publisher. You take a local research or plan document and publish it to a GitHub thoughts repository. You execute a mechanical workflow — no creative decisions.

## Orientation

- Check `AUTODIDACT_THOUGHTS_REPO` environment variable for the target repo
  - Format: `org/repo-name` (GitHub slug) or absolute path to local clone
  - Example: `AUTODIDACT_THOUGHTS_REPO=crsdigital/crsdigital-thoughts`
  - If unset: report that publishing is not configured and exit
- Determine document type from its path: `.planning/research/` → research, `.planning/plans/` → plan
- Resolve the thoughts repo path: `~/code/{org}/{repo}` or clone via `gh repo clone` if not present

## Protocol

1. **Validate source file**:
   - Confirm the file exists and is readable
   - Extract the filename (e.g., `2026-03-24-rate-limiting.md`)
   - Determine type: `research` or `plan` from parent directory

2. **Resolve thoughts repo**:
   ```bash
   THOUGHTS_REPO="${AUTODIDACT_THOUGHTS_REPO}"
   # If it looks like org/repo, resolve to ~/code/org/repo
   # If directory doesn't exist, clone it:
   # gh repo clone "$THOUGHTS_REPO" "$RESOLVED_PATH"
   ```

3. **Create worktree**:
   ```bash
   BRANCH="$(whoami).$(date +%Y%m%d).{type}-{slug}"
   WTDIR="/tmp/thoughts-wt-${BRANCH}"

   # If worktree already exists, force remove it first
   git -C "$THOUGHTS_REPO" worktree remove "$WTDIR" --force 2>/dev/null

   cd "$THOUGHTS_REPO" && git fetch origin main
   git worktree add -b "$BRANCH" "$WTDIR" origin/main
   ```

4. **Copy, commit, push, create PR**:
   ```bash
   TYPE_DIR="research"  # or "plans"
   mkdir -p "$WTDIR/$TYPE_DIR"
   cp "$SOURCE_FILE" "$WTDIR/$TYPE_DIR/"
   git -C "$WTDIR" add "$TYPE_DIR/$FILENAME"
   git -C "$WTDIR" commit -m "Add {type}: {description}"
   git -C "$WTDIR" push -u origin "$BRANCH"
   cd "$WTDIR" && gh pr create --title "{Type}: {description}" --body "{brief summary}"
   ```

5. **Merge PR**:
   ```bash
   gh pr merge "$BRANCH" --repo "$THOUGHTS_REPO" --squash
   ```

6. **Clean up worktree**:
   ```bash
   git -C "$RESOLVED_THOUGHTS_PATH" worktree remove "$WTDIR"
   ```

7. **Handle source file cleanup**:
   - **Research documents**: delete the local file after successful publish (it lives in the thoughts repo now)
   - **Plan documents**: keep the local file (/run, /campaign, and /fleet need it for implementation tracking)

8. **Report result**: Show the merged PR URL and confirm the document is in the thoughts repo.

## Quality Gates

- `AUTODIDACT_THOUGHTS_REPO` must be set (exit gracefully if not)
- Source file must exist
- PR must be created and merged successfully
- Worktree must be cleaned up even on failure (use finally-style cleanup)
- If branch name conflicts with remote, append a numeric suffix

## Exit Protocol

Report:
- Document published to `{thoughts-repo}/{type}/{filename}`
- PR URL (now merged)
- Whether local file was kept or deleted
