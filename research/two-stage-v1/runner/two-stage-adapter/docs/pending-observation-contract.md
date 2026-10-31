# Pending observation lifecycle contract v1

This is this-run workflow memory for findings first discovered on a protected-regression candidate. It adds no model role/stage, native method, renderer, taxonomy, geometry/coordinate change, extra repair attempt or external-label input. Original/SAM absolute placement, translation, scope guards, rollback and max three attempts remain intact. Initial main/semantic prompts remain byte-identical. Source/current visual necessity is a verifier judgment; schema validation is not visual proof. The separate per-finding resolution-support gap remains unaddressed.

## Pure helper interfaces

`capture_pending(existing, findings, *, raw_sha256, observed_revision, retained_revision, before_evidence_hashes, observed_evidence_hashes, round_number, report_path) -> list[dict]` deep-copies prior pending rows and new original findings without granting authority. Duplicate IDs reject. Caller has already validated new findings against the rejected candidate using `flow.validate_issues`.

`triage_pending(pending, reviews, *, active_issues, known_svg_ids, validate_current_issue) -> dict` returns `pending`, `required`, `uncertain`, `receipts` arrays. The callback takes a list of issues and is the existing `flow.validate_issues(rows, actual_candidate_svg)`; it is not a permissive replacement. It validates actual candidate IDs, native issue fields, decisions/categories and real missing-content container. No inputs mutate. Caller must discard all returned triage on rollback.

## Persisted state

`pending_observations` is an array of pending objects. `pending_observation_receipts` is append-only accepted triage history. `historical_finding_ids` is a unique string array reserving every accepted or rejected discovery forever, including pending/promoted/retired IDs. IDs cannot be reintroduced through either new finding array. Existing active/historical IDs are also checked directly against pending/receipt IDs. A pending ID never enters the required/uncertain queues before accepted current review. It is never resolved merely because it is pending or retired.

Each pending object has exactly the following generated fields:

```json
{
  "id": "unique finding ID string",
  "original_finding": {"verbatim": "complete submitted native finding, including any candidate metadata"},
  "original_decision": "confirmed or uncertain",
  "observed_revision": "rejected candidate current.svg SHA-256 string",
  "retained_revision_at_capture": "retained checkpoint current.svg SHA-256 string",
  "raw_sha256": "immutable verifier raw bytes SHA-256 string",
  "report_path": "run-relative round-N/verifier/raw.json string",
  "before_evidence_hashes": {"key": "source/before evidence hash string"},
  "observed_evidence_hashes": {"key": "source/candidate evidence hash string"},
  "observed_round": 1,
  "status": "pending",
  "current_edit_authority": false
}
```

`original_finding` is deep-copied verbatim, not rewritten to a canonical issue or rebound. Source hashes (including original PNG), before hashes, observed hashes, raw report path/hash and rejected revision remain unchanged through defer, another rollback and retirement. Raw files remain protected by their original receipt hashes. A retained receipt embeds the entire observation and exact review, `repair_credit:false`, `reviewed_revision:string`, `reviewed_evidence_hashes:object<string,string>`, `review_round:integer[1,3]` and `review_raw_sha256:string`. Accepted promotion receipts preserve original provenance outside the canonical current issue; current uncertainty uses the normal uncertain queue with this receipt retained by ID. The acceptance file also records committed triage receipts; on rollback both triage and binding receipt arrays are empty.

## Verifier review schema

