---
description: Teach autodidact new knowledge or query the learning database.
model: sonnet
---

You are tasked with managing autodidact's learning database.

If the user provided arguments after `/learn`, treat them as knowledge to record:
1. Extract a topic, key, and value from the input
2. Record it in the learning DB with confidence 0.7 (user-taught)
3. Confirm what was stored

If the user wants to query (e.g., `/learn query <terms>`), search the FTS5 index and display results.

If the first argument is `mine` (e.g., `/learn mine /path/to/project`), call `mine_and_record()` from `src.session_miner` with the given project path and the active LearningDB. Display the returned summary dict showing sessions_scanned, commands_found, patterns_found, and learnings_recorded.

Use the autodidact-learn skill for the full protocol.
