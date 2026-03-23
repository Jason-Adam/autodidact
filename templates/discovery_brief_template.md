Discovery brief format for fleet workers (~500 tokens max):

```
DISCOVERY BRIEF (Wave [N], Worker [task_id]):
- Changed: [file1.py] (added auth middleware); [file2.py] (updated imports)
- Added: [new_file.py] (token validation dataclass)
- Removed: [old_file.py] (deprecated handler)
- Key finding: [most important thing the next wave needs to know]
- Risk: [anything that might cause problems downstream]
- Dependencies: [what subsequent work depends on from this change]
- Tests: [test status — passed/failed/skipped]
```

Rules:
- Under 500 tokens
- Focus on WHAT changed, not HOW
- Key findings and risks are most important for next wave
- File descriptions are 1 clause each
- Skip sections that don't apply
