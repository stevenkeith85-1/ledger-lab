# Architecture Decision Records

ADRs are the source of truth for LedgerLab decisions that later code must follow. An ADR records the context, the options that were compared, the decision, and the consequences. Code, reviews, and tests point here. They do not restate the decision.

Each ADR uses these sections:

1. **Status** — `Proposed`, `Accepted`, `Superseded`, or `Deprecated`.
2. **Context** — the problem and the constraints that force a decision.
3. **Options considered** — each alternative, with its advantages and its costs.
4. **Decision** — the normative rule. An implementer should be able to code from this section.
5. **Consequences** — what follows, including non-functional effects, verification, and open points.

Status sits at the top of the file so a reader sees it first. An ADR is accepted when its PR is merged by the principal engineer. A change of mind is a new ADR that marks the old one `Superseded`. Accepted ADRs stay in this directory.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-canonical-serialisation.md) | Canonical serialisation | Accepted |
| [0002](0002-integer-amounts.md) | Integer amounts | Accepted |

Machine-readable vectors for ADR 0001 and ADR 0002 live in [vectors/serialisation.json](vectors/serialisation.json). Regenerate that file with [vectors/generate.py](vectors/generate.py); do not edit it by hand.

```sh
python docs/adr/vectors/generate.py
```

## AGENTS.md

[SCRUM-13](https://stevenkeith85.atlassian.net/browse/SCRUM-13) owns `AGENTS.md`. When that file lands, it should link to this index and to the two ADRs above, and it should not copy the byte layout or the amount rules. This change does not add that line.
