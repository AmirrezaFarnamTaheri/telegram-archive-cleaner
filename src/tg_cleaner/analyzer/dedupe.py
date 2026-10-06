"""Duplicate detection with conservative deletion eligibility.

The analyzer deliberately separates *finding similarity* from *authorizing deletion*.
Only deterministic equivalence classes (identical normalized text, or the same Telegram
media object with the same caption) are auto-eligible. Fuzzy, perceptual, forwarded,
and same-media/different-caption findings require an explicit user preset/action.
"""

from __future__ import annotations

import difflib
import re
import uuid
from collections import defaultdict
from typing import Any, Callable

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.hashing import hamming_distance, token_sort_ratio
from tg_cleaner.core.models import (
    AnalysisFlag,
    DuplicateGroup,
    DuplicateGroupType,
    FlagType,
    MessageRecord,
    RetentionPreset,
)

MIN_TEXT_LENGTH_FOR_FUZZY = 30
FUZZY_RATIO_THRESHOLD = 85.0
DHASH_MAX_HAMMING_DISTANCE = 3
UPDATE_MARKERS = re.compile(
    r"\b(update|updated|reschedule|rescheduled|correction|edit|new link|fixed)\b",
    re.IGNORECASE,
)

# These groups represent deterministic content identity rather than a similarity guess.
_AUTO_ELIGIBLE_GROUPS = {
    DuplicateGroupType.EXACT_TEXT,
    DuplicateGroupType.EXACT_MEDIA,
    DuplicateGroupType.SAME_MEDIA_DIFF_CAPTION,
}


