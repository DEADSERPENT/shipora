"""Post-correction of speech-to-text output (the "hearing" half of the sandwich).

Telephony/ASR models are good at sentences and bad at what a parcel assistant needs most: spelled identifiers and
brand words. This module repairs the predictable mistakes *before* the text reaches the agents:

  * spoken digits / NATO words inside an ID ("S H P one alpha two bravo ...") -> "SHP1A2B...";
  * brand words ("ship ora", "ship bot") -> Shipora / ShipBot;
  * letters that cannot appear in a tracking number (hex 0-9 A-F only) but sound like ones that can
    ("5V" heard for "5E": V/E/B/D/T/P all rhyme) -> the nearest valid character.

It only ever edits things that look like a tracking number or a known brand word, so ordinary speech passes through untouched."""

import re

_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "to": "2", "too": "2", "three": "3", "four": "4", "for": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "ate": "8", "nine": "9"}
_NATO = {"alpha": "A", "alfa": "A", "bravo": "B", "charlie": "C", "delta": "D", "echo": "E", "foxtrot": "F"}
_LETTER_WORDS = {"a": "A", "b": "B", "bee": "B", "c": "C", "see": "C", "d": "D", "dee": "D", "e": "E", "f": "F", "eff": "F"}
# Non-hex letters -> the valid hex character they are most often confused with by ASR (same vowel sound).
_NON_HEX_FIX = {"O": "0", "I": "1", "L": "1", "V": "E", "T": "D", "P": "B", "K": "A", "G": "C", "Z": "C", "U": "E"}
_BRANDS = [(re.compile(r"\bship\s*ora(?:'s)?\b", re.I), "Shipora"), (re.compile(r"\bship\s*bot\b", re.I), "ShipBot"),
           (re.compile(r"\bshipper\s*a\b", re.I), "Shipora"), (re.compile(r"\bship\s*or\s*a\b", re.I), "Shipora")]
_TOKEN = re.compile(r"[A-Za-z0-9]+")


_SHP_START = re.compile(r"(?<![A-Za-z0-9])s\W{0,2}h\W{0,2}p(?![A-Za-z])", re.I)
_WORD = re.compile(r"[A-Za-z0-9]+")


def _piece_chars(piece: str):
    """The tracking-number characters one spoken token stands for, or None if it is not part of an ID."""
    low = piece.lower()
    if low in _DIGIT_WORDS and low not in ("to", "too", "for"):
        return _DIGIT_WORDS[low]
    if low in _NATO:
        return _NATO[low]
    if low in ("bee", "dee", "see", "eff"):
        return _LETTER_WORDS[low]
    if re.fullmatch(r"[0-9a-z]{1,10}", low) and (len(low) == 1 or any(c.isdigit() for c in low)):
        return low.upper()
    return None


def _spoken_run_to_chars(text: str) -> str:
    """'shp one alpha two bravo ...' / 'S H P 1 a 2 b ...' -> 'SHP1A2B...' (only directly after an SHP marker)."""
    out, pos = [], 0
    for m in _SHP_START.finditer(text):
        if m.start() < pos:
            continue
        chars, end = [], m.end()
        for w in _WORD.finditer(text, m.end()):
            if w.start() - end > 3 or len(chars) >= 16:      # a real gap in the speech ends the ID
                break
            got = _piece_chars(w.group(0))
            if got is None:
                break
            chars.append(got)
            end = w.end()
        flat = "".join(chars)
        if flat.isdigit() and len(flat) >= 6 and len(flat) not in (8, 10):
            continue          # 8 digits = current ID, 10 = legacy. Any other count means the ASR dropped or REPEATED digits
                              # ("four four four four…"): never guess which — leave it unparsed so the caller is asked to repeat
        if len(flat) >= 8:                                  # looks like an ID; otherwise leave the sentence alone
            out.append(text[pos:m.start()] + "SHP" + flat[:10])
            pos = end
    out.append(text[pos:])
    return "".join(out)


# Current format: SHP + 8 digits (spoken "S H P 4 8 2 1 7 3 9 0" / "SHP 4821 7390"). Legacy: SHP + 10 hex characters.
_NEW_ID = re.compile(r"(?<![A-Za-z0-9])S\W{0,2}H\W{0,2}P(?:\W{0,2}[A-Za-z](?=\W{0,2}\d))?((?:\W{0,2}\d){8})(?!\d)", re.I)  # tolerates ONE stray letter the ASR glues on ("SHPA8079...")
_CANDIDATE = re.compile(r"(?<![A-Za-z0-9])S\W{0,2}H\W{0,2}P(?!(?:\W{0,2}\d){8}(?!\d))((?:\W{0,2}[0-9A-Z]){10})(?![0-9A-Za-z])", re.I)


def _repair_candidate(m: re.Match) -> str:
    """Legacy hex IDs only. Lookalike letters are mapped to the nearest hex digit; if anything is still not hex the
    'candidate' was ordinary words ("SHP one two four…" -> letters of "onetwofour"), so the text is left untouched."""
    chars = re.sub(r"\W", "", m.group(1)).upper()
    fixed = "".join(c if c in "0123456789ABCDEF" else _NON_HEX_FIX.get(c, c) for c in chars)
    return "SHP" + fixed if re.fullmatch(r"[0-9A-F]{10}", fixed) else m.group(0)


def _new_id(m: re.Match) -> str:
    return "SHP" + re.sub(r"\D", "", m.group(1))


# "SHP" is not an English word, so ASR often hears its last letter as a rhyming one ("SHB 6071 7355", measured with Whisper small).
# Only repaired when exactly 8 digits follow, i.e. when the text is plainly a tracking number.
_SHP_LOOKALIKE = re.compile(r"(?<![A-Za-z0-9])(S\W{0,2}H\W{0,2})[BTDV](?=(?:\W{0,2}\d){8}(?!\d))", re.I)


def extract_id(text: str):
    """The tracking number in `text` in canonical form (spoken, spaced or mis-heard variants repaired), or None."""
    text = _SHP_LOOKALIKE.sub(lambda m: m.group(1) + "P", text or "")
    m = _NEW_ID.search(text or "")
    if m:
        return _new_id(m)
    m = _CANDIDATE.search(text or "")
    if m and re.fullmatch(r"SHP[0-9A-F]{10}", _repair_candidate(m)):
        return _repair_candidate(m)
    # The ASR mangled the prefix itself ("as HP 81742801"): trust the sentence around it instead — "tracking number is <8 digits>".
    m = _CONTEXT_ID.search(text or "")
    if m:
        return _new_id(m)
    # One or two digits were dropped ("SHP-3591090"): not a valid ID, but close enough for the caller's own-shipment repair.
    m = _SHORT_ID.search(text or "")
    return "SHP" + re.sub(r"\D", "", m.group(1)) if m else None


_CONTEXT_ID = re.compile(r"tracking\s*(?:number|no\.?|id)\W+(?:is\W+)?(?:[A-Za-z]{1,3}\W{0,2}){0,3}((?:\W{0,2}\d){8})(?!\d)", re.I)
_SHORT_ID = re.compile(r"(?<![A-Za-z0-9])S\W{0,2}H\W{0,2}P\W{0,2}((?:\W{0,2}\d){6,7})(?!\d)", re.I)


def fix_transcript(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in _BRANDS:
        text = pattern.sub(replacement, text)
    text = _SHP_LOOKALIKE.sub(lambda m: m.group(1) + "P", text)
    text = _spoken_run_to_chars(text)
    text = _NEW_ID.sub(_new_id, text)
    return _CANDIDATE.sub(_repair_candidate, text)
