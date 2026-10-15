"""Legacy Hindi font conversion (Kruti Dev 010 / DevLys 010 -> Unicode).

Many SCERT Chhattisgarh Hindi-medium PDFs are typeset in Kruti Dev, a
pre-Unicode font that draws Devanagari glyphs on Latin code points. Their
text layer reads as "rkfydk&1 esa" instead of "तालिका-1 में", which neither
retrieval nor the SLM can use. This module converts that text.

Kruti Dev is a fixed keyboard-to-glyph mapping, so conversion is
deterministic: greedy longest-match token mapping, then two reordering rules:
  - "f" (ि) is typed BEFORE its consonant cluster; it is moved after it.
  - "Z" (reph, र्) is typed AFTER its syllable; it is moved before it.

Known limits: glyphs the PDF does not expose (rare ligatures) are lost, and
typing errors in the source survive. Quality is checked at ingestion
(`devanagari_share`); see docs/CURRICULUM.md.
"""
from __future__ import annotations

import re
import unicodedata

# Ordered roughly by length; tokenisation is greedy longest-match.
_MAP: dict[str, str] = {
    # vowels
    "vks": "ओ", "vkS": "औ", "v‚": "ऑ", "vk": "आ", "v": "अ", "b±": "ईं", "bZ": "ई", "Ã": "ई", "b": "इ",
    "m": "उ", "Å": "ऊ", ",s": "ऐ", ",": "ए", "_": "ऋ",
    # conjuncts and ligatures
    "Ùk": "त्त", "Ù": "त्त्", "Ÿk": "त्त", "Ÿ": "त्त्", "Dr": "क्त", "xz": "ग्र", "–": "दृ", "—": "कृ", "Ñ": "कृ",
    "é": "न्न", "™": "न्न्", "à": "ह्न", "á": "ह्य", "â": "हृ", "ã": "ह्म", "º": "ह्", "í": "द्द", "Ì": "द्द",
    "æ": "द्र", "ç": "प्र", "Á": "प्र", "Ø": "क्र", "Ý": "फ्र", "|": "द्य", "}": "द्व", "J": "श्र", "K": "ज्ञ",
    "{k": "क्ष", "{": "क्ष्", "=": "त्र", "«": "त्र्", "#": "रु", ":": "रू", "ô": "क्क", "ê": "ट्ट", "Í": "ट्ट",
    "ë": "ट्ठ", "Î": "ट्ठ", "ì": "ड्ड", "Ï": "ड्ड", "ï": "ड्ढ", "Ô": "ड्ढ", "èk": "ध", "è": "ध्", "Ë": "ध्",
    "Ö": "झ्", "Ük": "श", "Ü": "श्", "î": "्य", "Ó": "्य",
    # consonants (full, and half forms; half + "k" = full)
    "Dk": "क", "d": "क", "D": "क्", "[k": "ख", "[": "ख्", "Xk": "ग", "x": "ग", "X": "ग्", "?k": "घ", "?": "घ्",
    "³": "ङ", "Pk": "च", "p": "च", "P": "च्", "N": "छ", "Tk": "ज", "t": "ज", "T": "ज्", ">": "झ", "÷": "झ्",
    "¥": "ञ", "V": "ट", "B": "ठ", "M": "ड", "<": "ढ", ".k": "ण", ".": "ण्", "Rk": "त", "r": "त", "R": "त्",
    "Fk": "थ", "F": "थ्", "n": "द", "/k": "ध", "/": "ध्", "Uk": "न", "u": "न", "U": "न्", "Ik": "प", "i": "प",
    "I": "प्", "Q": "फ", "¶": "फ्", "Ck": "ब", "c": "ब", "C": "ब्", "Hk": "भ", "H": "भ्", "Ek": "म", "e": "म",
    "E": "म्", ";": "य", "¸": "य्", "j": "र", "Yk": "ल", "y": "ल", "Y": "ल्", "G": "ळ", "Ok": "व", "o": "व",
    "O": "व्", "'k": "श", "'": "श्", "’k": "श", "’": "श्", '"k': "ष", '"': "ष्", "”k": "ष", "”": "ष्",
    "Lk": "स", "l": "स", "L": "स्", "g": "ह",
    # vowel signs and marks
    "ks": "ो", "kS": "ौ", "k": "ा", "h": "ी", "q": "ु", "w": "ू", "`": "ृ", "s": "े", "S": "ै", "a": "ं",
    "¡": "ँ", "%": "ः", "~": "्", "+": "़", "z": "्र", "ª": "्र", "‚": "ॉ", "W": "ॅ", "f": "ि",
    "Z": "\x00", "±": "\x00ं",  # reph marker, resolved below
    # punctuation and digits
    "A": "।", "-": ".", "&": "-", "(": ";", "¼": "(", "½": ")", "]": ",", "@": "/", "*": "‘", "^": "’",
    "Þ": "“", "ß": "”", "¿": "{", "À": "}", "\\": "?", "Û": "•", "ñ": "॰",
    "å": "०", "ƒ": "१", "„": "२", "…": "३", "†": "४", "‡": "५", "ˆ": "६", "‰": "७", "Š": "८", "‹": "९",
}
_MAXLEN = max(len(k) for k in _MAP)

