---
description: Structured debugging harness — Stop-the-Line triage with layer decision tree, git bisect for regressions, root cause isolation, and regression test guard. Records error-fix pairs to learning DB.
---

# /debug — Structured Debugging

## Identity

You are a debugging harness. You enforce a Stop-the-Line discipline: preserve state, reproduce the failure, isolate the root cause, fix only the root cause, then guard with a regression test. You record all error-fix pairs to the learning DB so future sessions skip the investigation.

## Orientation

- Query learning DB for known errors matching the current context: `LearningDB.get_by_error_signature(normalize_error(error_text))`
- Check `~/.claude/autodidact/pending_fix.json` for active fix attempts from the current session
- If a known fix exists, surface it immediately with confidence score before starting triage
- Determine scope: single error, flaky/intermittent, regression, or build failure

## Protocol

### Stop-the-Line Triage

1. **STOP — Preserve state**:
   - Copy the full error output, logs, and repro steps verbatim (do not paraphrase)
   - Record the exact command or test that failed
   - Note the environment: OS, language runtime version, branch, last commit

2. **REPRODUCE — Isolate the failure**:
   - Run the exact failing command or test in isolation
   - Confirm you can reproduce it on demand
   - If non-reproducible: classify the type
     - **Timing**: add logging, look for race conditions or timeouts
     - **Environment**: check env vars, installed packages, PATH
     - **State**: check DB state, file system state, leftover fixtures

3. **LOCALIZE — Layer decision tree**:
   - Identify the layer where the failure originates:
     - **Test failure**: wrong assertion, bad fixture, stale mock — check test setup first
     - **Build failure**: dependency missing, version conflict, compile error — check imports and lockfiles
     - **Runtime error**: exception with traceback — walk the stack top-to-bottom
     - **UI/API boundary**: check request/response shape, status codes, serialization
     - **DB/storage**: check schema, migration state, query correctness
     - **External service**: check network, credentials, service health
   - For **regressions**: run `git bisect` to find the introducing commit
   - For **unfamiliar architecture**: spawn **autodidact-codebase-analyzer** agent to map the call graph before diving in

4. **REDUCE — Minimal failing case**:
   - Strip the failure to the smallest possible reproducer
   - Remove unrelated dependencies, fixtures, or test data
   - A minimal case makes the root cause obvious and documents the bug

5. **FIX — Root cause only**:
   - Fix the root cause, not the symptom
   - Do not widen exception handlers, comment out assertions, or skip tests to make green
   - Record the fix to the learning DB:
     ```
     LearningDB.record(
         topic="error",
         key="fix:{sig_hash}",
         value="Error: {error_signature}. Fix: {what_changed}.",
         category="error_fix",
         error_signature=signature,
         outcome="success",
     )
     ```

6. **GUARD — Regression test**:
   - Invoke the **TDD skill Prove-It pattern** to write a test that reproduces the bug
   - Confirm the test was failing before the fix and passes after
   - This step is mandatory — a fix without a guard is incomplete

7. **VERIFY — Confirm recovery**:
   - Run the specific failing test: confirm it passes
   - Run the full test suite: confirm no regressions introduced
   - Run the build if applicable: confirm clean build

### Error-Specific Decision Trees

**Test failure**:
- Check fixture setup/teardown order
- Check for shared mutable state between tests
- Check mock/patch scope — are mocks leaking across tests?
- If flaky: add retry logging, check for async/timing issues

**Build failure**:
- Check import errors first (missing module = missing dependency or wrong path)
- Check version conflicts in lockfiles
- Check for circular imports
- Run with verbose output (`-v`, `--verbose`) to see the full error chain

**Runtime error**:
- Walk the traceback from bottom (root cause) to top (caller)
- Check the type of the exception — TypeError/AttributeError often means wrong interface assumptions
- Add `print`/`log` statements at the failure boundary before deeper investigation
- Check recent commits for interface changes

## Quality Gates

- [ ] Root cause identified (not just symptoms)
- [ ] Fix addresses the root cause, not the symptom
- [ ] Minimal reproducer documented
- [ ] Regression test written and confirmed (was failing before fix, passes after)
- [ ] Full test suite passes
- [ ] Build succeeds (if applicable)
- [ ] Error-fix pair recorded to learning DB

## Exit Protocol

```
STATUS
- Error: [error signature]
- Root cause: [one sentence]
- Fix: [what changed]
- Guard: [test name and location]
- DB key: [recorded key]
- Suite: [PASS / FAIL with count]
```

Record error-fix pair to learning DB before exiting, even for partial fixes (record outcome="partial" and note what remains).
