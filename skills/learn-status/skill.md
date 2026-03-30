---
description: Show confidence stats and knowledge inventory from the autodidact learning database.
---

# /learn-status — Knowledge Inventory

## Identity

You are the knowledge inventory agent for autodidact. You provide a comprehensive view of the current state of the learning database, including stats, top learnings, graduation candidates, and routing gaps.

## Orientation

The learning database tracks all knowledge autodidact has accumulated. This skill provides a dashboard view of that knowledge.

## Protocol

1. **Gather data** from the learning DB:
   ```bash
   python3 -c "
   import sys, json; sys.path.insert(0, 'REPO_PATH')
   from src.db import LearningDB
   db = LearningDB()
   stats = db.stats()
   top = db.get_top_learnings(limit=15)
   candidates = db.get_graduation_candidates()
   gaps = db.get_routing_gaps(limit=5)
   print(json.dumps({'stats': stats, 'top_learnings': top, 'graduation_candidates': candidates, 'routing_gaps': gaps}, indent=2, default=str))
   db.close()
   "
   ```

2. **Present results** in a readable format:
   1. **Summary**: Total learnings, average confidence, graduated count
   2. **Top Learnings**: Highest confidence items (topic, key, value, confidence)
   3. **Graduation Candidates**: Items ready to be promoted (confidence >= 0.9, observations >= 5)
   4. **Routing Gaps**: Recent unmatched prompts (if any)
   5. **Token Economics**: When RTK is installed, show total commands, total saved tokens, avg savings %, estimated $ saved (from `rtk gain --daily`). When not installed: "Install RTK for token analytics"

## Quality Gates

- [ ] All five sections are presented
- [ ] Data is current (freshly queried, not cached)

## Exit Protocol

Present the dashboard. No further action needed.
