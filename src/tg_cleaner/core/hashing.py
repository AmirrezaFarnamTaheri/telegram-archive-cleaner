"""Pure-function utilities for perceptual image hashing and text normalization.

Part of the Domain Layer: No network, database, or UI dependencies.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata

from PIL import Image

# Fallback-aware rapidfuzz import
try:
    from rapidfuzz import fuzz as _rf
except ImportError:
    _rf = None

# Regex patterns for text cleaning
_ZERO_WIDTH_CHARS = re.compile(r"[\u200B-\u200D\uFEFF]")
_EMOJI_PATTERN = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27ff]", flags=re.UNICODE)
_MULTI_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """Normalize text using Unicode NFKC, strip invisible characters, and collapse spaces."""
    if not text:
        return ""

    # Canonical decomposition followed by canonical composition
    normalized = unicodedata.normalize("NFKC", text)

    # Strip zero-width and invisible control characters
    normalized = _ZERO_WIDTH_CHARS.sub("", normalized)

    # Strip emojis to ensure text comparison focuses on semantic text
    normalized = _EMOJI_PATTERN.sub(" ", normalized)

    # Lowercase and collapse consecutive whitespace
    normalized = _MULTI_WHITESPACE.sub(" ", normalized.lower()).strip()
    return normalized


def compute_text_hash(text: str | None) -> str | None:
    """Compute SHA-256 hex digest of normalized text."""
    normalized = normalize_text(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_dhash(image_bytes: bytes, hash_size: int = 8) -> str | None:
    """Compute 64-bit difference hash (dHash) from image bytes using Pillow."""
    if not image_bytes:
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            # Convert to grayscale and resize to (width + 1, height)
            gray = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
            # Modern Pillow uses get_flattened_data; fallback to getdata for older versions
            if hasattr(gray, "get_flattened_data"):
                pixels = list(gray.get_flattened_data())
            else:
                pixels = list(gray.getdata())

            # Compare adjacent horizontal pixels
            diff_bits = 0
            for row in range(hash_size):
                row_offset = row * (hash_size + 1)
                for col in range(hash_size):
                    left_pixel = pixels[row_offset + col]
                    right_pixel = pixels[row_offset + col + 1]
                    diff_bits = (diff_bits << 1) | (1 if left_pixel > right_pixel else 0)

            # Return as 16-character hexadecimal string
            return f"{diff_bits:016x}"
    except Exception:
        return None


def hamming_distance(hash_hex_1: str | None, hash_hex_2: str | None) -> int:
    """Calculate number of differing bits between two hexadecimal hash strings."""
    if not hash_hex_1 or not hash_hex_2:
        return 64

    try:
        val1 = int(hash_hex_1, 16)
        val2 = int(hash_hex_2, 16)
        xor_result = val1 ^ val2
        return bin(xor_result).count("1")
    except ValueError:
        return 64


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Two-row dynamic programming Levenshtein distance."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)
    if len(s1) < len(s2):
        s1, s2 = s2, s1

    previous_row = list(range(len(s2) + 1))
    for i, char1 in enumerate(s1, start=1):
        current_row = [i]
        for j, char2 in enumerate(s2, start=1):
            cost = 0 if char1 == char2 else 1
            current_row.append(
                min(
                    previous_row[j] + 1,  # deletion
                    current_row[j - 1] + 1,  # insertion
                    previous_row[j - 1] + cost,  # substitution
                )
            )
        previous_row = current_row
    return previous_row[-1]


def token_sort_ratio(s1: str, s2: str) -> float:
    """Calculate token-sorted Levenshtein similarity in range [0.0, 100.0]."""
    if _rf is not None:
        return float(_rf.token_sort_ratio(s1, s2))

    norm1 = normalize_text(s1)
    norm2 = normalize_text(s2)
    if not norm1 and not norm2:
        return 100.0
    if not norm1 or not norm2:
        return 0.0

    sorted1 = " ".join(sorted(norm1.split()))
    sorted2 = " ".join(sorted(norm2.split()))
    if sorted1 == sorted2:
        return 100.0

    max_len = max(len(sorted1), len(sorted2))
    if max_len == 0:
        return 100.0

    distance = _levenshtein_distance(sorted1, sorted2)
    similarity = (1.0 - (distance / max_len)) * 100.0
    return max(0.0, round(similarity, 1))
