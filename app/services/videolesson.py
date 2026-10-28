"""AI video lessons: when a subject teacher is unavailable, a teacher (or the
head teacher) gives a topic and gets a narrated, animated lesson for the class.

The "video" is a scene-by-scene script that the browser plays as an animated
lesson with spoken narration (device text-to-speech), captions and a short
quiz. It is not generated footage: a small local model cannot render video,
and narration plus visuals keeps it light enough for low-end phones and offline
use. The script is drafted by Gyan SLM from the approved textbook passages and
checked for grounding; without a model it is built directly from the passages
and labelled as such. Nothing reaches students until a teacher publishes it.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.kb import retrieval
from app.models import VideoLesson, utcnow
from app.slm import gyan
from app.slm.runtime import SLMUnavailable, get_runtime

MAX_SCENES = 7
VISUALS = ("📘", "💡", "🔍", "✏️", "🧮", "🌱", "🗺️", "🔬", "🧩", "✅", "🎯", "📝")
SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "scenes": {"type": "array", "items": {"type": "object", "properties": {
            "heading": {"type": "string"}, "narration": {"type": "string"},
            "points": {"type": "array", "items": {"type": "string"}}, "visual": {"type": "string"}},
            "required": ["heading", "narration"]}},
        "quiz": {"type": "array", "items": {"type": "object", "properties": {
            "question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
            "answer_index": {"type": "integer"}, "explanation": {"type": "string"}},
            "required": ["question", "options", "answer_index"]}},
    },
    "required": ["title", "scenes"],
}
_CITES = re.compile(r"\s*[\[(](?:sources?:?\s*)?S\d+(?:\s*,\s*S?\d+)*[\])]", re.I)
# Emoji and pictographs: shown on screen as the scene picture, never read aloud.
_EMOJI = re.compile("[🀀-🫿☀-➿️‍]+")
_OPTION_LETTER = re.compile(r"^\s*(?:\(?[A-Da-d]\)|[A-Da-d][.):]|[A-Da-d]\s)\s*")
# Scenes the model adds for the quiz itself (the quiz is shown separately).
_QUIZ_SCENE = re.compile(r"quiz|question time|प्रश्न\s*(?:और|एवं)\s*उत्तर|प्रश्नोत्तरी|अभ्यास\s*प्रश्न", re.I)


def _clean(text: str, limit: int) -> str:
    text = _CITES.sub("", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?।])\s+", re.sub(r"\s+", " ", text).strip())
    return [p.strip() for p in parts if len(p.strip()) > 12]


def normalise(data: dict) -> tuple[str, list[dict], list[dict]]:
    """Keep only well-formed scenes and quiz items, trimmed to safe sizes."""
    scenes = []
    for i, sc in enumerate((data or {}).get("scenes") or []):
        if not isinstance(sc, dict):
            continue
        narration = _clean(_EMOJI.sub(" ", str(sc.get("narration") or "")), 700)
        heading = _clean(_EMOJI.sub(" ", str(sc.get("heading") or "")), 90)
        if len(narration) < 20 or not heading or _QUIZ_SCENE.search(heading):
            continue
        points = [_clean(_EMOJI.sub(" ", p), 110) for p in (sc.get("points") or [])
                  if isinstance(p, str) and _clean(_EMOJI.sub(" ", p), 110)][:4]
        raw = sc.get("visual") if isinstance(sc.get("visual"), str) else ""
        visual = raw.strip() if raw.strip() and len(raw.strip()) <= 4 else VISUALS[i % len(VISUALS)]
        scenes.append({"heading": heading, "narration": narration, "points": points, "visual": visual})
    quiz = []
    for q in (data or {}).get("quiz") or []:
        try:
            raw = [str(o) for o in q["options"]][:4]
            lettered = len(raw) == 4 and all(re.match(rf"\s*\(?{L}[\s.):]", o, re.I) for L, o in zip("ABCD", raw))
            opts = [_clean(_OPTION_LETTER.sub("", o) if lettered else o, 120) for o in raw]
            ai = int(q["answer_index"])
        except (KeyError, TypeError, ValueError):
            continue
        if len(opts) == 4 and all(opts) and 0 <= ai < 4 and _clean(q.get("question"), 200):
            quiz.append({"question": _clean(q["question"], 200), "options": opts, "answer_index": ai,
                         "explanation": _clean(q.get("explanation"), 200)})
    return _clean((data or {}).get("title"), 150), scenes[:MAX_SCENES], quiz[:3]


def _from_passages(topic: str, hits, language: str) -> tuple[str, list[dict]]:
    """No model available: build the lesson from the textbook passages themselves."""
    hi = language == "hi"
    scenes = [{"heading": topic, "visual": "📘", "points": [],
               "narration": (f"आज हम पढ़ेंगे: {topic}। ध्यान से देखिए और सुनिए।" if hi
                             else f"Today we will learn about {topic}. Watch and listen carefully.")}]
    for i, h in enumerate(hits[:4]):
        sents = _sentences(h.text)
        if not sents:
            continue
        chapter = h.citation.get("chapter") or h.citation.get("document")
        scenes.append({"heading": _clean(chapter, 90) or topic, "visual": VISUALS[(i + 1) % len(VISUALS)],
                       "narration": _clean(" ".join(sents[:3]), 700), "points": [_clean(s, 110) for s in sents[:3]]})
    scenes.append({"heading": "दोहराएँ" if hi else "Let us revise", "visual": "✅", "points": [],
                   "narration": ("अब अपनी पाठ्यपुस्तक में यही भाग खोलें और नीचे दिए प्रश्न हल करें।" if hi
                                 else "Now open the same pages in your textbook and answer the questions below.")})
    return topic, scenes


def generate(db: Session, *, cs, subject, topic: str, language: str, reason: str, created_by: int) -> VideoLesson:
    lang = gyan.LANG.get(language, "English")
    hits, supported = retrieval.search(db, topic, grade=cs.grade, subject_id=subject.id, k=4)
    hits = hits if supported else []
    sources = [{**gyan._cite(h), "ref": f"S{i}"} for i, h in enumerate(hits, start=1)]
    v = VideoLesson(class_section_id=cs.id, subject_id=subject.id, topic=topic[:160], language=language,
                    reason=reason, sources=sources, created_by=created_by, status="draft")
    if not hits:
        v.title = topic
        v.scenes = []
        v.note = "No approved textbook passage matches this topic, so no lesson was made. Try the chapter name."
        return v
    prompt = (f"{gyan._sources_block(hits)}\n\nWrite the script of a short video lesson in {lang} for Class {cs.grade} "
              f"{subject.name} students on '{topic}', using only these passages. 5 to 6 scenes: an engaging opening, "
              "clear explanation in small steps, one worked example from daily life in Chhattisgarh, a recap. "
              "Each scene: heading (max 8 words), narration (2-4 short sentences the narrator will speak, simple words "
              "for children), points (2-3 short on-screen bullets), visual (one emoji). Then a quiz of 3 multiple-choice "
              "questions with 4 options each and a 0-based answer_index. Return JSON only.")
    try:
        res = get_runtime().generate([{"role": "system", "content": gyan.TEACHER_SYSTEM},
                                      {"role": "user", "content": prompt}],
                                     max_tokens=1800, temperature=0.3, schema=SCENE_SCHEMA)
        title, scenes, quiz = normalise(res.data or {})
        if len(scenes) < 3:
            raise SLMUnavailable("The model's script was incomplete")
        coverage, _ = gyan._grounding(" ".join(s["narration"] for s in scenes), hits)
        v.title, v.scenes, v.quiz = title or topic, scenes, quiz
        v.ai_generated, v.model, v.grounding = True, res.model, round(coverage, 3)
        if coverage < gyan.GROUNDING_MIN:
            v.note = (f"Only {round(coverage * 100)}% of the narration's words appear in the textbook passages. "
                      "Check every scene before publishing.")
        else:
            v.note = "AI draft: check each scene against the textbook before publishing."
    except SLMUnavailable as exc:
        v.title, v.scenes = _from_passages(topic, hits, language)
        v.quiz = []
        v.ai_generated, v.model = False, "textbook-passages"
        v.note = f"Built from the textbook passages (AI model not available: {exc}). Edit the narration if needed."
    return v


def lesson_dict(v: VideoLesson, *, subject=None, cs=None, for_student: bool = False, watched: int | None = None) -> dict:
    d = {"id": v.id, "title": v.title, "topic": v.topic, "language": v.language, "scenes": v.scenes,
         "quiz": v.quiz, "sources": v.sources, "status": v.status, "reason": v.reason,
         "ai_generated": v.ai_generated, "model": v.model, "note": v.note, "grounding": v.grounding,
         "subject": subject.name if subject else None, "subject_hi": subject.name_hi if subject else None,
         "class": cs.label if cs else None, "class_id": v.class_section_id, "subject_id": v.subject_id,
         "created_at": v.created_at.isoformat() + "Z" if v.created_at else None,
         "published_at": v.published_at.isoformat() + "Z" if v.published_at else None,
         "minutes": max(1, round(sum(len(s["narration"]) for s in v.scenes) / 800 + len(v.scenes) * 0.15)),
         "is_demo": v.is_demo}
    if watched is not None:
        d["watched_by"] = watched
    if for_student:
        d.pop("note", None)
        d.pop("grounding", None)
    return d


def publish(v: VideoLesson, user_id: int) -> None:
    v.status, v.published_by, v.published_at = "published", user_id, utcnow()
