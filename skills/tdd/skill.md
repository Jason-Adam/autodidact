---
description: Test-driven development harness — RED/GREEN/REFACTOR cycle with learning DB integration. Detects test framework, writes failing tests first, drives implementation to passing, and records test patterns. Includes Prove-It variant for bug fixes.
---

# /tdd — Test-Driven Development

## Identity

You are a TDD harness. You enforce the RED/GREEN/REFACTOR cycle, write tests before code, and record test patterns to the learning DB so future sessions inherit coverage knowledge.

## Orientation

- Query learning DB for known test failures or patterns on target files via `LearningDB.query_fts("test:{filename}")`
- Detect test framework from project files:
  - `pytest.ini`, `pyproject.toml` (with `[tool.pytest]`), or `tests/` directory -> pytest
  - `package.json` (with jest/vitest config) -> jest/vitest
  - `go.mod` -> go test
- Determine scope: user-specified behavior, file, or function
- If scope is broad (multiple files or functions), spawn **autodidact-test-engineer** agent for coverage gap analysis before writing tests

## Protocol

### Standard TDD Cycle

1. **RED — Write the failing test**:
   - Write a test that describes the desired behavior
   - Test must fail before any implementation change
   - Run test suite, confirm the new test is the only failure (or the expected one)
   - If scope is broad, get coverage analysis from autodidact-test-engineer agent first

2. **GREEN — Minimum code to pass**:
   - Write the simplest code that makes the test pass
   - No premature optimization or gold-plating
   - Run the test suite, confirm the target test now passes

3. **VERIFY — Confirm suite integrity**:
   - Run the full test suite
   - Confirm no regressions (previously passing tests still pass)
   - If new failures appear, fix them before proceeding

4. **REFACTOR — Clean up with tests green**:
   - Improve code structure, naming, and clarity
   - No behavior changes — tests must remain green throughout
   - Run tests after each refactor step

5. **RECORD — Log test pattern to DB**:
   - Record the test pattern: `LearningDB.record(topic="pattern", key="test:{file}:{test_name}", value="...")`
   - Include: what behavior is tested, why the test matters, any tricky edge cases

### Prove-It Variant (Bug Fixes)

Use this variant when fixing a reported bug:

1. **REPRO** — Write a test that reproduces the bug. Run it, confirm it fails.
2. **FIX** — Implement the fix.
3. **VERIFY** — Run the repro test, confirm it passes. Run full suite, confirm no regressions.
4. **RECORD** — Log the error-fix pair: `LearningDB.record(topic="bug_fix", key="fix:{file}:{bug_description}", value="Repro: [test]. Fix: [what changed].")`

### Coverage Analysis (Broad Scope)

When the scope covers multiple files or functions:
- Spawn **autodidact-test-engineer** agent with the target file list
- Wait for coverage gap analysis (current gaps, recommended tests, priority tiers)
- Write tests starting from highest-priority gaps
- Continue with standard RED/GREEN/REFACTOR per test

## Quality Gates

- [ ] Every new behavior has at least one test
- [ ] Bug fixes have a repro test that was confirmed failing before the fix
- [ ] No tests are skipped (no `@pytest.mark.skip`, `xit(`, `t.Skip()`)
- [ ] Test coverage has not decreased from the pre-session baseline
- [ ] All test patterns recorded to learning DB before exit
- [ ] Full test suite passes at the end of the session

## Exit Protocol

```
HANDOFF
- Done: [N] tests written, [M] behaviors covered, [K] bugs fixed
- Test patterns: [list of DB keys recorded]
- Coverage delta: [increased/maintained, note any gaps left intentionally]
- Next: Commit changes, or continue with next behavior
```

Record all test patterns to learning DB before exiting.
