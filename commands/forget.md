---
description: Decay or remove specific learnings from the autodidact database.
model: sonnet
---

You are tasked with removing or decaying knowledge in autodidact's learning database.

1. If the user specifies what to forget, search the DB for matching learnings
2. Show the matches and ask for confirmation
3. Options:
   - **Decay**: Reduce confidence by 0.3 (learning fades but isn't deleted)
   - **Delete**: Remove entirely from the DB
4. Execute the chosen action and confirm

Use `LearningDB.query_fts(search_text)` to find matches, then apply the appropriate action.
