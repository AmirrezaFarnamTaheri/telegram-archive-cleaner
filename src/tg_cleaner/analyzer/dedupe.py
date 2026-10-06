"""Multi-engine deduplication analyzer.

Detects exact text, fuzzy near-duplicates, exact media, and Same Media / Different Captions.
Part of the Application (Use Case) Layer.
"""

from __future__ import annotations

import difflib
import re
import uuid
from typing import Any

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.hashing import token_sort_ratio
from tg_cleaner.core.models import (
    AnalysisFlag,
    DuplicateGroup,
    DuplicateGroupType,
    FlagType,
    MessageRecord,
    RetentionPreset,
)

# Constants for detection tuning
MIN_TEXT_LENGTH_FOR_FUZZY = 30
FUZZY_RATIO_THRESHOLD = 85.0
DHASH_MAX_HAMMING_DISTANCE = 3
UPDATE_MARKERS = re.compile(
    r"\b(update|updated|reschedule|rescheduled|correction|edit|new link|fixed)\b",
    re.IGNORECASE,
)


class DeduplicationEngine:
    """Orchestrates duplicate detection across text, media, and forwarding channels."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def find_duplicates(
        self, chat_id: int, preset: RetentionPreset = RetentionPreset.KEEP_NEWEST
    ) -> list[DuplicateGroup]:
        """Audit messages in a chat for all classes of duplicate content."""
        self.db.clear_flags_for_chat(chat_id)
        messages = self.db.get_messages(chat_id)
        if not messages:
            return []

        # Track already grouped message IDs to prevent overlapping classifications
        grouped_ids: set[int] = set()
        duplicate_groups: list[DuplicateGroup] = []
        flags: list[AnalysisFlag] = []

        # 1. Media Deduplication (Exact Media & Same Media / Different Captions)
        media_groups = self._cluster_media_messages(messages, grouped_ids)
        for group, group_flags in media_groups:
            self._apply_retention_policy(group, group_flags, preset)
            duplicate_groups.append(group)
            flags.extend(group_flags)

        # 2. Exact Text Deduplication
        text_groups = self._cluster_exact_text_messages(messages, grouped_ids)
        for group, group_flags in text_groups:
            self._apply_retention_policy(group, group_flags, preset)
            duplicate_groups.append(group)
            flags.extend(group_flags)

        # 3. Fuzzy Text Deduplication
        fuzzy_groups = self._cluster_fuzzy_text_messages(messages, grouped_ids)
        for group, group_flags in fuzzy_groups:
            self._apply_retention_policy(group, group_flags, preset)
            duplicate_groups.append(group)
            flags.extend(group_flags)

        # Persist groups and flags to SQLite staging
        for group in duplicate_groups:
            self.db.upsert_duplicate_group(group)
        self.db.upsert_flags(flags)

        return duplicate_groups

    def detect_duplicates_in_chat(
        self, chat_id: int, preset: RetentionPreset = RetentionPreset.KEEP_NEWEST
    ) -> list[DuplicateGroup]:
        """Alias for find_duplicates."""
        return self.find_duplicates(chat_id, preset=preset)

    def apply_preset(self, group: DuplicateGroup, preset: RetentionPreset) -> None:
        """Update retention preset for an existing duplicate group and refresh flags."""
        messages = self.db.get_messages_by_ids(group.chat_id, group.message_ids)
        group.recommended_preset = preset

        flags = self._resolve_flags_for_group(group, messages, preset)
        group.primary_message_id = self._pick_primary_message_id(messages, preset)

        self.db.upsert_duplicate_group(group)
        self.db.update_flags_for_group(group.id, flags)

    def _cluster_media_messages(
        self, messages: list[MessageRecord], seen_ids: set[int]
    ) -> list[tuple[DuplicateGroup, list[AnalysisFlag]]]:
        """Group messages by shared media identifiers, dimensions, or perceptual hashes."""
        clusters: list[tuple[DuplicateGroup, list[AnalysisFlag]]] = []
        media_map: dict[str, list[MessageRecord]] = {}

        for msg in messages:
            if msg.id in seen_ids or not msg.media_type:
                continue

            # Key by Telegram media_id or attribute fingerprint
            key = None
            if msg.media_id:
                key = f"id:{msg.media_type}:{msg.media_id}"
            elif msg.file_size and msg.mime_type:
                key = f"tuple:{msg.media_type}:{msg.file_size}:{msg.mime_type}:{msg.duration}"

            if key:
                media_map.setdefault(key, []).append(msg)

        for key, group_msgs in media_map.items():
            if len(group_msgs) < 2:
                continue

            msg_ids = [m.id for m in group_msgs]
            seen_ids.update(msg_ids)

            # Determine whether captions are identical or divergent
            first_hash = group_msgs[0].text_hash
            is_same_caption = all(m.text_hash == first_hash for m in group_msgs)

            group_type = (
                DuplicateGroupType.EXACT_MEDIA
                if is_same_caption
                else DuplicateGroupType.SAME_MEDIA_DIFF_CAPTION
            )
            diff_summary = self._compute_caption_diff_summary(group_msgs)
            group_id = f"group-media-{uuid.uuid4().hex[:8]}"

            group = DuplicateGroup(
                id=group_id,
                chat_id=group_msgs[0].chat_id,
                group_type=group_type,
                message_ids=msg_ids,
                diff_summary=diff_summary,
            )
            flag_type = (
                FlagType.DUPLICATE_EXACT_MEDIA
                if is_same_caption
                else FlagType.DUPLICATE_SAME_MEDIA_DIFF_CAPTION
            )
            flags = [
                AnalysisFlag(
                    message_id=m.id,
                    chat_id=m.chat_id,
                    flag_type=flag_type,
                    group_id=group_id,
                    confidence=1.0,
                    details={"matched_by": key},
                )
                for m in group_msgs
            ]
            clusters.append((group, flags))

        return clusters

    def _cluster_exact_text_messages(
        self, messages: list[MessageRecord], seen_ids: set[int]
    ) -> list[tuple[DuplicateGroup, list[AnalysisFlag]]]:
        """Group messages by identical text hash."""
        clusters: list[tuple[DuplicateGroup, list[AnalysisFlag]]] = []
        text_map: dict[str, list[MessageRecord]] = {}

        for msg in messages:
            if msg.id in seen_ids or not msg.text_hash or len(msg.text.strip()) < 5:
                continue
            text_map.setdefault(msg.text_hash, []).append(msg)

        for group_msgs in text_map.values():
            if len(group_msgs) < 2:
                continue

            msg_ids = [m.id for m in group_msgs]
            seen_ids.update(msg_ids)

            group_id = f"group-text-{uuid.uuid4().hex[:8]}"
            group = DuplicateGroup(
                id=group_id,
                chat_id=group_msgs[0].chat_id,
                group_type=DuplicateGroupType.EXACT_TEXT,
                message_ids=msg_ids,
                diff_summary={"reason": "Identical normalized text"},
            )
            flags = [
                AnalysisFlag(
                    message_id=m.id,
                    chat_id=m.chat_id,
                    flag_type=FlagType.DUPLICATE_EXACT_TEXT,
                    group_id=group_id,
                    confidence=1.0,
                )
                for m in group_msgs
            ]
            clusters.append((group, flags))

        return clusters

    def _cluster_fuzzy_text_messages(
        self, messages: list[MessageRecord], seen_ids: set[int]
    ) -> list[tuple[DuplicateGroup, list[AnalysisFlag]]]:
        """Find near-duplicate messages using token sort similarity."""
        clusters: list[tuple[DuplicateGroup, list[AnalysisFlag]]] = []
        candidates = [
            m for m in messages if m.id not in seen_ids and len(m.text) >= MIN_TEXT_LENGTH_FOR_FUZZY
        ]

        matched_in_pass: set[int] = set()
        for i, msg_a in enumerate(candidates):
            if msg_a.id in matched_in_pass:
                continue

            matches = [msg_a]
            for j in range(i + 1, len(candidates)):
                msg_b = candidates[j]
                if msg_b.id in matched_in_pass:
                    continue

                score = token_sort_ratio(msg_a.text, msg_b.text)
                if score >= FUZZY_RATIO_THRESHOLD:
                    matches.append(msg_b)
                    matched_in_pass.add(msg_b.id)

            if len(matches) > 1:
                matched_in_pass.add(msg_a.id)
                msg_ids = [m.id for m in matches]
                seen_ids.update(msg_ids)

                group_id = f"group-fuzzy-{uuid.uuid4().hex[:8]}"
                group = DuplicateGroup(
                    id=group_id,
                    chat_id=msg_a.chat_id,
                    group_type=DuplicateGroupType.FUZZY_TEXT,
                    message_ids=msg_ids,
                    diff_summary={"matched_pairs": len(matches)},
                )
                flags = [
                    AnalysisFlag(
                        message_id=m.id,
                        chat_id=m.chat_id,
                        flag_type=FlagType.DUPLICATE_FUZZY_TEXT,
                        group_id=group_id,
                        confidence=0.9,
                    )
                    for m in matches
                ]
                clusters.append((group, flags))

        return clusters

    def _compute_caption_diff_summary(self, messages: list[MessageRecord]) -> dict[str, Any]:
        """Generate human-readable difference metrics across captions."""
        lengths = [len(m.text) for m in messages]
        has_update_marker = any(bool(UPDATE_MARKERS.search(m.text)) for m in messages)

        # Word diff between first and last message
        words_first = messages[0].text.split()
        words_last = messages[-1].text.split()
        matcher = difflib.SequenceMatcher(None, words_first, words_last)

        return {
            "min_length": min(lengths),
            "max_length": max(lengths),
            "length_delta": max(lengths) - min(lengths),
            "has_update_marker": has_update_marker,
            "similarity_ratio": round(matcher.ratio() * 100, 1),
        }

    def _pick_primary_message_id(
        self, messages: list[MessageRecord], preset: RetentionPreset
    ) -> int | None:
        """Identify which message should be kept according to active preset."""
        if not messages or preset == RetentionPreset.WHITELIST_ALL:
            return None

        if preset == RetentionPreset.KEEP_NEWEST:
            return max(messages, key=lambda m: m.date).id
        elif preset == RetentionPreset.KEEP_OLDEST:
            return min(messages, key=lambda m: m.date).id
        elif preset == RetentionPreset.KEEP_LONGEST:
            return max(messages, key=lambda m: (len(m.text), m.date)).id
        return max(messages, key=lambda m: m.date).id

    def _resolve_flags_for_group(
        self,
        group: DuplicateGroup,
        messages: list[MessageRecord],
        preset: RetentionPreset,
    ) -> list[AnalysisFlag]:
        """Determine deletion candidacy for each message in group."""
        primary_id = self._pick_primary_message_id(messages, preset)
        flags: list[AnalysisFlag] = []

        flag_type_map = {
            DuplicateGroupType.EXACT_TEXT: FlagType.DUPLICATE_EXACT_TEXT,
            DuplicateGroupType.EXACT_MEDIA: FlagType.DUPLICATE_EXACT_MEDIA,
            DuplicateGroupType.SAME_MEDIA_DIFF_CAPTION: FlagType.DUPLICATE_SAME_MEDIA_DIFF_CAPTION,
            DuplicateGroupType.FUZZY_TEXT: FlagType.DUPLICATE_FUZZY_TEXT,
            DuplicateGroupType.FORWARD_CHAIN: FlagType.DUPLICATE_FORWARD,
        }
        flag_type = flag_type_map.get(group.group_type, FlagType.DUPLICATE_EXACT_TEXT)

        for m in messages:
            # If WHITELIST_ALL, none are candidates. Otherwise, all non-primary are candidates.
            is_candidate = (preset != RetentionPreset.WHITELIST_ALL) and (m.id != primary_id)
            flags.append(
                AnalysisFlag(
                    message_id=m.id,
                    chat_id=m.chat_id,
                    flag_type=flag_type,
                    group_id=group.id,
                    is_candidate_for_deletion=is_candidate,
                    confidence=1.0,
                    details={"preset": preset.value, "is_keeper": m.id == primary_id},
                )
            )
        return flags

    def _apply_retention_policy(
        self,
        group: DuplicateGroup,
        flags: list[AnalysisFlag],
        preset: RetentionPreset,
    ) -> None:
        """Apply preset to newly formed group."""
        group.recommended_preset = preset
        messages = self.db.get_messages_by_ids(group.chat_id, group.message_ids)
        group.primary_message_id = self._pick_primary_message_id(messages, preset)

        # Update flag candidate markers in-place
        for flag in flags:
            flag.is_candidate_for_deletion = (
                preset != RetentionPreset.WHITELIST_ALL
                and flag.message_id != group.primary_message_id
            )
            flag.details["is_keeper"] = flag.message_id == group.primary_message_id

    def apply_retention_preset(
        self, group: DuplicateGroup, preset: RetentionPreset
    ) -> list[AnalysisFlag]:
        """Apply a retention preset to a group, update database, and return new flags."""
        messages = self.db.get_messages_by_ids(group.chat_id, group.message_ids)
        group.recommended_preset = preset
        group.primary_message_id = self._pick_primary_message_id(messages, preset)
        self.db.upsert_duplicate_group(group)

        flags = self._resolve_flags_for_group(group, messages, preset)
        self.db.update_flags_for_group(group.id, flags)
        return flags
