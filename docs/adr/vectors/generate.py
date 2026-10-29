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

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

WARNING = "TEST ONLY - never use these keys for real value"

TX_TAG = b"LedgerLab/tx/v1\x00"
BLOCK_TAG = b"LedgerLab/block/v1\x00"
MAX_AMOUNT = 2**53 - 1
VERSION = 1
INPUT_COUNT_MAX = 1000
OUTPUT_COUNT_MAX = 1000
# Test-chain genesis difficulty. Legal range is 0..255. The search below
# is deterministic: each vector uses the smallest nonce from 0 that matches
# its leading-zero condition.
DIFFICULTY_BITS = 16
HEADER_PREFIX_LEN = 120
HEADER_LEN = 128

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


def pow_target(difficulty_bits: int) -> int:
    """Exclusive upper bound on the block hash as a big-endian integer."""
    bits = require_int("difficulty_bits", difficulty_bits)
    if not 0 <= bits <= 255:
        raise ValueError("difficulty_bits outside 0..255")
    return 1 << (256 - bits)


def leading_zero_bits(digest: bytes) -> int:
    if len(digest) != 32:
        raise ValueError("digest must be 32 bytes")
    value = int.from_bytes(digest, "big")
    if value == 0:
        return 256
    return 256 - value.bit_length()


def encode_block_header(
    version: int,
    height: int,
    prev_block_hash: bytes,
    tx_root: bytes,
    timestamp_ms: int,
    proposer_public_key: bytes,
    difficulty_bits: int,
    nonce: int,
) -> bytes:
    """128-byte header. The nonce is part of the header that is hashed and signed."""
    bits = require_int("difficulty_bits", difficulty_bits)
    if not 0 <= bits <= 255:
        raise ValueError("difficulty_bits outside 0..255")
    header = b"".join(
        [
            u32(version),
            u64(height),
            raw32("prev_block_hash", prev_block_hash),
            raw32("tx_root", tx_root),
            u64(timestamp_ms),
            raw32("proposer_public_key", proposer_public_key),
            u32(bits),
            u64(nonce),
        ]
    )
    if len(header) != HEADER_LEN:
        raise RuntimeError(f"header length {len(header)}")
    return header


def mine_nonces(prefix: bytes, difficulty_bits: int) -> dict[str, tuple[int, bytes, bytes, int]]:
    """Find three nonces, each the smallest from 0 for its condition.

    ``valid`` meets the target (hash < 2**(256 - difficulty_bits)).
    ``exact`` has exactly ``difficulty_bits`` leading zero bits, which passes.
    ``below`` has exactly ``difficulty_bits - 1`` leading zero bits, which fails.
    """
    if len(prefix) != HEADER_PREFIX_LEN:
        raise ValueError("header prefix must be 120 bytes")
    target = pow_target(difficulty_bits)
    found: dict[str, tuple[int, bytes, bytes, int]] = {}
    nonce = 0
    while len(found) < 3:
        header = prefix + u64(nonce)
        digest = sha256(BLOCK_TAG + header)
        value = int.from_bytes(digest, "big")
        zeros = 256 if value == 0 else 256 - value.bit_length()
        if "valid" not in found and value < target:
            found["valid"] = (nonce, header, digest, zeros)
        if "exact" not in found and zeros == difficulty_bits:
            found["exact"] = (nonce, header, digest, zeros)
        if "below" not in found and zeros == difficulty_bits - 1:
            found["below"] = (nonce, header, digest, zeros)
        nonce += 1
        if nonce > 5_000_000:
            raise RuntimeError("proof-of-work search exceeded 5000000 nonces")
    exact_nonce = found["exact"][0]
    valid_nonce = found["valid"][0]
    if exact_nonce < valid_nonce:
        raise RuntimeError("exact leading-zero nonce was below the first valid nonce")
    if not int.from_bytes(found["exact"][2], "big") < target:
        raise RuntimeError("exact leading-zero hash missed the target")
    if int.from_bytes(found["below"][2], "big") < target:
        raise RuntimeError("below-target boundary hash met the target")
    return found


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


def finish_block(
    name: str,
    description: str,
    role: str,
    nonce: int,
    header: bytes,
    digest: bytes,
    zeros: int,
    meets_target: bool,
    shared: dict,
    keys: dict[str, tuple[Ed25519PrivateKey, bytes]],
) -> dict:
    """Sign the finished header. Mining has already chosen ``nonce``."""
    if header[-8:] != u64(nonce):
        raise RuntimeError("header nonce bytes do not match the mined nonce")
    preimage = BLOCK_TAG + header
    if sha256(preimage) != digest:
        raise RuntimeError("block hash does not match the mined digest")
    proposer_id = shared["proposer_id"]
    private, public = keys[proposer_id]
    signature = private.sign(preimage)
    if len(signature) != 64:
        raise RuntimeError("proposer signature was not 64 bytes")
    private.public_key().verify(signature, preimage)
    tweaked = bytearray(header)
    tweaked[-1] ^= 0x01
    try:
        private.public_key().verify(signature, BLOCK_TAG + bytes(tweaked))
    except InvalidSignature:
        pass
    else:
        raise RuntimeError("signature verified for a header with a different nonce")
    return {
        "block_hash_hex": digest.hex(),
        "description": description,
        "difficulty_bits": shared["difficulty_bits"],
        "fields": {
            "difficulty_bits": shared["difficulty_bits"],
            "height": shared["height"],
            "nonce": nonce,
            "prev_block_hash_hex": shared["prev_block_hash"].hex(),
            "proposer_public_key_hex": public.hex(),
            "timestamp_ms": shared["timestamp_ms"],
            "tx_root_hex": shared["tx_root"].hex(),
            "version": VERSION,
        },
        "header_hex": header.hex(),
        "leading_zero_bits": zeros,
        "meets_pow_target": meets_target,
        "name": name,
        "preimage_hex": preimage.hex(),
        "proposer_key": key_record(proposer_id, SEEDS[proposer_id], public),
        "proposer_signature_hex": signature.hex(),
        "role": role,
        "tx_ids_hex": [tx_id.hex() for tx_id in shared["tx_ids"]],
        "tx_names": shared["tx_names"],
    }


