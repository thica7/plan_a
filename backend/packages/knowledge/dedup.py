"""Near-duplicate detection for knowledge-base text chunks."""

from __future__ import annotations

import hashlib
import os
import re

_DEFAULT_THRESHOLD = 5
_HASH_BITS = 64
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def simhash(text: str) -> int:
    """Return a deterministic 64-bit SimHash for text."""
    vector = [0] * _HASH_BITS
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        token_hash = int.from_bytes(digest, "big")
        for bit in range(_HASH_BITS):
            if token_hash & (1 << bit):
                vector[bit] += 1
            else:
                vector[bit] -= 1

    fingerprint = 0
    for bit, weight in enumerate(vector):
        if weight >= 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def dedup_document(text: str, existing_hashes: list[int], threshold: int | None = None) -> bool:
    """Return True when text is a near-duplicate of any existing SimHash."""
    threshold = _dedup_threshold() if threshold is None else threshold
    candidate = simhash(text)
    return any(hamming_distance(candidate, existing) <= threshold for existing in existing_hashes)


def batch_dedup(texts: list[str], threshold: int | None = None) -> list[str]:
    """Return texts with near-duplicates removed, preserving first occurrence order."""
    threshold = _dedup_threshold() if threshold is None else threshold
    kept: list[str] = []
    hashes: list[int] = []
    for text in texts:
        if dedup_document(text, hashes, threshold):
            continue
        kept.append(text)
        hashes.append(simhash(text))
    return kept


def _tokens(text: str) -> list[str]:
    tokens = [token.casefold() for token in _TOKEN_RE.findall(text)]
    return tokens or [text.casefold()]


def _dedup_threshold() -> int:
    try:
        return int(os.getenv("KB_DEDUP_THRESHOLD", str(_DEFAULT_THRESHOLD)))
    except ValueError:
        return _DEFAULT_THRESHOLD
