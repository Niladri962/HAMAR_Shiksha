"""Voice input, theme toggle and legacy-font (Kruti Dev) textbook conversion."""
import io
import wave

import pytest

from app.config import get_settings
from app.kb.legacy_fonts import devanagari_share, krutidev_to_unicode
from app.services import stt


# ------------------------------------------------------------ Kruti Dev --

@pytest.mark.parametrize("legacy, unicode_", [
    ("rkfydk&1 esa dqN tarqvksa ds uke fy[ks x, gSaA", "तालिका-1 में कुछ जंतुओं के नाम लिखे गए हैं।"),
    ("'kCnkFkZ iz'u vkSj vH;kl", "शब्दार्थ प्रश्न और अभ्यास"),       # reph moved before its syllable
    ("iwoZ mŸkj if'pe nf{k.k", "पूर्व उत्तर पश्चिम दक्षिण"),
    ('jk"Vªh; izrhd', "राष्ट्रीय प्रतीक"),
    ("fpg~u ;k ladsr ls fn[kkbZ tkrh gaSA", "चिह्न या संकेत से दिखाई जाती हैं।"),  # anusvara typed before matra
    ("fLFkfr Hkkstu fo|ky; dk;Z", "स्थिति भोजन विद्यालय कार्य"),     # ि moved after a conjunct
    ("i;kZoj.k v/;;u&5", "पर्यावरण अध्ययन-5"),
])
def test_krutidev_conversion(legacy, unicode_):
    assert krutidev_to_unicode(legacy) == unicode_


def test_segment_splits_long_pages_and_finds_chapters():
    from app.kb.ingest import MAX_WORDS, segment

    sentence = "Friction is a force that opposes motion between two surfaces in contact."
    page = "CHAPTER- 14\nFriction\n" + "\n".join([sentence] * 60)  # one 700-word "paragraph", no blank lines
    chunks = segment([(84, page)])
    assert len(chunks) >= 4
    assert all(len(c["text"].split()) <= MAX_WORDS for c in chunks)
    assert all(c["page"] == 84 and c["chapter"] == "CHAPTER- 14: Friction" for c in chunks)
    hindi = segment([(3, "पाठ-4 मैं सड़क हूँ\n" + "सड़क ने अपनी कहानी स्वयं कही है। " * 10)])
    assert hindi[0]["chapter"] == "पाठ-4 मैं सड़क हूँ"


def test_chapters_from_running_headers_when_no_headings():
    from app.kb.ingest import segment

    body = "\n".join(["वायु हमारे चारों तरफ है और सजीवों के लिए आवश्यक है।"] * 3)
    pages = [(1, f"विज्ञान कक्षा 8\n{body}"), (2, f"वायु\n{body}"), (3, f"विज्ञान कक्षा 8\n{body}"),
             (4, f"वायु\n{body}"), (5, f"विज्ञान कक्षा 8\n{body}")]
    chapters = [c["chapter"] for c in segment(pages)]
    assert chapters[0] is None and set(chapters[1:]) == {"वायु"}


def test_devanagari_share_detects_failed_conversion():
    assert devanagari_share("तालिका में कुछ जंतु") == 1.0
    assert devanagari_share("rkfydk esa dqN") == 0.0


# ---------------------------------------------------------------- voice --

def _wav(samples: bytes, rate=16000, channels=1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples)
    return buf.getvalue()


def test_voice_requires_sign_in(anon):
    assert anon.get("/api/voice/status").status_code == 401
    r = anon.post("/api/voice/transcribe", files={"audio": ("q.wav", _wav(b"\0\0" * 16000), "audio/wav")})
    assert r.status_code in (401, 403)


def test_voice_disabled_by_default(as_):
    c = as_("student5")
    assert c.get("/api/voice/status").json()["speech_to_text"] is False
    r = c.post("/api/voice/transcribe", files={"audio": ("q.wav", _wav(b"\0\0" * 16000), "audio/wav")})
    assert r.status_code == 503
    assert c.get("/api/platform").json()["voice"] == {"speech_to_text": False}


def test_voice_validates_audio_and_never_invents_text_from_silence(as_, monkeypatch):
    monkeypatch.setattr(get_settings(), "stt_model", "base")
    monkeypatch.setattr(stt, "_load", lambda: pytest.fail("silence must not reach the model"))
    c = as_("student5")
    assert c.post("/api/voice/transcribe", files={"audio": ("q.wav", b"not audio", "audio/wav")}).status_code == 422
    too_long = _wav(b"\0\0" * 16000 * (get_settings().stt_max_seconds + 5))
    assert c.post("/api/voice/transcribe", files={"audio": ("q.wav", too_long, "audio/wav")}).status_code == 413
    r = c.post("/api/voice/transcribe", files={"audio": ("q.wav", _wav(b"\0\0" * 32000), "audio/wav")},
               data={"language": "hi"})
    assert r.status_code == 200
    assert r.json()["text"] == "" and r.json()["reason"] == "silence"


def test_wav_decoding_resamples_to_16k():
    audio = stt.decode_wav(_wav(b"\x10\x00" * 48000, rate=48000))
    assert len(audio) == 16000


def test_microphone_allowed_only_for_this_site(anon):
    pp = anon.get("/").headers["Permissions-Policy"]
    assert "microphone=(self)" in pp and "camera=()" in pp


# ---------------------------------------------------------------- theme --

@pytest.mark.parametrize("page", ["/", "/student/login", "/teacher/login", "/admin/login"])
def test_every_page_loads_the_theme_toggle_before_paint(anon, page):
    html = anon.get(page).text
    head = html.split("</head>")[0]
    assert '<script src="/static/js/theme.js"></script>' in head  # not deferred: no flash of the wrong theme


def test_theme_script_and_dark_styles_are_served(anon):
    assert anon.get("/static/js/theme.js").status_code == 200
    css = anon.get("/static/css/app.css").text
    assert ':root[data-theme="dark"] body.theme-student' in css
