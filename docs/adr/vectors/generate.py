"""Regenerate the canonical-serialisation test vectors.

Run from anywhere:

    python docs/adr/vectors/generate.py

The only dependency outside the standard library is ``cryptography``
(``Ed25519PrivateKey.from_private_bytes``). Ed25519 signing follows
RFC 8032 and is deterministic, so the signatures in the output are
fixed values.

The script writes ``serialisation.json`` next to itself. Object keys are
sorted, the indent is two spaces, and the file ends with one trailing
newline. Running it twice produces identical bytes. Do not edit the JSON
by hand; change this script and run it again.

The integers below are chosen so a little-endian encoder cannot collide
with the big-endian bytes: ``2**32 + 1`` is the u64
``00 00 00 01 00 00 00 01``, and ``2**16 + 3`` is the u32 ``00 01 00 03``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

WARNING = "TEST ONLY - never use these keys for real value"

TX_TAG = b"LedgerLab/tx/v1\x00"
BLOCK_TAG = b"LedgerLab/block/v1\x00"
MAX_AMOUNT = 2**53 - 1
VERSION = 1
INPUT_COUNT_MAX = 1000
OUTPUT_COUNT_MAX = 1000

# 32-byte seeds. Key A is 0x00..0x1f. Key B is 0x20..0x3f.
SEEDS: dict[str, bytes] = {
    "A": bytes(range(0, 32)),
    "B": bytes(range(32, 64)),
}

OUTPUT_PATH = Path(__file__).resolve().parent / "serialisation.json"


def require_int(name: str, value: object) -> int:
    """Reject bool. ``bool`` is a subclass of ``int``, so isinstance is wrong."""
    if type(value) is bool or type(value) is not int:
        raise TypeError(f"{name} must be int, not {type(value).__name__}")
    return value


def u32(value: object) -> bytes:
    number = require_int("u32", value)
    if not 0 <= number <= 0xFFFFFFFF:
        raise ValueError(f"u32 out of range: {number}")
    return number.to_bytes(4, "big", signed=False)


def u64(value: object) -> bytes:
    number = require_int("u64", value)
    if not 0 <= number <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError(f"u64 out of range: {number}")
    return number.to_bytes(8, "big", signed=False)


def raw32(name: str, value: bytes) -> bytes:
    if not isinstance(value, (bytes, bytearray)) or len(value) != 32:
        raise ValueError(f"{name} must be 32 bytes")
    return bytes(value)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def load_key(seed: bytes) -> tuple[Ed25519PrivateKey, bytes]:
    seed = raw32("seed", seed)
    private = Ed25519PrivateKey.from_private_bytes(seed)
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    if len(public) != 32:
        raise RuntimeError("Ed25519 public key was not 32 bytes")
    return private, public


def key_record(key_id: str, seed: bytes, public: bytes) -> dict[str, str]:
    return {
        "key_id": key_id,
        "public_key_hex": public.hex(),
        "seed_hex": seed.hex(),
        "warning": WARNING,
    }


def encode_tx_body(
    version: int,
    inputs: list[tuple[bytes, int]],
    outputs: list[tuple[int, bytes]],
) -> bytes:
    """Unsigned transaction body. Signatures are not included."""
    if not 0 <= len(inputs) <= INPUT_COUNT_MAX:
        raise ValueError("input_count outside 0..=1000")
    if not 1 <= len(outputs) <= OUTPUT_COUNT_MAX:
        raise ValueError("output_count outside 1..=1000")

    parts = [u32(version), u32(len(inputs))]
    for prev_tx_id, output_index in inputs:
        parts.append(raw32("prev_tx_id", prev_tx_id))
        parts.append(u32(output_index))
    parts.append(u32(len(outputs)))
    amounts: list[int] = []
    for amount, recipient in outputs:
        amount = require_int("amount", amount)
        if not 1 <= amount <= MAX_AMOUNT:
            raise ValueError(f"amount out of range: {amount}")
        amounts.append(amount)
        parts.append(u64(amount))
        parts.append(raw32("recipient_public_key", recipient))
    if sum(amounts) > MAX_AMOUNT:
        raise ValueError("output sum exceeds MAX_AMOUNT")
    return b"".join(parts)


def encode_block_header(
    version: int,
    height: int,
    prev_block_hash: bytes,
    tx_root: bytes,
    timestamp_ms: int,
    proposer_public_key: bytes,
) -> bytes:
    return b"".join(
        [
            u32(version),
            u64(height),
            raw32("prev_block_hash", prev_block_hash),
            raw32("tx_root", tx_root),
            u64(timestamp_ms),
            raw32("proposer_public_key", proposer_public_key),
        ]
    )


def make_tx(
    name: str,
    description: str,
    inputs: list[tuple[bytes, int, str]],
    outputs: list[tuple[int, str]],
    keys: dict[str, tuple[Ed25519PrivateKey, bytes]],
) -> dict:
    encoded_inputs = [(prev, index) for prev, index, _signer in inputs]
    encoded_outputs = [(amount, keys[recipient][1]) for amount, recipient in outputs]
    body = encode_tx_body(VERSION, encoded_inputs, encoded_outputs)
    preimage = TX_TAG + body
    tx_id = sha256(preimage)

    signatures: list[str] = []
    signing_keys: list[dict[str, str]] = []
    input_fields: list[dict[str, object]] = []
    for prev_tx_id, output_index, signer_id in inputs:
        private, public = keys[signer_id]
        signature = private.sign(preimage)
        if len(signature) != 64:
            raise RuntimeError("Ed25519 signature was not 64 bytes")
        private.public_key().verify(signature, preimage)
        signatures.append(signature.hex())
        signing_keys.append(key_record(signer_id, SEEDS[signer_id], public))
        input_fields.append(
            {
                "output_index": output_index,
                "prev_tx_id_hex": prev_tx_id.hex(),
            }
        )

    output_fields = [
        {
            "amount": amount,
            "recipient_public_key_hex": keys[recipient][1].hex(),
        }
        for amount, recipient in outputs
    ]
    return {
        "body_hex": body.hex(),
        "description": description,
        "fields": {
            "inputs": input_fields,
            "outputs": output_fields,
            "version": VERSION,
        },
        "name": name,
        "signatures_hex": signatures,
        "signing_keys": signing_keys,
        "signing_preimage_hex": preimage.hex(),
        "tx_id_hex": tx_id.hex(),
        "tx_id_preimage_hex": preimage.hex(),
    }


def make_block(
    transactions: list[dict],
    keys: dict[str, tuple[Ed25519PrivateKey, bytes]],
) -> dict:
    """Header over ``transactions`` in list order. Proposer is test key A."""
    tx_ids = [bytes.fromhex(tx["tx_id_hex"]) for tx in transactions]
    for tx_id in tx_ids:
        raw32("tx_id", tx_id)
    tx_root = sha256(b"".join(tx_ids))
    proposer_id = "A"
    _private, proposer_public = keys[proposer_id]
    height = 42
    timestamp_ms = 1_735_689_600_000  # 2025-01-01T00:00:00.000Z
    prev_block_hash = bytes(32)
    header = encode_block_header(
        VERSION,
        height,
        prev_block_hash,
        tx_root,
        timestamp_ms,
        proposer_public,
    )
    preimage = BLOCK_TAG + header
    block_hash = sha256(preimage)
    signature = keys[proposer_id][0].sign(preimage)
    if len(signature) != 64:
        raise RuntimeError("proposer signature was not 64 bytes")
    keys[proposer_id][0].public_key().verify(signature, preimage)
    return {
        "block_hash_hex": block_hash.hex(),
        "description": (
            "Header fixture. tx_root commits to the transaction ids in "
            "tx_names order. The all-zero prev_block_hash pins the genesis "
            "previous-hash bytes. Height 42 keeps the u64 endianness visible. "
            "This fixture is not a consensus-valid block: coinbase rules are "
            "SCRUM-16 and proof-of-authority policy is SCRUM-19."
        ),
        "fields": {
            "height": height,
            "prev_block_hash_hex": prev_block_hash.hex(),
            "proposer_public_key_hex": proposer_public.hex(),
            "timestamp_ms": timestamp_ms,
            "tx_root_hex": tx_root.hex(),
            "version": VERSION,
        },
        "header_hex": header.hex(),
        "preimage_hex": preimage.hex(),
        "proposer_key": key_record(proposer_id, SEEDS[proposer_id], proposer_public),
        "proposer_signature_hex": signature.hex(),
        "tx_ids_hex": [tx_id.hex() for tx_id in tx_ids],
        "tx_names": [tx["name"] for tx in transactions],
    }


def document_for(keys: dict[str, tuple[Ed25519PrivateKey, bytes]]) -> dict:
    public_only = {key_id: pair[1] for key_id, pair in keys.items()}
    # Repeated prev-ids are synthetic. They are not ids of the vectors below.
    sample = make_tx(
        "sample",
        "One input, one output, amount 1000. Signed by test key A.",
        inputs=[(bytes([0x11]) * 32, 0, "A")],
        outputs=[(1000, "B")],
        keys=keys,
    )
    normal = make_tx(
        "normal",
        "Two inputs and two outputs. Input 0 is signed by A, input 1 by B. "
        "The second output index is 2**16+3 and the second amount is 2**32+1.",
        inputs=[
            (bytes([0x21]) * 32, 0, "A"),
            (bytes([0x22]) * 32, 2**16 + 3, "B"),
        ],
        outputs=[
            (1000, "A"),
            (2**32 + 1, "B"),
        ],
        keys=keys,
    )
    min_amount = make_tx(
        "min_amount",
        "Single output of amount 1, the minimum legal amount. Signed by A.",
        inputs=[(bytes([0x31]) * 32, 0, "A")],
        outputs=[(1, "B")],
        keys=keys,
    )
    max_amount = make_tx(
        "max_amount",
        "Single output of amount 2**53-1, the maximum legal amount. Signed by B.",
        inputs=[(bytes([0x32]) * 32, 0, "B")],
        outputs=[(MAX_AMOUNT, "A")],
        keys=keys,
    )
    transactions = [sample, normal, min_amount, max_amount]
    catalogue = [
        key_record(key_id, SEEDS[key_id], public_only[key_id])
        for key_id in ("A", "B")
    ]
    return {
        "block": make_block(transactions, keys),
        "constants": {
            "block_header_field_order": [
                "version",
                "height",
                "prev_block_hash",
                "tx_root",
                "timestamp_ms",
                "proposer_public_key",
            ],
            "block_preimage": "BLOCK_TAG || header",
            "block_tag_ascii": "LedgerLab/block/v1",
            "block_tag_hex": BLOCK_TAG.hex(),
            "endianness": "unsigned-big-endian",
            "hash": "SHA-256",
            "input_count_max": INPUT_COUNT_MAX,
            "input_count_min": 0,
            "input_field_order": ["prev_tx_id", "output_index"],
            "max_amount": MAX_AMOUNT,
            "output_count_max": OUTPUT_COUNT_MAX,
            "output_count_min": 1,
            "output_field_order": ["amount", "recipient_public_key"],
            "signature": "Ed25519-RFC8032",
            "tx_body_field_order": [
                "version",
                "input_count",
                "inputs",
                "output_count",
                "outputs",
            ],
            "tx_id_preimage": "TX_TAG || tx_body",
            "tx_root": (
                "SHA-256 of the raw 32-byte transaction ids concatenated in block order"
            ),
            "tx_signing_preimage": "TX_TAG || tx_body",
            "tx_tag_ascii": "LedgerLab/tx/v1",
            "tx_tag_hex": TX_TAG.hex(),
            "version": VERSION,
        },
        "keys": catalogue,
        "notes": (
            "TEST ONLY keys. signing_preimage_hex and tx_id_preimage_hex name the "
            "two transaction preimages; both are TX_TAG || tx_body, signatures "
            "excluded. signatures_hex[i] was produced by signing_keys[i] over that "
            "preimage and aligns with fields.inputs[i]. signer identity is not a "
            "serialised field. The block preimage is BLOCK_TAG || header; the "
            "proposer signature is excluded from the block hash. tx_root hashes "
            "raw transaction-id bytes, not their hex text. Amounts in this file "
            "are JSON integers because every fixture value is inside the safe "
            "range; the node JSON API still sends decimal strings (ADR 0002)."
        ),
        "transactions": transactions,
        "warning": WARNING,
    }


def dump(data: dict) -> str:
    text = json.dumps(
        data,
        allow_nan=False,
        ensure_ascii=True,
        indent=2,
        separators=(",", ": "),
        sort_keys=True,
    )
    if not text.endswith("\n"):
        text += "\n"
    return text


def main() -> None:
    keys = {key_id: load_key(seed) for key_id, seed in SEEDS.items()}
    payload = document_for(keys)
    text = dump(payload)
    if dump(json.loads(text)) != text:
        raise RuntimeError("JSON encoding was not stable")
    OUTPUT_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT_PATH}")
    for tx in payload["transactions"]:
        print(f"{tx['name']} {tx['tx_id_hex']}")
    print(f"block {payload['block']['block_hash_hex']}")


if __name__ == "__main__":
    main()