_C = "[क-हक़-य़]़?"          # consonant (+ nukta)
_CLUSTER = f"(?:{_C}्)*{_C}"                      # half consonants + final consonant
_MATRAS = "ा-ौँ-ःॅ"
_I_FIX = re.compile(f"ि({_CLUSTER})")             # ि + cluster -> cluster + ि
_REPH_FIX = re.compile(f"({_CLUSTER}[{_MATRAS}]*)\x00")  # syllable + reph -> र् + syllable
_NASAL_FIX = re.compile("([ंँ])([ा-ौ])")  # anusvara typed before a matra


def krutidev_to_unicode(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        for size in range(min(_MAXLEN, n - i), 0, -1):
            piece = text[i:i + size]
            if piece in _MAP:
                out.append(_MAP[piece])
                i += size
                break
        else:
            out.append(text[i])
            i += 1
    s = "".join(out)
    s = _I_FIX.sub(r"\1ि", s)
    s = _REPH_FIX.sub(r"र्\1", s)
    s = s.replace("\x00", "र्")  # unresolved reph (no preceding syllable)
    s = _NASAL_FIX.sub(r"\2\1", s)
    s = s.replace("ाे", "ो").replace("ाै", "ौ").replace("अा", "आ")
    return unicodedata.normalize("NFC", s)


def devanagari_share(text: str) -> float:
    """Share of letters that are Devanagari - a cheap check that conversion worked."""
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if "ऀ" <= c <= "ॿ") / len(letters) if letters else 0.0


def pdf_page_text(page, font_pattern: str = r"kruti|devlys|^CIDFont") -> str:
    """Extract one pdfplumber page, converting only words set in a legacy font
    (English words in Times/Arial stay as they are)."""
    legacy = re.compile(font_pattern, re.I)
    # Words are built from characters in content-stream order. Kruti Dev draws
    # some vowel signs backwards over the previous glyph, so the gap is measured
    # from the right-most edge seen in the word, not from the last glyph.
    words: list[dict] = []
    cur = None
    for ch in page.chars:
        text = ch["text"]
        size = ch.get("size") or 10
        new_line = cur is not None and abs(ch["top"] - cur["top"]) > size * 0.5
        gap = ch["x0"] - cur["x1"] if cur is not None else 0
        if cur is None or new_line or text.isspace() or gap > size * 0.18 or ch["fontname"] != cur["font"]:
            if cur is not None and cur["text"]:
                words.append(cur)
            cur = {"text": "", "font": ch["fontname"], "top": ch["top"], "bottom": ch["bottom"], "x1": ch["x1"]}
            if text.isspace():
                continue
        cur["text"] += text
        cur["x1"] = max(cur["x1"], ch["x1"])
    if cur is not None and cur["text"]:
        words.append(cur)

    lines: list[list[str]] = []
    last_top, last_bottom = None, None
    for w in words:
        font = w["font"] if w["font"].startswith("CIDFont") else w["font"].split("+", 1)[-1]
        txt = krutidev_to_unicode(w["text"]) if legacy.search(font) else w["text"]
        if last_top is None or abs(w["top"] - last_top) > 3:
            if last_bottom is not None and w["top"] - last_bottom > (w["bottom"] - w["top"]) * 0.9:
                lines.append([])  # paragraph gap
            lines.append([])
        lines[-1].append(txt)
        last_top, last_bottom = w["top"], w["bottom"]
    text = "\n".join(" ".join(l) for l in lines)
    text = re.sub(r"\(cid:\d+\)", "", text)
    # a word that starts with a vowel sign belongs to the previous word
    return re.sub(r" (?=[ऀ-ःऺ-ॏॢॣ])", "", text)
