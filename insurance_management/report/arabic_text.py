# -*- coding: utf-8 -*-
"""Tiny Arabic text shaper + bidi reorderer for ReportLab.

ReportLab draws glyphs left-to-right exactly as given, with no OpenType
shaping and no bidi support, so raw Arabic comes out as disconnected,
reversed letters. ``shape()`` converts logical-order text to the visual-order
string ReportLab needs: letters joined into their initial/medial/final forms
(Unicode Arabic Presentation Forms-B, which the bundled DejaVu Sans font
contains), lam-alef ligatures, and runs reordered right-to-left, with
Latin text and numbers kept left-to-right.

Pure Python, no third-party packages. Text without any Arabic/Hebrew
character is returned untouched.
"""
import unicodedata

_ALEFS = {0x0622, 0x0623, 0x0625, 0x0627}
_MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<"}

# base codepoint -> {"isolated": ch, "final": ch, "initial": ch, "medial": ch}
_FORMS = {}
# (lam, alef-variant codepoint) -> {"isolated": ch, "final": ch}
_LIGATURES = {}


def _build_tables():
    for cp in range(0xFE70, 0xFF00):
        ch = chr(cp)
        decomposition = unicodedata.decomposition(ch)
        if not decomposition.startswith("<"):
            continue
        tag, _sep, rest = decomposition.partition("> ")
        form = tag.strip("<")
        codes = [int(code, 16) for code in rest.split()]
        if form not in ("isolated", "final", "initial", "medial"):
            continue
        if len(codes) == 1:
            _FORMS.setdefault(codes[0], {})[form] = ch
        elif len(codes) == 2 and codes[0] == 0x0644 and codes[1] in _ALEFS:
            _LIGATURES.setdefault((codes[0], codes[1]), {})[form] = ch


_build_tables()


def _is_arabic(ch):
    cp = ord(ch)
    return (
        0x0600 <= cp <= 0x06FF
        or 0x0750 <= cp <= 0x077F
        or 0xFB50 <= cp <= 0xFDFF
        or 0xFE70 <= cp <= 0xFEFF
        or 0x0590 <= cp <= 0x05FF
    )


def _is_transparent(ch):
    return unicodedata.category(ch) == "Mn"


def _can_join_next(cp):
    """Dual-joining letters connect to the letter that follows them."""
    return "initial" in _FORMS.get(cp, {})


def _can_join_prev(cp):
    """Letters that have a joined-to-previous (final) form."""
    return "final" in _FORMS.get(cp, {})


def _reshape(text):
    chars = list(text)
    count = len(chars)
    out = []
    i = 0
    prev_joins = False  # previous visible letter connects forward into this one
    while i < count:
        ch = chars[i]
        cp = ord(ch)
        if _is_transparent(ch):
            out.append(ch)
            i += 1
            continue
        if cp not in _FORMS:
            out.append(ch)
            prev_joins = False
            i += 1
            continue

        # Look ahead to the next non-transparent character.
        j = i + 1
        while j < count and _is_transparent(chars[j]):
            j += 1
        next_cp = ord(chars[j]) if j < count else None

        if cp == 0x0644 and next_cp in _ALEFS:
            liga = _LIGATURES.get((cp, next_cp), {})
            key = "final" if prev_joins and "final" in liga else "isolated"
            out.append(liga.get(key) or liga.get("isolated") or ch)
            out.extend(chars[i + 1 : j])  # keep any diacritics in between
            prev_joins = False
            i = j + 1
            continue

        next_joins = _can_join_next(cp) and next_cp is not None and _can_join_prev(next_cp)
        forms = _FORMS[cp]
        if prev_joins and next_joins:
            key = "medial"
        elif prev_joins:
            key = "final"
        elif next_joins:
            key = "initial"
        else:
            key = "isolated"
        out.append(forms.get(key) or forms.get("isolated") or ch)
        prev_joins = _can_join_next(cp) and next_joins
        i += 1
    return "".join(out)


def _direction(ch):
    """'R', 'L' or None (neutral) for a single character."""
    bidi = unicodedata.bidirectional(ch)
    if bidi in ("R", "AL"):
        return "R"
    if bidi in ("L", "EN", "AN"):
        return "L"
    return None


def _reorder(text):
    n = len(text)
    dirs = [_direction(ch) for ch in text]
    # Combining marks follow the direction of the letter they sit on.
    for idx in range(n):
        if dirs[idx] is None and unicodedata.category(text[idx]) == "Mn" and idx:
            dirs[idx] = dirs[idx - 1]

    base = next((d for d in dirs if d), "L")
    # Resolve neutrals: between two strong chars of the same direction they
    # take that direction, otherwise the paragraph direction.
    resolved = list(dirs)
    idx = 0
    while idx < n:
        if resolved[idx] is not None:
            idx += 1
            continue
        start = idx
        while idx < n and resolved[idx] is None:
            idx += 1
        before = resolved[start - 1] if start > 0 else base
        after = resolved[idx] if idx < n else base
        fill = before if before == after else base
        for k in range(start, idx):
            resolved[k] = fill

    runs = []  # [direction, [chars]]
    for ch, d in zip(text, resolved):
        if runs and runs[-1][0] == d:
            runs[-1][1].append(ch)
        else:
            runs.append([d, [ch]])

    pieces = []
    for d, chunk in runs:
        if d == "R":
            chunk = [_MIRROR.get(c, c) for c in reversed(chunk)]
        pieces.append("".join(chunk))
    if base == "R":
        pieces.reverse()
    return "".join(pieces)


def shape(text):
    """Return ``text`` ready to be drawn by ReportLab (visual order)."""
    if not text:
        return text or ""
    text = str(text)
    if not any(_is_arabic(ch) for ch in text):
        return text
    return _reorder(_reshape(text))
