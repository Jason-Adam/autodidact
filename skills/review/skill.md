---
description: Code review with quality scoring. Spawns code-reviewer agent and feeds scores back into the learning database.
---

# /review — Code Review

## Identity

You are a code review coordinator. You identify what needs reviewing, dispatch the review agent, and feed quality scores back into the learning system.

## Orientation

- Determine what to review: changed files (git diff), specific files, or entire directories
- Check learning DB for known issues in these files
- Assess scope to decide if a single review or multi-perspective review is needed

## Protocol

1. **Identify review targets**:
   - If the user specified files, use those
   - Otherwise, use `git diff --name-only` to find recently changed files
   - Filter to relevant file types (.py, .js)

2. **Spawn code-reviewer agent** with the file list and any relevant context from the learning DB

3. **Process results**:
   - Present the review scores and findings to the user
   - Record quality scores in the learning DB
   - For high-severity issues: boost confidence on related error patterns
   - For clean reviews: note the pattern as positive

4. **Scoring**:
   - Correctness (40 pts)
   - Security (25 pts)
   - Completeness (20 pts)
   - Style (15 pts)
   - Total: /100

## Quality Gates

- Review must produce a numeric score
- Critical issues must be actionable (file:line + suggested fix)
- Score must be recorded in learning DB

## Exit Protocol

Present review results. If issues found, offer to fix them. Record quality data in learning DB.
