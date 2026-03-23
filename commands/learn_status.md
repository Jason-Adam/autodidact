---
description: Show confidence stats and knowledge inventory from the autodidact learning database.
model: sonnet
---

You are tasked with showing the current state of autodidact's learning database.

Run the following to get stats:
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

Present the results in a readable format:
1. **Summary**: Total learnings, average confidence, graduated count
2. **Top Learnings**: Highest confidence items (topic, key, value, confidence)
3. **Graduation Candidates**: Items ready to be promoted (confidence ≥ 0.9, observations ≥ 5)
4. **Routing Gaps**: Recent unmatched prompts (if any)
