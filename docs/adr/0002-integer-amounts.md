# ADR 0002: Integer amounts

- **Status:** Accepted
- **Date:** 2026-10-27
- **Ticket:** [SCRUM-14](https://stevenkeith85.atlassian.net/browse/SCRUM-14)

## Status

Accepted.

## Context

LedgerLab moves value in a UTXO set. Every output has an amount. Those amounts are created in Python, stored in Postgres, sent through a JSON API, and added up in a React or Angular client whose numbers are IEEE-754 binary64.

The wire width is already fixed by [ADR 0001](0001-canonical-serialisation.md): each amount is a `u64`. That width can hold values up to `2**64 - 1`. JavaScript cannot. `Number` loses integer precision above `2**53 - 1` (`9007199254740991`, `Number.MAX_SAFE_INTEGER`). A total that crosses that line displays and compares as a different integer. SCRUM-15 has to reject negative and overflowing amounts, which it cannot do until this ADR states the bound.

The same integers are hashed inside the transaction body. Two encodings of one economic value would be two transaction ids. The domain has to be one set of integers, checked in one place, before anything is signed, stored, or shown.

## Options considered

### Floating point (`float`, `DOUBLE PRECISION`, JavaScript `number` as the source of truth)

Advantages: native in the browser; compact; people already write `1.5` for currency in prototypes.

Costs: binary64 cannot represent every decimal people expect, and above `2**53` it cannot represent every integer. Addition is not exact, so two nodes can disagree on a sum that then becomes a transaction id. Postgres `DOUBLE PRECISION` has the same values. Rejected.

### `Decimal` / `NUMERIC` end to end

Advantages: base-10 quantities such as `1.00` stay exact; Postgres has `NUMERIC`; Python has `decimal.Decimal`.

Costs: `Decimal("1")`, `Decimal("1.0")`, and `Decimal("1.00")` are the same quantity and different encodings. Canonicalising the scale is a second protocol. The wire format in ADR 0001 has no scale field. The browser still needs a non-float transport. `Decimal` also crosses into the node as a type that is easy to mix with `float` by accident. Rejected for the wire, for storage, and for the Python domain model.

### Decimal strings as the only representation, including in Python and Postgres

Advantages: no precision ceiling; JSON and SQL can both store text; the browser will not coerce the value.

Costs: ordering, indexing, and sums become parser problems. `"10"` sorts before `"2"`. Leading zeros, a leading `+`, Unicode digits, and an embedded decimal point create many strings for one amount, so the bytes under the hash drift. A `TEXT` column cannot enforce the numeric bound without a cast that reintroduces an integer. Rejected as the stored and in-process form. A canonical decimal string remains the JSON boundary, below.

### Unbounded integers, with no maximum

Advantages: Python `int` already has arbitrary precision; no ceiling to revisit; sums cannot overflow the type.

Costs: a value the database and the browser cannot hold is a valid Python object, so the bug appears at the boundary instead of at validation. `BIGINT` cannot store it. JavaScript cannot display it. There is no single overflow fixture a test can assert, because there is always a larger integer. Rejected.

### Bounded integers in the smallest unit (chosen)

Advantages: one canonical value per amount; compares, sums, and hashes with ordinary integer rules; fits the `u64` on the wire, Postgres `BIGINT`, and a JavaScript number, so the client can do arithmetic after a careful parse. The upper bound is a constant a test can pin. Headroom remains in the `u64` if a later ADR raises the cap and the client stops using `Number`.

Costs: the unit is indivisible, so the product cannot represent a fraction of it. The cap is far below `2**64 - 1`, and application code must enforce it because the wire width alone will not. JSON must not use a JSON number.

## Decision

Amounts are integers in the smallest indivisible unit. No amount is a fraction. The unit has no smaller subdivision.

Let `MAX_AMOUNT = 2**53 - 1 = 9007199254740991`.

A transaction is valid only when all of the following hold:

- Every output amount `a` satisfies `1 <= a <= MAX_AMOUNT`.
- The sum of that transaction's output amounts is `<= MAX_AMOUNT`.
- Once the spent outputs are known, the sum of that transaction's input amounts is `<= MAX_AMOUNT`.

Zero-value outputs are rejected. A negative amount is rejected. An amount above `MAX_AMOUNT` is rejected even when it fits in a `u64`. Implementations must not clamp, saturate, or truncate.

The sum is computed with arbitrary-precision addition (Python `int`) and then compared to `MAX_AMOUNT`. It is not computed in `float`. Binary64 cannot represent every integer above `2**53`, so a float sum of in-range amounts can be a different integer from the mathematical sum. Fixed-width addition is acceptable only when the type can hold `1000 * MAX_AMOUNT` (the count limit from ADR 0001 times the cap) and the comparison still uses the exact sum. Given those limits the worst-case sum fits in a `u64` and in signed `BIGINT`; the required check is the comparison with `MAX_AMOUNT`, not a wraparound check.

Where each layer stores the integer:

| Layer | Representation |
| --- | --- |
| Wire, ADR 0001 | `u64`, unsigned big-endian. The width stays `u64` so a future cap still fits. Values from `MAX_AMOUNT + 1` through `2**64 - 1` are well-formed integers and invalid amounts. |
| Python domain | `int`. Validators must use `type(value) is int`. |
| JSON API | Canonical decimal string. JSON numbers are rejected on input and are not emitted. |
| Postgres | `BIGINT`, with `CHECK (amount > 0 AND amount <= 9007199254740991)` on every amount column. |
| Vector file | JSON integers. That file is a fixture, not an API payload. See below. |

`bool` is a subclass of `int` in Python. `isinstance(True, int)` is true, and `True == 1`, so a boolean can pass an `isinstance` check and be stored as one unit. Validators reject bool explicitly:

```python
MAX_AMOUNT = 2**53 - 1

def check_amount(value: object) -> int:
    if type(value) is not int:
        raise ValueError("amount must be int")
    if not 1 <= value <= MAX_AMOUNT:
        raise ValueError("amount out of range")
    return value
```

`type(True) is int` is false, so the type test is the whole bool check. Do not coerce with `int(value)` before the test: `int(True)` is `1`, and `int(1.0)` is `1`.

The JSON API accepts and emits one grammar, and nothing else:

- The amount is a string of ASCII digits `0-9`.
- No leading `+` or `-`, no leading zero, no decimal point, no exponent, no whitespace.
- The integer value of the string satisfies `1 <= n <= MAX_AMOUNT`.
- A JSON number, JSON boolean, JSON null, or any other token is rejected, including a number that happens to be a safe integer.

Parse the string with an arbitrary-precision base-10 conversion after the grammar check. `int("01")` in Python succeeds and would hide a non-canonical string, so the grammar check comes first. Do not use `float`, `Number`, or `parseFloat`.

Postgres `BIGINT` is a signed 64-bit integer. `MAX_AMOUNT` fits in it. The `CHECK` constraint is what rejects zero, negatives, and values above the cap; the column type alone does not. Do not use `DOUBLE PRECISION`, `REAL`, or `NUMERIC` for amounts.

Input amounts are not fields in the transaction body. They are the amounts of the outputs being spent. Existence of those outputs is transaction and block validation ([SCRUM-15](https://stevenkeith85.atlassian.net/browse/SCRUM-15), [SCRUM-16](https://stevenkeith85.atlassian.net/browse/SCRUM-16)). This ADR only fixes the numeric rule those checks apply.

## Consequences

- One integer is one amount. The value that is signed, the value that is stored, and the value that is displayed are the same integer.
- The `u64` width is wider than the legal range on purpose. Raising the cap later, if the client no longer uses JavaScript `Number`, does not require a new field width. It does require a new decision, and values above today's cap stay invalid until that decision.
- Because each output and the output total are both capped at `MAX_AMOUNT`, a JavaScript `Number` can hold an amount and a transaction total without rounding. The client still parses API strings itself; it does not read them through a JSON number.
- A structural decoder may return a `u64` above `MAX_AMOUNT` so the error can name the bound. Acceptance, persistence, and relay happen only after `check_amount` and the sum checks succeed.
- The per-column `CHECK` does not see the sum of a transaction's outputs. The node enforces the sum before insert. The column check is still required so a bad write that skips the node fails closed.
- SCRUM-15's cases "negative amount" and "overflowing amount" are this bound: reject `amount < 1`, reject `amount > MAX_AMOUNT`, reject an output sum or a resolved input sum above `MAX_AMOUNT`.
- Auditors recompute the same totals the hash covers, in integers, with no rounding step.

### Test vectors

[vectors/serialisation.json](vectors/serialisation.json), generated by [vectors/generate.py](vectors/generate.py), pins the bound with two transactions:

- `min_amount`: a single output of amount `1`.
- `max_amount`: a single output of amount `9007199254740991`.

The file also carries `sample` and `normal`, whose amounts sit strictly inside the range. Amounts in that JSON document are JSON integers because the fixture format in SCRUM-14 asked for integers and every value is inside the safe range. Node request and response bodies still use decimal strings. The generator refuses a bool, a float, zero, or an amount above `MAX_AMOUNT`, and it refuses an output sum above `MAX_AMOUNT`.

### Open points

- Coinbase reward sizing is [SCRUM-16](https://stevenkeith85.atlassian.net/browse/SCRUM-16). Whatever reward it defines, the output amount and the output sum still have to satisfy this ADR.
- `AGENTS.md` will link to this ADR after [SCRUM-13](https://stevenkeith85.atlassian.net/browse/SCRUM-13) merges. The guide references this file and does not copy the bound, the `CHECK` clause, or the bool rule.