class DeduplicationEngine:
    """Orchestrates duplicate detection across text, media, and forwarding metadata."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def find_duplicates(
        self, chat_id: int, preset: RetentionPreset = RetentionPreset.KEEP_NEWEST
    ) -> list[DuplicateGroup]:
        """Rebuild duplicate findings for active messages in a chat."""
        self.db.clear_flags_for_chat(chat_id)
        messages = self.db.get_active_messages(chat_id)
        if not messages:
            return []

        grouped_ids: set[int] = set()
        duplicate_groups: list[DuplicateGroup] = []
        flags: list[AnalysisFlag] = []

        detectors: tuple[
            Callable[
                [list[MessageRecord], set[int]],
                list[tuple[DuplicateGroup, list[AnalysisFlag]]],
            ],
            ...,
        ] = (
            self._cluster_exact_media_messages,
            self._cluster_exact_text_messages,
            self._cluster_forwarded_messages,
            self._cluster_visual_media_messages,
            self._cluster_fuzzy_text_messages,
        )

        for detector in detectors:
            for group, group_flags in detector(messages, grouped_ids):
                self._apply_retention_policy(group, group_flags, preset, explicit=False)
                duplicate_groups.append(group)
                flags.extend(group_flags)

        for group in duplicate_groups:
            self.db.upsert_duplicate_group(group)
        self.db.upsert_flags(flags)
        return duplicate_groups

    def detect_duplicates_in_chat(
        self, chat_id: int, preset: RetentionPreset = RetentionPreset.KEEP_NEWEST
    ) -> list[DuplicateGroup]:
        """Compatibility alias for :meth:`find_duplicates`."""
        return self.find_duplicates(chat_id, preset=preset)

    def apply_preset(self, group: DuplicateGroup, preset: RetentionPreset) -> None:
        """Explicitly apply a retention policy to a previously reviewed group."""
        self.apply_retention_preset(group, preset)

    @staticmethod
    def _new_group_id(kind: str) -> str:
        return f"group-{kind}-{uuid.uuid4().hex[:10]}"

    def _cluster_exact_media_messages(
        self, messages: list[MessageRecord], seen_ids: set[int]
    ) -> list[tuple[DuplicateGroup, list[AnalysisFlag]]]:
        """Group only truly identical Telegram/export media identifiers.

        File size, MIME type, duration, and dimensions are intentionally *not* an identity
        key. Different files can share all of those attributes.
        """
        clusters: list[tuple[DuplicateGroup, list[AnalysisFlag]]] = []
        media_map: dict[tuple[str, str], list[MessageRecord]] = defaultdict(list)

        for msg in messages:
            if msg.id in seen_ids or not msg.media_type or not msg.media_id:
                continue
            media_map[(msg.media_type, msg.media_id)].append(msg)

        for (media_type, media_id), group_msgs in media_map.items():
            if len(group_msgs) < 2:
                continue
            msg_ids = [m.id for m in group_msgs]
            seen_ids.update(msg_ids)

            first_hash = group_msgs[0].text_hash
            same_caption = all(m.text_hash == first_hash for m in group_msgs)
            group_type = (
                DuplicateGroupType.EXACT_MEDIA
                if same_caption
                else DuplicateGroupType.SAME_MEDIA_DIFF_CAPTION
            )
            flag_type = (
                FlagType.DUPLICATE_EXACT_MEDIA
                if same_caption
                else FlagType.DUPLICATE_SAME_MEDIA_DIFF_CAPTION
            )
            group_id = self._new_group_id("media")
            summary = self._compute_caption_diff_summary(group_msgs)
            summary.update(
                {
                    "matched_by": "media_id",
                    "media_type": media_type,
                    "requires_review": not same_caption,
                }
            )
            group = DuplicateGroup(
                id=group_id,
                chat_id=group_msgs[0].chat_id,
                group_type=group_type,
                message_ids=msg_ids,
                diff_summary=summary,
            )
            flags = [
                AnalysisFlag(
                    message_id=m.id,
                    chat_id=m.chat_id,
                    flag_type=flag_type,
                    group_id=group_id,
                    confidence=1.0,
                    details={"matched_by": "media_id", "media_id": media_id},
                )
                for m in group_msgs
            ]
            clusters.append((group, flags))
        return clusters

    def _cluster_exact_text_messages(
        self, messages: list[MessageRecord], seen_ids: set[int]
    ) -> list[tuple[DuplicateGroup, list[AnalysisFlag]]]:
        """Group messages by conservative normalized-text SHA-256 identity."""
        clusters: list[tuple[DuplicateGroup, list[AnalysisFlag]]] = []
        text_map: dict[str, list[MessageRecord]] = defaultdict(list)
        for msg in messages:
            if msg.id in seen_ids or not msg.text_hash or len(msg.text.strip()) < 5:
                continue
            text_map[msg.text_hash].append(msg)

        for group_msgs in text_map.values():
            if len(group_msgs) < 2:
                continue
            msg_ids = [m.id for m in group_msgs]
            seen_ids.update(msg_ids)
            group_id = self._new_group_id("text")
            group = DuplicateGroup(
                id=group_id,
                chat_id=group_msgs[0].chat_id,
                group_type=DuplicateGroupType.EXACT_TEXT,
                message_ids=msg_ids,
                diff_summary={"reason": "Identical conservative normalized text"},
            )
            flags = [
                AnalysisFlag(
                    message_id=m.id,
                    chat_id=m.chat_id,
                    flag_type=FlagType.DUPLICATE_EXACT_TEXT,
                    group_id=group_id,
                    confidence=1.0,
                    details={"matched_by": "text_sha256"},
                )
                for m in group_msgs
            ]
            clusters.append((group, flags))
        return clusters

    def _cluster_forwarded_messages(
        self, messages: list[MessageRecord], seen_ids: set[int]
    ) -> list[tuple[DuplicateGroup, list[AnalysisFlag]]]:
        """Group repeated forwards of the exact same source post for human review."""
        forward_map: dict[tuple[int, int], list[MessageRecord]] = defaultdict(list)
        for msg in messages:
            if msg.id in seen_ids or msg.fwd_from_id is None or msg.fwd_channel_post is None:
                continue
            forward_map[(msg.fwd_from_id, msg.fwd_channel_post)].append(msg)

        result: list[tuple[DuplicateGroup, list[AnalysisFlag]]] = []
        for source, group_msgs in forward_map.items():
            if len(group_msgs) < 2:
                continue
            ids = [m.id for m in group_msgs]
            seen_ids.update(ids)
            group_id = self._new_group_id("forward")
            group = DuplicateGroup(
                id=group_id,
                chat_id=group_msgs[0].chat_id,
                group_type=DuplicateGroupType.FORWARD_CHAIN,
                message_ids=ids,
                diff_summary={
                    "source_peer_id": source[0],
                    "source_message_id": source[1],
                    "requires_review": True,
                },
            )
            flags = [
                AnalysisFlag(
                    message_id=m.id,
                    chat_id=m.chat_id,
                    flag_type=FlagType.DUPLICATE_FORWARD,
                    group_id=group_id,
                    confidence=1.0,
                    details={"matched_by": "forward_origin"},
                )
                for m in group_msgs
            ]
            result.append((group, flags))
        return result

    @staticmethod
    def _connected_components(
        nodes: list[MessageRecord], edges: list[tuple[int, int]]
    ) -> list[list[MessageRecord]]:
        """Return graph components containing at least two nodes."""
        by_id = {m.id: m for m in nodes}
        adjacency: dict[int, set[int]] = defaultdict(set)
        for left, right in edges:
            adjacency[left].add(right)
            adjacency[right].add(left)

        components: list[list[MessageRecord]] = []
        visited: set[int] = set()
        for node_id in adjacency:
            if node_id in visited:
                continue
            stack = [node_id]
            component_ids: list[int] = []
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component_ids.append(current)
                stack.extend(adjacency[current] - visited)
            if len(component_ids) >= 2:
                components.append([by_id[mid] for mid in component_ids])
        return components

    def _cluster_visual_media_messages(
        self, messages: list[MessageRecord], seen_ids: set[int]
    ) -> list[tuple[DuplicateGroup, list[AnalysisFlag]]]:
        """Find visually similar images with dHash; results require manual approval."""
        candidates = [
            m
            for m in messages
            if m.id not in seen_ids and m.media_type == "photo" and m.dhash
        ]
        edges: list[tuple[int, int]] = []
        distances: dict[tuple[int, int], int] = {}
        for i, left in enumerate(candidates):
            for right in candidates[i + 1 :]:
                if left.media_id and right.media_id and left.media_id == right.media_id:
                    continue
                if left.width and right.width and left.height and right.height:
                    if (left.width, left.height) != (right.width, right.height):
                        # Different resolutions can still be the same visual, but requiring the
                        # same geometry keeps this detector conservative.
                        continue
                distance = hamming_distance(left.dhash, right.dhash)
                if distance <= DHASH_MAX_HAMMING_DISTANCE:
                    edges.append((left.id, right.id))
                    distances[tuple(sorted((left.id, right.id)))] = distance

        result: list[tuple[DuplicateGroup, list[AnalysisFlag]]] = []
        for group_msgs in self._connected_components(candidates, edges):
            ids = [m.id for m in group_msgs]
            seen_ids.update(ids)
            pair_distances = [
                d for pair, d in distances.items() if pair[0] in ids and pair[1] in ids
            ]
            group_id = self._new_group_id("visual")
            group = DuplicateGroup(
                id=group_id,
                chat_id=group_msgs[0].chat_id,
                group_type=DuplicateGroupType.VISUAL_SIMILAR_MEDIA,
                message_ids=ids,
                diff_summary={
                    "max_hamming_distance": max(pair_distances, default=0),
                    "threshold": DHASH_MAX_HAMMING_DISTANCE,
                    "requires_review": True,
                },
            )
            flags = [
                AnalysisFlag(
                    message_id=m.id,
                    chat_id=m.chat_id,
                    flag_type=FlagType.DUPLICATE_VISUAL_MEDIA,
                    group_id=group_id,
                    confidence=0.8,
                    details={"matched_by": "dhash", "threshold": DHASH_MAX_HAMMING_DISTANCE},
                )
                for m in group_msgs
            ]
            result.append((group, flags))
        return result

    def _cluster_fuzzy_text_messages(
        self, messages: list[MessageRecord], seen_ids: set[int]
    ) -> list[tuple[DuplicateGroup, list[AnalysisFlag]]]:
        """Find near-duplicate text as review-only connected components."""
        candidates = [
            m for m in messages if m.id not in seen_ids and len(m.text.strip()) >= MIN_TEXT_LENGTH_FOR_FUZZY
        ]
        edges: list[tuple[int, int]] = []
        scores: dict[tuple[int, int], float] = {}
        for i, left in enumerate(candidates):
            left_len = max(len(left.text), 1)
            for right in candidates[i + 1 :]:
                right_len = max(len(right.text), 1)
                if min(left_len, right_len) / max(left_len, right_len) < 0.65:
                    continue
                score = token_sort_ratio(left.text, right.text)
                if score >= FUZZY_RATIO_THRESHOLD:
                    edges.append((left.id, right.id))
                    scores[tuple(sorted((left.id, right.id)))] = score

        result: list[tuple[DuplicateGroup, list[AnalysisFlag]]] = []
        for group_msgs in self._connected_components(candidates, edges):
            ids = [m.id for m in group_msgs]
            seen_ids.update(ids)
            group_scores = [s for pair, s in scores.items() if pair[0] in ids and pair[1] in ids]
            group_id = self._new_group_id("fuzzy")
            group = DuplicateGroup(
                id=group_id,
                chat_id=group_msgs[0].chat_id,
                group_type=DuplicateGroupType.FUZZY_TEXT,
                message_ids=ids,
                diff_summary={
                    "min_similarity": round(min(group_scores, default=FUZZY_RATIO_THRESHOLD), 1),
                    "threshold": FUZZY_RATIO_THRESHOLD,
                    "requires_review": True,
                },
            )
            flags = [
                AnalysisFlag(
                    message_id=m.id,
                    chat_id=m.chat_id,
                    flag_type=FlagType.DUPLICATE_FUZZY_TEXT,
                    group_id=group_id,
                    confidence=0.75,
                    details={"matched_by": "fuzzy_text", "threshold": FUZZY_RATIO_THRESHOLD},
                )
                for m in group_msgs
            ]
            result.append((group, flags))
        return result

    def _compute_caption_diff_summary(self, messages: list[MessageRecord]) -> dict[str, Any]:
        """Generate human-readable difference metrics across captions."""
        lengths = [len(m.text) for m in messages]
        has_update_marker = any(bool(UPDATE_MARKERS.search(m.text)) for m in messages)
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
        if not messages or preset == RetentionPreset.WHITELIST_ALL:
            return None
        if preset == RetentionPreset.KEEP_NEWEST:
            return max(messages, key=lambda m: (m.date, m.id)).id
        if preset == RetentionPreset.KEEP_OLDEST:
            return min(messages, key=lambda m: (m.date, m.id)).id
        if preset == RetentionPreset.KEEP_LONGEST:
            return max(messages, key=lambda m: (len(m.text), m.date, m.id)).id
        return max(messages, key=lambda m: (m.date, m.id)).id

    def _resolve_flags_for_group(
        self,
        group: DuplicateGroup,
        messages: list[MessageRecord],
        preset: RetentionPreset,
        *,
        explicit: bool,
    ) -> list[AnalysisFlag]:
        primary_id = self._pick_primary_message_id(messages, preset)
        flag_type_map = {
            DuplicateGroupType.EXACT_TEXT: FlagType.DUPLICATE_EXACT_TEXT,
            DuplicateGroupType.EXACT_MEDIA: FlagType.DUPLICATE_EXACT_MEDIA,
            DuplicateGroupType.VISUAL_SIMILAR_MEDIA: FlagType.DUPLICATE_VISUAL_MEDIA,
            DuplicateGroupType.SAME_MEDIA_DIFF_CAPTION: FlagType.DUPLICATE_SAME_MEDIA_DIFF_CAPTION,
            DuplicateGroupType.FUZZY_TEXT: FlagType.DUPLICATE_FUZZY_TEXT,
            DuplicateGroupType.FORWARD_CHAIN: FlagType.DUPLICATE_FORWARD,
        }
        flag_type = flag_type_map[group.group_type]
        may_auto_delete = group.group_type in _AUTO_ELIGIBLE_GROUPS

        flags: list[AnalysisFlag] = []
        for message in messages:
            eligible = (
                preset != RetentionPreset.WHITELIST_ALL
                and message.id != primary_id
                and (explicit or may_auto_delete)
            )
            flags.append(
                AnalysisFlag(
                    message_id=message.id,
                    chat_id=message.chat_id,
                    flag_type=flag_type,
                    group_id=group.id,
                    is_candidate_for_deletion=eligible,
                    confidence=1.0 if may_auto_delete else 0.75,
                    details={
                        "preset": preset.value,
                        "is_keeper": message.id == primary_id,
                        "requires_review": not may_auto_delete,
                        "explicitly_reviewed": explicit,
                    },
                )
            )
        return flags

    def _apply_retention_policy(
        self,
        group: DuplicateGroup,
        flags: list[AnalysisFlag],
        preset: RetentionPreset,
        *,
        explicit: bool,
    ) -> None:
        group.recommended_preset = preset
        messages = self.db.get_messages_by_ids(group.chat_id, group.message_ids)
        group.primary_message_id = self._pick_primary_message_id(messages, preset)
        may_auto_delete = group.group_type in _AUTO_ELIGIBLE_GROUPS
        group.diff_summary["requires_review"] = not may_auto_delete
        for flag in flags:
            flag.is_candidate_for_deletion = (
                preset != RetentionPreset.WHITELIST_ALL
                and flag.message_id != group.primary_message_id
                and (explicit or may_auto_delete)
            )
            flag.details.update(
                {
                    "preset": preset.value,
                    "is_keeper": flag.message_id == group.primary_message_id,
                    "requires_review": not may_auto_delete,
                    "explicitly_reviewed": explicit,
                }
            )

    def apply_retention_preset(
        self, group: DuplicateGroup, preset: RetentionPreset
    ) -> list[AnalysisFlag]:
        """Explicitly review a group and apply a deletion retention policy to it."""
        messages = self.db.get_messages_by_ids(group.chat_id, group.message_ids)
        group.recommended_preset = preset
        group.primary_message_id = self._pick_primary_message_id(messages, preset)
        group.diff_summary["requires_review"] = False if preset != RetentionPreset.WHITELIST_ALL else True
        self.db.upsert_duplicate_group(group)

        flags = self._resolve_flags_for_group(group, messages, preset, explicit=True)
        self.db.update_flags_for_group(group.id, flags)
        return flags
