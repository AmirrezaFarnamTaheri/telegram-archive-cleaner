"""Unit tests for perceptual image hashing and text normalization."""

import io

from PIL import Image

from tg_cleaner.core.hashing import (
    compute_dhash,
    compute_text_hash,
    hamming_distance,
    normalize_text,
    token_sort_ratio,
)


def _create_synthetic_image(color: str, size: tuple[int, int] = (100, 100)) -> bytes:
    """Helper creating raw image bytes for testing."""
    image = Image.new("RGB", size, color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_normalize_text_strips_unnecessary_characters():
    # Arrange
    raw_input = "  \u200bHello\tWORLD!! \n\n🎉 123  "
    expected = "hello world!! 123"

    # Act
    result = normalize_text(raw_input)

    # Assert
    assert result == expected


def test_normalize_text_unicode_nfkc():
    # Arrange
    raw_input = "ﬁle"  # ligature fi
    expected = "file"

    # Act
    result = normalize_text(raw_input)

    # Assert
    assert result == expected


def test_compute_text_hash_consistent_for_equivalent_strings():
    # Arrange
    text_a = "Important Update: The meeting is at 5 PM."
    text_b = "  important   update:  the meeting is at 5 pm.  "

    # Act
    hash_a = compute_text_hash(text_a)
    hash_b = compute_text_hash(text_b)

    # Assert
    assert hash_a is not None
    assert len(hash_a) == 64  # SHA-256 hex length
    assert hash_a == hash_b


def test_compute_dhash_produces_consistent_hex_string():
    # Arrange
    image_bytes = _create_synthetic_image("blue", (150, 150))

    # Act
    hash_val = compute_dhash(image_bytes)

    # Assert
    assert isinstance(hash_val, str)
    assert len(hash_val) == 16  # 64 bits = 16 hex chars


def test_hamming_distance_identical_and_divergent():
    # Arrange
    hash_a = "0000ffff0000ffff"
    hash_b = "0000ffff0000ffff"
    hash_c = "ffff0000ffff0000"

    # Act & Assert
    assert hamming_distance(hash_a, hash_b) == 0
    assert hamming_distance(hash_a, hash_c) == 64


def test_perceptual_hash_identifies_resized_same_image():
    # Arrange: Same red image at 2 different dimensions
    image_small = _create_synthetic_image("red", (80, 80))
    image_large = _create_synthetic_image("red", (800, 800))

    # Act
    hash_small = compute_dhash(image_small)
    hash_large = compute_dhash(image_large)
    dist = hamming_distance(hash_small, hash_large)

    # Assert: Should match perfectly or within 1 bit due to compression
    assert dist <= 2


def test_token_sort_ratio_identical_with_reordered_words():
    # Arrange
    s1 = "Webinar on Python and FastAPI"
    s2 = "FastAPI and Python on Webinar"

    # Act
    score = token_sort_ratio(s1, s2)

    # Assert
    assert score == 100.0


def test_token_sort_ratio_detects_dissimilarity():
    # Arrange
    s1 = "Completely unique message about finance"
    s2 = "Unrelated weather forecast for tomorrow"

    # Act
    score = token_sort_ratio(s1, s2)

    # Assert
    assert score < 50.0
