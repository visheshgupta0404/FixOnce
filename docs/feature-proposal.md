# Meko feature proposal: versioned memories (DRAFT)

Write this from friction we actually hit while building. Save evidence in `fixonce-build` as it happens.
If a different friction hurts more, propose that instead. 1-3 pages.

## 1. The friction
_What we could not do, or did awkwardly, and our workaround. Link the build-datapack entries._

## 2. The feature (in Meko terms)
A memory can carry a version scope (git SHA or deploy ID). Recall can ask for memories valid for a
version; older ones come back flagged as possibly stale, never hidden.

## 3. The interface
```
memory_search(query="checkout db timeouts", datapack_id="...", valid_for_version="v1.7")
-> {"results": [{"id": "...", "memory": "...", "score": 0.82,
                 "version": "v1.6", "stale": true, "superseded_by": null}]}
```

## 4. Scenario, before and after
Before: _..._  After: _..._

## 5. Why it's new
_What no context layer does today._

## 6. Risks
_Privacy, cost, abuse, and how to limit them._
