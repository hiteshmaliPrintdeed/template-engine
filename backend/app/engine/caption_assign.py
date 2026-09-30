"""
Caption assignment: every spread in a book gets a caption no other spread in
that book uses.

The solver asks for one caption per spread; the allocator answers from, in
order: the spread's segment pool (people lines for spreads with faces, neutral
lines for the rest), the variation's book-level pool, then the free local
reserve. A line already used anywhere in the book -- or a near-duplicate of one
("A day to remember" vs "A day to remember forever") -- is skipped. Only when
every source is exhausted does a line repeat, and that is logged.

Each variation starts its walk through a pool at a different offset, so the
three books differ even though they share the pools. Everything is
deterministic, so reshuffling (which keeps the spread structure) reproduces the
same captions.
"""

import re
from typing import Dict, List, Optional, Sequence, Set

from app.config import logger
from app.engine.story_content import people_claims, to_display

# Words too common to make two lines "the same" by sharing them.
_STOP = {
    "a", "an", "the", "of", "in", "on", "to", "and", "with", "for", "at", "by", "is", "it", "its",
    "this", "that", "every", "all", "our", "we", "us", "so", "as", "be", "are", "from", "one",
}
# Above 0.6 on purpose: "A day to remember" vs "A day to remember forever"
# (0.67) is one line, but "Day 1 begins here" vs "Day 2 begins here" (exactly
# 0.6) are two.
NEAR_DUPLICATE_JACCARD = 0.65


def _significant(text: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in _STOP)


def near_duplicate(a: frozenset, b: frozenset) -> bool:
    """Two lines are the same line if most of their significant words match."""
    if not a or not b:
        return a == b
    return len(a & b) / len(a | b) >= NEAR_DUPLICATE_JACCARD


class CaptionAllocator:
    def __init__(
        self,
        var_idx: int,
        segment_pools: Optional[Sequence[Optional[Dict[str, List[str]]]]] = None,
        variation_pool: Optional[Sequence[str]] = None,
        reserve: Optional[Dict[str, List[str]]] = None,
        variation_count: int = 3,
    ):
        self.var_idx = var_idx
        self.variation_count = variation_count
        self.segment_pools = list(segment_pools or [])
        self.variation_pool = list(variation_pool or [])
        self.reserve = reserve or {"people": [], "neutral": []}
        self._used_keys: Set[str] = set()
        self._used_sig: List[frozenset] = []
        # word -> indexes into _used_sig. Near-duplicates must share a word, so
        # a candidate is compared only with used lines it overlaps -- a few,
        # rather than every line in a 500-spread book.
        self._by_word: Dict[str, List[int]] = {}
        self._cursor: Dict[tuple, int] = {}
        self.repeats = 0

    # -- bookkeeping -------------------------------------------------------

    def mark_used(self, text: str) -> None:
        """Record a line placed by other means (a segment title), so no caption
        repeats it."""
        if text:
            self._used_keys.add(to_display(text))
            sig = _significant(text)
            self._used_sig.append(sig)
            for word in sig:
                self._by_word.setdefault(word, []).append(len(self._used_sig) - 1)

    def _is_free(self, text: str) -> bool:
        if to_display(text) in self._used_keys:
            return False
        sig = _significant(text)
        candidates = {i for word in sig for i in self._by_word.get(word, ())}
        return not any(near_duplicate(sig, self._used_sig[i]) for i in candidates)

    def _take_from(self, key: tuple, pool: Sequence[str], allow_people_words: bool) -> Optional[str]:
        """Next free line from pool, walking from this variation's offset."""
        if not pool:
            return None
        n = len(pool)
        start = self._cursor.get(key, (self.var_idx * n) // self.variation_count)
        for step in range(n):
            i = (start + step) % n
            line = pool[i]
            if not allow_people_words and people_claims(line):
                continue
            if self._is_free(line):
                self._cursor[key] = i + 1
                return line
        return None

    # -- the one call the solver makes ------------------------------------

    def take(self, segment_index: Optional[int], has_people: bool) -> str:
        kinds = ("people", "neutral") if has_people else ("neutral",)
        sources: List[tuple] = []
        seg = (
            self.segment_pools[segment_index]
            if segment_index is not None and segment_index < len(self.segment_pools)
            else None
        )
        if seg:
            sources += [(("seg", segment_index, k), seg.get(k) or [], k == "people") for k in kinds]
        # Book-level lines carry no people/neutral split: on a spread without
        # faces, only the ones free of people words may be used.
        sources.append((("var",), self.variation_pool, has_people))
        sources += [(("reserve", k), self.reserve.get(k) or [], k == "people") for k in kinds]

        for key, pool, allow_people in sources:
            line = self._take_from(key, pool, allow_people)
            if line is not None:
                self.mark_used(line)
                return line

        # Every source exhausted: repeat rather than print nothing. Only
        # expected for very large books generated fully offline.
        self.repeats += 1
        fallback = next(
            (l for _, pool, allow in sources for l in pool if allow or not people_claims(l)),
            "",
        )
        if self.repeats == 1:
            logger.warning(
                f"[Captions] Variation {self.var_idx + 1}: all caption sources exhausted; "
                f"repeating lines from here on"
            )
        return fallback
