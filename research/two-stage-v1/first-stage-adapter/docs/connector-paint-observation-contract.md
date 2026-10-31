# Existing verifier: connector contribution attention and actual residual concerns

When enabled, read the supplied exact packet, candidate receipt SHA and connector-concern-context.json in this same verifier slot. Four global NW/NE/SW/SE half-open cell summaries are attention hints only. They are not arrow counts, identities, source necessity, preservation certification or edit permission. Zero/unavailable data is not visual evidence. No per-cell review, extra image, model stage or fourth attempt is required. Probe PNGs/NPZ/full fields remain local audit-only and must not be loaded into model image payloads.

Use the supplied raster_aliases: source_png and original_png denote the frozen actual original raster, before_png the exact host-resolved retained-before raster, and candidate_png/current_png the existing actual candidate raster. Evidence artifact IDs are exactly original_png, before_png, candidate_png. Use the actual raw SHA and positive integer in-bounds [x,y,width,height]. Source dimensions may differ. Historical observations retain their own original before/observed paths and complete text/evidence; they are not the current before/current candidate.

Return exactly one connector_paint_ack object with mode, packet_sha256, manifest_sha256, policy_sha256, producer_sha256 (copied from candidate.connector_paint), candidate_receipt_sha256 (supplied by host), source_sha256, before, candidate, field_status (copied from packet), and use='attention_hint_only'. Never put this acknowledgement in an array. The existing native report fields/partitions/uncertainty/pending/promotion guards remain mandatory.

connector_visual_concerns is an array of independently articulated actual visible concerns that cannot safely bind to a current native issue. Each exact row is {concern_id,concern_text,source_obligation,source_evidence,before_evidence,current_evidence,why_unbound}; evidence is {text,artifact_id,sha256,region_xywh}. Use source/before/candidate evidence respectively. No origins/authority/host metadata are model supplied. Cell names, native IDs and all active/retired residual IDs are reserved. Unavailable/zero/no markers/bare regression text cannot generate a concern. Use native new_required_findings/new_uncertain_findings when representable, retaining original native rules.

connector_concern_reviews exactly partitions every prior active concern ID once. Exact row: {concern_id,decision,source_evidence,current_evidence,reason,native_issue_id}. Decision is defer, dismiss_current or transfer_to_native. Use original_png and actual current candidate_png evidence; native_issue_id must be null except transfer_to_native, which must name a validated surviving current required/uncertain native finding after native triage. Missing review rejects; defer preserves the original record. Dismissal or transfer gives zero repair/false-positive credit, including an exact no-op review. Residual concerns never authorize planner work and residual-only status is inconclusive.

A protected regression rolls back the full candidate: no concern retirement/transfer, native promotion/pending triage or queue change commits. Only actual new independently articulated concerns are retained as rejected-candidate observations. Native rollback/required/pending status priorities remain. Unresolved third-round concerns terminate inconclusive; there is no fourth attempt. Clean native runtime remains pending independent evaluation and visual_passed is always false. Strict enabled raw parsing rejects duplicate keys/nonfinite values after original final bytes are frozen; do not normalize or resubmit rejected finals.

The exact runtime schema is embedded in the frozen connector_paint_contract.py and validated by the host. This document explains required packet/report semantics without exposing renderer internals as model instructions. Current/historical origin validation and all artifact hashes are host responsibilities. Scripted synthetic tests establish mechanics only, not model truth or effectiveness.

Exact frozen model-facing definitions (acknowledgement is connector_paint_ack; new_concern and concern_review are individual array entries):