`pending_observation_reviews` is optional; omission is equivalent to `[]`. The following JSON Schema defines its exact row shape (the native issue definition is shared with existing validator semantics). Required string values containing only whitespace also reject in runtime validation. Array item types are explicit, even when arrays are empty.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "array",
  "items": {
    "oneOf": [
      {"type":"object","additionalProperties":false,"required":["id","decision","evidence","current_issue"],"properties":{"id":{"type":"string","minLength":1},"decision":{"enum":["confirmed_current","uncertain_current"]},"evidence":{"type":"string","minLength":1},"current_issue":{"$ref":"#/$defs/nativeIssue"}}},
      {"type":"object","additionalProperties":false,"required":["id","decision","evidence","reason"],"properties":{"id":{"type":"string","minLength":1},"decision":{"const":"not_present_current"},"evidence":{"type":"string","minLength":1},"reason":{"type":"string","minLength":1}}},
      {"type":"object","additionalProperties":false,"required":["id","decision","evidence","duplicate_of_id"],"properties":{"id":{"type":"string","minLength":1},"decision":{"const":"duplicate_of"},"evidence":{"type":"string","minLength":1},"duplicate_of_id":{"type":"string","minLength":1}}},
      {"type":"object","additionalProperties":false,"required":["id","decision","evidence"],"properties":{"id":{"type":"string","minLength":1},"decision":{"const":"defer"},"evidence":{"type":"string","minLength":1}}}
    ]
  },
  "$defs": {
    "nativeIssue": {
      "type":"object",
      "required":["id","image_id","category","decision","description","original_evidence","current_evidence","target_ids","neighbor_ids"],
      "properties":{
        "id":{"type":"string","minLength":1},
        "image_id":{"const":"case"},
        "category":{"enum":["F","E","B","S1","D","S2","A","C","S4"]},
        "decision":{"enum":["confirmed","uncertain"]},
        "description":{"type":"string","minLength":1},
        "original_evidence":{"type":"string","minLength":1},
        "current_evidence":{"type":"string","minLength":1},
        "target_ids":{"type":"array","items":{"type":"string"},"uniqueItems":true},
        "neighbor_ids":{"type":"array","items":{"type":"string"},"uniqueItems":true},
        "container_id":{"type":["string","null"]},
        "source_issue_id":{"type":"string"},
        "source_role":{"type":"string"}
      }
    }
  }
}
```

Additional runtime cross-field checks are authoritative: each review ID belongs to the pending set and appears once; any explicit review has nonempty source/current evidence. `confirmed_current`/`uncertain_current` needs a matching confirmed/uncertain current issue preserving `id`, `image_id`, `category`, `description`, `original_evidence` and original `source_issue_id`/`source_role` when present. Bindings/current evidence may differ. Unsupported candidate metadata may be omitted. Every target/neighbor/container refers to actual candidate SVG IDs. Empty targets require a real existing `container_id`; this remains insertion scope only. A category/identity rewrite rejects the report and cannot bypass native guards.

`not_present_current` records source/current evidence and reason; no program, resolved increment, false-positive increment or denominator change occurs. `duplicate_of` needs a compatible image/category and valid current bindings of one surviving active issue after normal disposition/bindings; historical/resolved/pending IDs are invalid links. It creates knowledge without erasing that active obligation or earning repair credit. Unsafe/unknown correspondence uses defer. `defer` and omitted reviews preserve the complete pending row and create no retirement/promotion receipt. Their raw explicit evidence remains in the immutable submitted verifier report.

## Existing field types and non-overlap

The existing verifier fields retain their meanings:

- `revision:string`, `evidence_hashes:object<string,string>` match exact actual candidate evidence.
- `resolved_ids:array<string>` and `unresolved_ids:array<string>` contain confirmed active IDs only and, with `not_required:array<{id:string,evidence:nonempty string}>`, exactly partition that queue. Unchanged SVG cannot claim repair resolution.
- `new_required_findings:array<nativeIssue>` uses confirmed, and `new_uncertain_findings:array<nativeIssue>` uses uncertain. IDs are globally new within this run. Neither array reintroduces pending/retired/active/historical IDs.
- `protected_regressions:array<string|object>` retains existing concise-obligation format. Any nonempty list rolls back the entire candidate.
- `examined_regions:array<string>` and `unresolved_regions:array<string>` contain unique current pack region IDs, with unknown/missing coverage inconclusive. These are region ID strings, not finding objects.
- `uncertainty_reviews:array<{id:string,decision:resolved|not_required|uncertain|confirmed,evidence:nonempty string,current_issue?:nativeIssue}>` handles only existing active uncertainties. Its existing confirmed promotion preserves identity/history; it cannot review pending IDs.
- `current_bindings:array<{id:string,target_ids:array<string>,neighbor_ids:array<string>,container_id?:string,evidence:nonempty string}>` handles only surviving unresolved required and unpromoted active uncertain IDs, validated against current SVG. It cannot review or promote pending IDs. Its `evidence` becomes active `current_evidence`.

Legacy `uncertain_findings` is rejected. Planner `issues:array<nativeIssue>` remains an exact permutation of required+uncertain JSON objects; `programs:array<nativeProgram>` cannot borrow pending/retired authority. Planner `unresolved_reasons:array<{issue_id:string,reason:string}>` remains unresolved explanatory data, not an observation review.

## Atomic transition and terminal status

All raw evidence, partitions, new findings, existing reviews/bindings and pending reviews validate before state/checkpoint mutation. On rollback: retain checkpoint and active queues, discard candidate triage/current bindings/dispositions, preserve existing pending/receipts, append newly discovered observations and reserve their IDs. No accepted retirement is inferred from a rejected candidate.

On normal acceptance: compute surviving active findings with current bindings; validate pending reviews against that candidate and those surviving obligations; append legal promotions/uncertainties or knowledge receipts; preserve omitted/defer pending; replace checkpoint through existing acceptance path. Knowledge-only review may accept an unchanged SVG without repair credit. The existing guard still rejects claimed repair resolution on unchanged SVG.

Pending-only work yields `needs_followup` before attempt 3 and `inconclusive` at attempt 3. If confirmed required findings remain, existing `needs_followup`/`unresolved_after_limit` takes priority. Pending can never produce runtime clean. Existing uncertainty/coverage constraints remain. There is no fourth repair attempt. External reference denominator and evaluation are never touched. Frozen `prompt_hashes` includes actual `pending_observations.py` and this document bytes alongside flow/brief/profile/prompts; dispatch/receive/accept reject byte changes during a run.
