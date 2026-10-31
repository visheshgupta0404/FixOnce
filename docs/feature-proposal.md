# Meko feature proposal: correctable shared knowledge

Team FixOnce (Vedansh Mathur, Vishal Verma, Vishesh Gupta), hackCBS 9.0, Meko challenge Track A.

## 1. The friction

FixOnce promotes a lesson to shared team knowledge once a human confirms the fix held. Building it
against the live Meko server, we hit a wall right after that step:

- **Promotion is one-way.** `memory_promote` moves the memory out of mem0 into the knowledge base.
  After that, `memory_get_by_id` says `not_found`, `memory_update` and `memory_delete_by_id` fail
  with a server error, and `knowledgebase_delete_document` returns 404 for its chunk. No MCP tool
  can correct or retract a promoted memory.
- **So the most trusted knowledge is the least fixable.** A runbook step that was right on v1.6 and
  wrong on v1.7 stays in shared knowledge forever, with no way to mark it outdated. A test memory we
  promoted by mistake is still in our product datapack and can only be removed by hand in the UI.
- **Promoted memories also drop out of the default search.** `context_search` applies a distance floor
  to the knowledge-base bucket, and our promoted lessons (rerank score 0.9999, distance 0.98) were
  filtered out, so recall returned nothing right after we promoted the seeded history.

Our workarounds: recall calls `knowledgebase_search` next to `context_search` and reads the memory id
back from `metadata_filters.memory_id`; Correct and Forget refuse promoted lessons with a plain
message instead of pretending to succeed; the demo corrects a lesson *before* promoting it.

Evidence in `fixonce-build` (promoted decisions and build notes): `d57f38e6` (promotion is one-way,
tested on live Meko), `a3820218` and `0240efe8` (promoted lessons hidden from `context_search`),
`d2901c94` (promoted lessons locked in the product).

## 2. The feature (in Meko terms)

**Promoted memories stay correctable, with history.** A promoted memory keeps a stable id and gains
revisions. Owners and maintainers can revise or retract it. Recall returns the latest revision,
says it is promoted, and can scope by version, so an older revision comes back flagged as possibly
stale instead of being silently wrong or silently hidden.

## 3. The interface

```
memory_revise(memory_id="0dfc80eb-...", text="...pause_batch_job, then raise_pool_size is safe on v1.7",
              valid_from_version="v1.7", reason="pool cap raised in v1.7", conversation_id="...")
-> {"id": "0dfc80eb-...", "revision": 2, "promoted": true, "superseded": [1]}

memory_retract(memory_id="29fbb2e9-...", reason="test data, promoted by mistake", conversation_id="...")
-> {"id": "29fbb2e9-...", "retracted": true}          # hidden from recall, kept in history

context_search(query="checkout db timeouts", valid_for_version="v1.7", conversation_id="...")
-> {"results": {"memory": [{"id": "0dfc80eb-...", "memory": "...", "score": 0.82, "promoted": true,
                            "revision": 2, "version": "v1.7", "stale": false}], ...}}
```

`memory_update` and `memory_delete_by_id` on a promoted id would map to `memory_revise` and
`memory_retract`, so existing clients stop failing with a server error.

## 4. Scenario, before and after

**Before.** Night shift confirms "pause the export job, never raise the pool size" and promotes it.
In v1.7 the DB connection cap is raised and raising the pool becomes the right first step. The
promoted lesson cannot be changed. Every on-call for every later incident is steered away from the
right fix, and the only way out is deleting it by hand in a UI, which also loses the history.

**After.** The engineer who learns the new behaviour taps Correct. Meko stores revision 2 for v1.7
with the reason. Recall on v1.7 returns revision 2; recall for a v1.6 rollback still finds
revision 1, flagged as for an older version. Nothing true is lost and nothing stale is served
as current.

## 5. Why it's new

Context layers treat shared knowledge as append-only documents: you can add a better note, but the
old one keeps being retrieved next to it, with the same weight. Code and runbooks have versions;
memory does not. A promoted memory that can be revised, retracted and scoped to a version makes
team knowledge behave like code: reviewed, versioned, and safe to correct.

## 6. Risks

- **Abuse or mistakes:** only owners and maintainers can revise or retract (same rule as promote);
  every revision records who, when and why, and old revisions stay readable.
- **Privacy:** retract hides a memory from recall but keeps history, so personal data also needs a
  true purge; we propose `memory_retract(purge=true)` for owners, which removes every revision.
- **Cost:** revisions are small text rows; the knowledge-base index only needs the latest revision
  per id, plus older ones when a version scope asks for them.