```json
{
  "$defs": {
    "acknowledgement": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "mode",
        "packet_sha256",
        "manifest_sha256",
        "policy_sha256",
        "producer_sha256",
        "candidate_receipt_sha256",
        "source_sha256",
        "before",
        "candidate",
        "field_status",
        "use"
      ],
      "properties": {
        "mode": {
          "const": "connector-paint-global-v2"
        },
        "packet_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "manifest_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "policy_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "producer_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "candidate_receipt_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "source_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "before": {
          "$ref": "#/$defs/endpoint"
        },
        "candidate": {
          "$ref": "#/$defs/endpoint"
        },
        "field_status": {
          "enum": [
            "field_available",
            "field_unavailable"
          ]
        },
        "use": {
          "const": "attention_hint_only"
        }
      }
    },
    "new_concern": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "concern_id",
        "concern_text",
        "source_obligation",
        "source_evidence",
        "before_evidence",
        "current_evidence",
        "why_unbound"
      ],
      "properties": {
        "concern_id": {
          "type": "string",
          "minLength": 1
        },
        "concern_text": {
          "type": "string",
          "minLength": 1
        },
        "source_obligation": {
          "type": "string",
          "minLength": 1
        },
        "source_evidence": {
          "$ref": "#/$defs/visual_evidence"
        },
        "before_evidence": {
          "$ref": "#/$defs/visual_evidence"
        },
        "current_evidence": {
          "$ref": "#/$defs/visual_evidence"
        },
        "why_unbound": {
          "type": "string",
          "minLength": 1
        }
      }
    },
    "concern_review": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "concern_id",
        "decision",
        "source_evidence",
        "current_evidence",
        "reason",
        "native_issue_id"
      ],
      "properties": {
        "concern_id": {
          "type": "string",
          "minLength": 1
        },
        "decision": {
          "enum": [
            "defer",
            "dismiss_current",
            "transfer_to_native"
          ]
        },
        "source_evidence": {
          "$ref": "#/$defs/visual_evidence"
        },
        "current_evidence": {
          "$ref": "#/$defs/visual_evidence"
        },
        "reason": {
          "type": "string",
          "minLength": 1
        },
        "native_issue_id": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1
            },
            {
              "type": "null"
            }
          ]
        }
      }
    },
    "visual_evidence": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "text",
        "artifact_id",
        "sha256",
        "region_xywh"
      ],
      "properties": {
        "text": {
          "type": "string",
          "minLength": 1
        },
        "artifact_id": {
          "type": "string",
          "minLength": 1
        },
        "sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "region_xywh": {
          "type": "array",
          "minItems": 4,
          "maxItems": 4,
          "items": {
            "type": "integer",
            "minimum": 0
          }
        }
      }
    },
    "packet": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "schema_version",
        "mode",
        "policy_sha256",
        "producer_sha256",
        "producer_version",
        "metric_version",
        "manifest_sha256",
        "source_sha256",
        "before",
        "candidate",
        "field_status",
        "unavailable_reason",
        "cells",
        "audit",
        "limitations",
        "before_locator"
      ],
      "properties": {
        "schema_version": {
          "const": "connector-paint-packet-v2"
        },
        "mode": {
          "const": "connector-paint-global-v2"
        },
        "policy_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "producer_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "producer_version": {
          "type": "string",
          "minLength": 1
        },
        "metric_version": {
          "type": "string",
          "minLength": 1
        },
        "manifest_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "source_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "before": {
          "$ref": "#/$defs/endpoint"
        },
        "candidate": {
          "$ref": "#/$defs/endpoint"
        },
        "field_status": {
          "enum": [
            "field_available",
            "field_unavailable"
          ]
        },
        "unavailable_reason": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1
            },
            {
              "type": "null"
            }
          ]
        },
        "cells": {
          "type": "array",
          "minItems": 4,
          "maxItems": 4,
          "items": {
            "$ref": "#/$defs/cell"
          }
        },
        "audit": {
          "anyOf": [
            {
              "$ref": "#/$defs/artifact"
            },
            {
              "type": "null"
            }
          ]
        },
        "limitations": {
          "type": "array",
          "items": {
            "type": "string",
            "minLength": 1
          }
        },
        "before_locator": {
          "$ref": "#/$defs/before_locator"
        }
      }
    },
    "cell": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "cell",
        "region_xywh",
        "counts"
      ],
      "properties": {
        "cell": {
          "enum": [
            "NW",
            "NE",
            "SW",
            "SE"
          ]
        },
        "region_xywh": {
          "type": "array",
          "minItems": 4,
          "maxItems": 4,
          "items": {
            "type": "integer",
            "minimum": 0
          }
        },
        "counts": {
          "anyOf": [
            {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "before_nonzero",
                "candidate_nonzero",
                "lost",
                "gained",
                "altered",
                "changed"
              ],
              "properties": {
                "before_nonzero": {
                  "type": "integer",
                  "minimum": 0
                },
                "candidate_nonzero": {
                  "type": "integer",
                  "minimum": 0
                },
                "lost": {
                  "type": "integer",
                  "minimum": 0
                },
                "gained": {
                  "type": "integer",
                  "minimum": 0
                },
                "altered": {
                  "type": "integer",
                  "minimum": 0
                },
                "changed": {
                  "type": "integer",
                  "minimum": 0
                }
              }
            },
            {
              "type": "null"
            }
          ]
        }
      }
    },
    "before_locator": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "kind",
        "run_id",
        "relative_path",
        "origin_round",
        "evidence",
        "acceptance_receipt_path",
        "acceptance_receipt_sha256"
      ],
      "properties": {
        "kind": {
          "enum": [
            "frozen_initial",
            "accepted_candidate"
          ]
        },
        "run_id": {
          "enum": [
            "run1",
            "run2",
            "run3"
          ]
        },
        "relative_path": {
          "type": "string",
          "minLength": 1
        },
        "origin_round": {
          "type": "integer",
          "minimum": 0,
          "maximum": 2
        },
        "evidence": {
          "$ref": "#/$defs/full_evidence"
        },
        "acceptance_receipt_path": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1
            },
            {
              "type": "null"
            }
          ]
        },
        "acceptance_receipt_sha256": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^[0-9a-f]{64}$"
            },
            {
              "type": "null"
            }
          ]
        }
      }
    },
    "full_evidence": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "revision",
        "evidence_hashes",
        "pair_hashes",
        "required_regions"
      ],
      "properties": {
        "revision": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "evidence_hashes": {
          "type": "object",
          "additionalProperties": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$"
          }
        },
        "pair_hashes": {
          "type": "object",
          "additionalProperties": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$"
          }
        },
        "required_regions": {
          "type": "array",
          "items": {
            "type": "string",
            "minLength": 1
          },
          "uniqueItems": true
        }
      }
    },
    "endpoint": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "revision",
        "evidence_hashes"
      ],
      "properties": {
        "revision": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "evidence_hashes": {
          "type": "object",
          "additionalProperties": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$"
          }
        }
      }
    },
    "artifact": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "path",
        "sha256"
      ],
      "properties": {
        "path": {
          "type": "string",
          "minLength": 1
        },
        "sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        }
      }
    }
  }
}
```
