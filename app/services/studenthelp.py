"""Student self-improvement and peer help.

Helping themselves:
- goals: weekly targets the student sets; progress is counted from the learner record
- revision: a "my mistakes" deck re-asked on a 1/3/7-day schedule until mastered
- library: the class's approved textbooks, chapter by chapter
- level and streak: earned from learning activity (attendance does not count)

Help from others:
- doubts: ask the teacher privately, or ask the class doubt board where classmates
  answer; the teacher can see, answer, hide and mark answers helpful
- study buddies: pairs set up by the teacher (a classmate strong in a topic helps
  one who is still practising it); suggestions are computed from mastery

Child safety: posts are screened (wellbeing, personal information, links,
abusive words) before anyone else sees them; classmates see first names only;
the teacher moderates; there are no private student-to-student messages.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Assessment,
    AssessmentResult,
    ClassSection,
    CurriculumChunk,
    CurriculumDocument,
    Doubt,
    DoubtReply,
    LearnerEvent,
    LearningProgress,
    RevisionItem,
    StudentEnrollment,
    StudentGoal,
    StudyPair,
    Subject,
    User,
    utcnow,
)
from app.services import content, learner

# ------------------------------------------------------------ level & streak --

XP = {"assessment_result": 10, "activity_completion": 10, "lesson_completed": 5, "chapter_read": 5,
      "revision_review": 3, "peer_help": 15}
LEVELS = [(0, "Beginner", "शुरुआत"), (60, "Explorer", "खोजी"), (150, "Learner", "सीखने वाला"),
          (300, "Achiever", "उपलब्धि"), (500, "Star", "सितारा"), (800, "Champion", "चैंपियन"),
          (1200, "Guru", "गुरु")]


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def level_and_streak(db: Session, student_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    counts = dict(db.execute(select(LearnerEvent.event_type, func.count()).where(
        LearnerEvent.student_user_id == student_id, LearnerEvent.event_type.in_(list(XP)))
        .group_by(LearnerEvent.event_type)).all())
    xp = sum(XP[k] * n for k, n in counts.items())
    idx = max(i for i, (lo, _, _) in enumerate(LEVELS) if xp >= lo)
    nxt = LEVELS[idx + 1][0] if idx + 1 < len(LEVELS) else None
    days = {d.date() if isinstance(d, datetime) else d for d in db.scalars(
        select(LearnerEvent.occurred_at).where(LearnerEvent.student_user_id == student_id,
                                               LearnerEvent.event_type.in_(list(XP)),
                                               LearnerEvent.occurred_at >= datetime.combine(today - timedelta(days=60),
                                                                                           datetime.min.time())))}
    streak, d = 0, today if today in days else today - timedelta(days=1)
    while d in days:
        streak += 1
        d -= timedelta(days=1)
    return {"xp": xp, "level": idx + 1, "level_name": LEVELS[idx][1], "level_name_hi": LEVELS[idx][2],
            "next_level_xp": nxt, "level_floor_xp": LEVELS[idx][0], "streak_days": streak,
            "active_today": today in days, "breakdown": counts,
            "how": "XP: quiz or practice 10, lesson 5, textbook chapter 5, revision answer 3, accepted help to a classmate 15."}


# --------------------------------------------------------------------- goals --

GOAL_KINDS = {
    "practice": ("activity_completion", "Practice sets", "अभ्यास सेट"),
    "lessons": ("lesson_completed", "Lessons read", "पढ़े गए पाठ"),
    "chapters": ("chapter_read", "Textbook chapters", "पाठ्यपुस्तक अध्याय"),
    "revision": ("revision_review", "Mistakes fixed", "सुधारी गई गलतियाँ"),
    "helping": ("peer_help", "Classmates helped", "सहपाठियों की मदद"),
    "custom": (None, "My own goal", "मेरा लक्ष्य"),
}
MAX_ACTIVE_GOALS = 6


def goal_progress(db: Session, g: StudentGoal) -> int:
    event_type = GOAL_KINDS[g.kind][0]
    if event_type is None:
        return g.manual_progress
    start = datetime.combine(g.week_start, datetime.min.time())
    where = (LearnerEvent.student_user_id == g.student_user_id, LearnerEvent.event_type == event_type,
             LearnerEvent.occurred_at >= start, LearnerEvent.occurred_at < start + timedelta(days=7))
    if g.kind == "revision":  # only correct answers count as a fixed mistake
        return sum(1 for p in db.scalars(select(LearnerEvent.payload).where(*where)) if p.get("correct"))
    return db.scalar(select(func.count(LearnerEvent.id)).where(*where)) or 0


def goal_dict(db: Session, g: StudentGoal) -> dict:
    done = goal_progress(db, g)
    return {"id": g.id, "kind": g.kind, "title": g.title, "target": g.target, "progress": min(done, g.target),
            "done": done >= g.target, "week_start": g.week_start.isoformat(), "manual": g.kind == "custom",
            "kind_label": GOAL_KINDS[g.kind][1], "kind_label_hi": GOAL_KINDS[g.kind][2]}


def create_goal(db: Session, student_id: int, kind: str, title: str, target: int, today: date | None = None) -> StudentGoal:
    today = today or date.today()
    active = db.scalar(select(func.count(StudentGoal.id)).where(
        StudentGoal.student_user_id == student_id, StudentGoal.status == "active",
        StudentGoal.week_start == week_start(today))) or 0
    if active >= MAX_ACTIVE_GOALS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"You already have {MAX_ACTIVE_GOALS} goals this week")
    check_post(title)
    g = StudentGoal(student_user_id=student_id, kind=kind, title=title.strip()[:140] or GOAL_KINDS[kind][1],
                    target=target, week_start=week_start(today))
    db.add(g)
    db.flush()
    return g


# ------------------------------------------------------------------ revision --

INTERVALS = {0: 1, 1: 3, 2: 7}  # correct streak -> days until the next review
MASTERED_AFTER = 2


def capture_mistakes(db: Session, r: AssessmentResult) -> int:
    """Add wrongly answered multiple-choice questions to the student's deck."""
    a: Assessment = r.assessment
    by_id = {q.get("id"): q for q in (a.questions or [])}
    n = 0
    for item in r.item_results or []:
        q = by_id.get(item.get("id"))
        if not q or item.get("method") != "mcq" or item.get("score", 0) >= item.get("max", 1) or not q.get("options"):
            continue
        key = f"assessment:{a.id}:{q['id']}"
        row = db.scalar(select(RevisionItem).where(RevisionItem.student_user_id == r.student_user_id,
                                                   RevisionItem.item_key == key))
        if row is None:
            db.add(RevisionItem(student_user_id=r.student_user_id, item_key=key, subject_id=a.subject_id,
                                topic=q.get("topic") or a.topic or "", next_review=date.today(),
                                question={"text": q["text"], "options": q["options"],
                                          "answer_index": q["answer_index"]}))
        else:
            row.times_wrong += 1
            row.correct_streak, row.mastered, row.next_review = 0, False, date.today()
        n += 1
    db.flush()
    return n