def make_blocks(
    transactions: list[dict],
    keys: dict[str, tuple[Ed25519PrivateKey, bytes]],
) -> dict[str, dict]:
    """Three headers over the same transactions. Only the nonce differs.

    The proposer signs ``BLOCK_TAG || header`` after the nonce is chosen.
    """
    tx_ids = [bytes.fromhex(tx["tx_id_hex"]) for tx in transactions]
    for tx_id in tx_ids:
        raw32("tx_id", tx_id)
    tx_root = sha256(b"".join(tx_ids))
    proposer_id = "A"
    _private, proposer_public = keys[proposer_id]
    height = 42
    timestamp_ms = 1_735_689_600_000  # 2025-01-01T00:00:00.000Z
    prev_block_hash = bytes(32)
    # Nonce is the last 8 bytes. Drop that placeholder so the search can append
    # each candidate without rebuilding the rest of the header.
    prefix = encode_block_header(
        VERSION,
        height,
        prev_block_hash,
        tx_root,
        timestamp_ms,
        proposer_public,
        DIFFICULTY_BITS,
        0,
    )[:HEADER_PREFIX_LEN]
    mined = mine_nonces(prefix, DIFFICULTY_BITS)
    shared = {
        "difficulty_bits": DIFFICULTY_BITS,
        "height": height,
        "prev_block_hash": prev_block_hash,
        "proposer_id": proposer_id,
        "timestamp_ms": timestamp_ms,
        "tx_ids": tx_ids,
        "tx_names": [tx["name"] for tx in transactions],
        "tx_root": tx_root,
    }
    valid_nonce, valid_header, valid_digest, valid_zeros = mined["valid"]
    exact_nonce, exact_header, exact_digest, exact_zeros = mined["exact"]
    below_nonce, below_header, below_digest, below_zeros = mined["below"]
    common = (
        "Same transaction ids, height 42, timestamp_ms 1735689600000, "
        "all-zero prev_block_hash, proposer test key A, difficulty_bits 16. "
        "The signature is over BLOCK_TAG || header after that nonce is final, "
        "and it is not part of the hash. Coinbase rules remain SCRUM-16, so "
        "this is a header fixture, not a consensus-valid chain block."
    )
    return {
        "block": finish_block(
            "block",
            "Smallest nonce from 0 whose block hash, as a big-endian integer, "
            "is strictly less than 2**(256 - 16). " + common,
            "minimal_valid_nonce",
            valid_nonce,
            valid_header,
            valid_digest,
            valid_zeros,
            True,
            shared,
            keys,
        ),
        "block_boundary_pass": finish_block(
            "block_boundary_pass",
            "Smallest nonce from 0 whose block hash has exactly 16 leading "
            "zero bits. That hash passes the target check. " + common,
            "exact_leading_zero_bits_pass",
            exact_nonce,
            exact_header,
            exact_digest,
            exact_zeros,
            True,
            shared,
            keys,
        ),
        "block_boundary_fail": finish_block(
            "block_boundary_fail",
            "Smallest nonce from 0 whose block hash has exactly 15 leading "
            "zero bits. That hash fails the target check. The proposer "
            "signature is valid for this header; the failure is the work. "
            + common,
            "fewer_leading_zero_bits_fail",
            below_nonce,
            below_header,
            below_digest,
            below_zeros,
            False,
            shared,
            keys,
        ),
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
    blocks = make_blocks(transactions, keys)
    return {
        "block": blocks["block"],
        "block_boundary_fail": blocks["block_boundary_fail"],
        "block_boundary_pass": blocks["block_boundary_pass"],
        "constants": {
            "block_header_field_order": [
                "version",
                "height",
                "prev_block_hash",
                "tx_root",
                "timestamp_ms",
                "proposer_public_key",
                "difficulty_bits",
                "nonce",
            ],
            "block_preimage": "BLOCK_TAG || header",
            "difficulty_bits_max": 255,
            "difficulty_bits_min": 0,
            "header_width_bytes": HEADER_LEN,
            "pow_target_rule": (
                "uint256be(block_hash) < 2**(256 - difficulty_bits)"
            ),
            "proposer_signs": "BLOCK_TAG || header after the nonce is final",
            "test_chain_difficulty_bits": DIFFICULTY_BITS,
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
            "serialised field. The block preimage is BLOCK_TAG || header, and "
            "that header includes difficulty_bits and the final nonce. The "
            "proposer signs that preimage after mining. The signature is "
            "excluded from the block hash. A test chain fixes difficulty_bits "
            "in its genesis; these block vectors use 16. tx_root hashes "
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
    for key in ("block", "block_boundary_pass", "block_boundary_fail"):
        block = payload[key]
        print(
            f"{key} hash={block['block_hash_hex']} "
            f"nonce={block['fields']['nonce']} "
            f"difficulty_bits={block['fields']['difficulty_bits']} "
            f"leading_zero_bits={block['leading_zero_bits']} "
            f"meets_pow_target={block['meets_pow_target']}"
        )


if __name__ == "__main__":
    main()