def revision_summary(db: Session, student_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    rows = db.scalars(select(RevisionItem).where(RevisionItem.student_user_id == student_id)).all()
    due = [r for r in rows if not r.mastered and r.next_review <= today]
    by_topic = Counter(r.topic for r in rows if not r.mastered)
    return {"due": len(due), "open": sum(1 for r in rows if not r.mastered), "mastered": sum(1 for r in rows if r.mastered),
            "topics": [{"topic": t, "open": n} for t, n in by_topic.most_common(6)]}


def due_items(db: Session, student_id: int, limit: int = 5, today: date | None = None) -> list[RevisionItem]:
    today = today or date.today()
    return list(db.scalars(select(RevisionItem).where(
        RevisionItem.student_user_id == student_id, RevisionItem.mastered.is_(False),
        RevisionItem.next_review <= today).order_by(RevisionItem.next_review, RevisionItem.id).limit(limit)))


def answer_revision(db: Session, student_id: int, item_id: int, choice: int, today: date | None = None) -> dict:
    today = today or date.today()
    row = db.get(RevisionItem, item_id)
    if row is None or row.student_user_id != student_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    correct = choice == row.question.get("answer_index")
    if correct:
        row.correct_streak += 1
        row.mastered = row.correct_streak >= MASTERED_AFTER
        row.next_review = today + timedelta(days=INTERVALS.get(row.correct_streak, 7))
    else:
        row.times_wrong += 1
        row.correct_streak, row.next_review = 0, today + timedelta(days=1)
    row.last_reviewed_at = utcnow()
    learner.record_event(db, student_id=student_id, event_type="revision_review",
                         payload={"item_id": row.id, "topic": row.topic, "correct": correct, "mastered": row.mastered,
                                  "summary": f"Revision ({row.topic}): {'correct' if correct else 'try again'}"})
    return {"correct": correct, "correct_index": row.question.get("answer_index"), "mastered": row.mastered,
            "next_review": row.next_review.isoformat(), "correct_streak": row.correct_streak}


# ------------------------------------------------------------------- library --

PAGES_PER_SECTION = 8


def library(db: Session, grade: int, subject_ids: list[int]) -> list[dict]:
    docs = db.scalars(select(CurriculumDocument).where(
        CurriculumDocument.approval_status == "approved", CurriculumDocument.grade == grade,
        CurriculumDocument.subject_id.in_(subject_ids or [-1])).order_by(CurriculumDocument.is_demo,
                                                                         CurriculumDocument.title)).all()
    out = []
    for d in docs:
        out.append({"id": d.id, "title": d.title, "subject_id": d.subject_id, "language": d.language,
                    "publisher": d.publisher, "is_demo": d.is_demo, "pages": d.pages,
                    "sections": _sections(db, d.id)})
    return out


def _sections(db: Session, doc_id: int) -> list[dict]:
    """Chapters where the book has them; otherwise page ranges."""
    rows = db.execute(select(CurriculumChunk.chapter, func.min(CurriculumChunk.page), func.max(CurriculumChunk.page),
                             func.count(CurriculumChunk.id), func.min(CurriculumChunk.seq))
                      .where(CurriculumChunk.document_id == doc_id).group_by(CurriculumChunk.chapter)
                      .order_by(func.min(CurriculumChunk.seq))).all()
    named = [r for r in rows if r[0]]
    if len(named) >= 2:
        return [{"key": f"c:{r[0]}", "title": r[0], "pages": f"{r[1]}-{r[2]}", "passages": r[3]} for r in named]
    lo, hi = db.execute(select(func.min(CurriculumChunk.page), func.max(CurriculumChunk.page))
                        .where(CurriculumChunk.document_id == doc_id)).one()
    if lo is None:
        return []
    return [{"key": f"p:{p}", "title": f"Pages {p}-{min(p + PAGES_PER_SECTION - 1, hi)}",
             "pages": f"{p}-{min(p + PAGES_PER_SECTION - 1, hi)}", "passages": None}
            for p in range(lo, hi + 1, PAGES_PER_SECTION)]


def read_section(db: Session, doc: CurriculumDocument, key: str) -> list[dict]:
    stmt = select(CurriculumChunk).where(CurriculumChunk.document_id == doc.id)
    if key.startswith("c:"):
        stmt = stmt.where(CurriculumChunk.chapter == key[2:])
    elif key.startswith("p:") and key[2:].isdigit():
        p = int(key[2:])
        stmt = stmt.where(CurriculumChunk.page >= p, CurriculumChunk.page < p + PAGES_PER_SECTION)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown section")
    return [{"page": c.page, "text": c.text} for c in db.scalars(stmt.order_by(CurriculumChunk.seq).limit(80))]


def sections_read(db: Session, student_id: int) -> set[str]:
    return {f"{p.get('document_id')}|{p.get('section')}" for p in db.scalars(select(LearnerEvent.payload).where(
        LearnerEvent.student_user_id == student_id, LearnerEvent.event_type == "chapter_read"))}


# -------------------------------------------------------------- safety screen --

_PHONE = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b")
_LINK = re.compile(r"https?://|www\.|\.com\b|whatsapp|instagram|facebook|telegram|snapchat", re.I)
_ABUSE = re.compile(r"\b(idiot|stupid|fool|shut up|hate you|loser|dumb)\b|पागल|बेवकूफ|गधा|मूर्ख|चुप कर", re.I)


class PostRejected(HTTPException):
    def __init__(self, message: str, reason: str):
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": message, "reason": reason})


def check_post(text: str) -> None:
    """Raise if a student post must not be shown to others."""
    if content._WELLBEING.search(text):
        raise PostRejected(content.WELLBEING_REPLY["en"] + " / " + content.WELLBEING_REPLY["hi"], "wellbeing")
    if _PHONE.search(text) or _LINK.search(text) or content._PRIVACY.search(text):
        raise PostRejected("Please do not share phone numbers, links, passwords or anyone's personal details. "
                           "कृपया फ़ोन नंबर, लिंक, पासवर्ड या किसी की निजी जानकारी साझा न करें।", "privacy")
    if _ABUSE.search(text):
        raise PostRejected("Please write kindly. Unkind words are not allowed. "
                           "कृपया अच्छे शब्दों में लिखें।", "abuse")


# -------------------------------------------------------------------- doubts --

def display_name(u: User) -> str:
    parts = (u.full_name or "").split()
    return parts[0] if parts else "Student"


def doubt_dict(db: Session, d: Doubt, viewer_id: int, *, teacher_view: bool) -> dict:
    replies = db.scalars(select(DoubtReply).where(DoubtReply.doubt_id == d.id).order_by(DoubtReply.created_at)).all()
    asker = db.get(User, d.student_user_id)
    subj = db.get(Subject, d.subject_id) if d.subject_id else None
    out_replies = []
    for r in replies:
        if r.hidden and not teacher_view:
            continue
        author = db.get(User, r.author_user_id)
        out_replies.append({"id": r.id, "body": r.body, "role": r.author_role, "accepted": r.accepted,
                            "hidden": r.hidden, "reported": r.reported if teacher_view else None,
                            "mine": r.author_user_id == viewer_id,
                            "author": (author.full_name if teacher_view else
                                       ("Teacher" if r.author_role == "teacher" else display_name(author))),
                            "created_at": r.created_at.isoformat() + "Z"})
    return {"id": d.id, "audience": d.audience, "topic": d.topic, "body": d.body, "status": d.status,
            "subject": subj.name if subj else None, "subject_hi": subj.name_hi if subj else None,
            "asker": asker.full_name if teacher_view else display_name(asker), "mine": d.student_user_id == viewer_id,
            "asker_public_id": asker.public_id if teacher_view else None,
            "created_at": d.created_at.isoformat() + "Z", "replies": out_replies, "is_demo": d.is_demo}


def student_doubts(db: Session, student_id: int, class_id: int) -> list[Doubt]:
    """Own doubts (any audience) + the class board (open/answered, not hidden)."""
    return list(db.scalars(select(Doubt).where(
        Doubt.class_section_id == class_id,
        ((Doubt.student_user_id == student_id) | ((Doubt.audience == "class") & (Doubt.status != "hidden"))))
        .order_by(Doubt.created_at.desc()).limit(60)))


def accept_reply(db: Session, reply: DoubtReply, by_user: int) -> None:
    if reply.accepted or reply.hidden:
        return
    reply.accepted = True
    d = db.get(Doubt, reply.doubt_id)
    d.status = "answered"
    if reply.author_role == "student" and reply.author_user_id != d.student_user_id:
        learner.record_event(db, student_id=reply.author_user_id, event_type="peer_help", recorded_by=by_user,
                             event_uid=f"peer-help-{reply.id}",
                             payload={"doubt_id": d.id, "reply_id": reply.id, "topic": d.topic,
                                      "summary": f"Helped a classmate ({d.topic or 'doubt'})"})


# --------------------------------------------------------------- study pairs --

def pair_suggestions(db: Session, cs: ClassSection, *, helper_min: float = 0.8, learner_max: float = 0.55,
                     min_attempts: int = 3, limit: int = 10) -> list[dict]:
    """Per topic: classmates with high mastery paired with classmates still practising it."""
    ids = list(db.scalars(select(StudentEnrollment.student_user_id).where(
        StudentEnrollment.class_section_id == cs.id, StudentEnrollment.active.is_(True))))
    busy = {(p.helper_user_id, p.topic) for p in db.scalars(select(StudyPair).where(
        StudyPair.class_section_id == cs.id, StudyPair.status == "active"))}
    busy |= {(p.learner_user_id, p.topic) for p in db.scalars(select(StudyPair).where(
        StudyPair.class_section_id == cs.id, StudyPair.status == "active"))}
    rows = db.scalars(select(LearningProgress).where(LearningProgress.student_user_id.in_(ids or [-1]),
                                                     LearningProgress.attempted >= min_attempts)).all()
    by_topic: dict[tuple[int, str], list[LearningProgress]] = defaultdict(list)
    for r in rows:
        by_topic[(r.subject_id, r.topic)].append(r)
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids or [-1])))}
    # Candidate pairs, neediest learners first; each student is suggested at most once.
    candidates = []
    for (subj_id, topic), progs in by_topic.items():
        helpers = [p for p in progs if p.mastery >= helper_min and (p.student_user_id, topic) not in busy]
        for l in (p for p in progs if p.mastery < learner_max and (p.student_user_id, topic) not in busy):
            for h in helpers:
                candidates.append((l.mastery, -h.mastery, subj_id, topic, h, l))
    out, used = [], set()
    for _, _, subj_id, topic, h, l in sorted(candidates, key=lambda c: (c[0], c[1])):
        if h.student_user_id in used or l.student_user_id in used:
            continue
        used |= {h.student_user_id, l.student_user_id}
        out.append({"subject_id": subj_id, "topic": topic,
                    "helper": {"public_id": users[h.student_user_id].public_id,
                               "name": users[h.student_user_id].full_name, "mastery": round(h.mastery, 2)},
                    "learner": {"public_id": users[l.student_user_id].public_id,
                                "name": users[l.student_user_id].full_name, "mastery": round(l.mastery, 2)}})
        if len(out) >= limit:
            break
    return out


def my_pairs(db: Session, student_id: int) -> list[dict]:
    rows = db.scalars(select(StudyPair).where(
        StudyPair.status == "active",
        (StudyPair.helper_user_id == student_id) | (StudyPair.learner_user_id == student_id))).all()
    out = []
    for p in rows:
        helping = p.helper_user_id == student_id
        partner = db.get(User, p.learner_user_id if helping else p.helper_user_id)
        subj = db.get(Subject, p.subject_id) if p.subject_id else None
        out.append({"id": p.id, "topic": p.topic, "role": "helper" if helping else "learner",
                    "partner": display_name(partner), "note": p.note,
                    "subject": subj.name if subj else None, "subject_hi": subj.name_hi if subj else None})
    return out
