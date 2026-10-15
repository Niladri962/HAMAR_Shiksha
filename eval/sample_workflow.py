"""End-to-end sample workflow against the real API and the real local SLM.

Runs on a throw-away database seeded with demo data and writes a transcript
(docs/SAMPLE_WORKFLOW.md) of what each step actually returned.

    python -m eval.sample_workflow --model gemma2:2b [--embedding BAAI/bge-m3]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma2:2b")
    ap.add_argument("--embedding", default="")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="hs-sample-")
    os.environ.update({"HS_DATABASE_URL": f"sqlite:///{tmp}/s.db", "HS_ENVIRONMENT": "test", "HS_SLM_RUNTIME": "ollama",
                       "HS_SLM_MODEL": a.model, "HS_EMBEDDING_MODEL": a.embedding, "HS_KB_DIR": str(ROOT / "data" / "kb-eval"),
                       "HS_IP_MAX_ATTEMPTS": "100000", "USE_TF": "0", "HF_HUB_OFFLINE": "1"})
    from fastapi.testclient import TestClient

    from app import database
    from app.demo_seed import DEMO_PASSWORDS, seed_demo
    from app.main import app

    database.init_db()
    with database.SessionLocal() as db:
        seed_demo(db)

    log: list[str] = [f"# Sample curriculum-grounded workflow (real run)", "",
                      f"- Date: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
                      f"- Gyan SLM: `{a.model}` via local Ollama · retrieval: {a.embedding or 'BM25 keyword'}",
                      "- Data: demonstration seed + demo primers (**not SCERT material**).",
                      "- Every block below is the actual API response from this run (trimmed for length).", ""]

    def client(portal, login_id, pw):
        c = TestClient(app, base_url="http://testserver")
        r = c.post(f"/api/auth/{portal}/login", json={"login_id": login_id, "password": pw})
        r.raise_for_status()
        c.headers["X-CSRF-Token"] = c.cookies.get("hs_csrf")
        return c

    def step(title, obj, keys=None):
        if keys:
            obj = {k: obj.get(k) for k in keys}
        txt = json.dumps(obj, ensure_ascii=False, indent=1)
        log.extend([f"## {title}", "", "```json", txt[:2500] + ("\n..." if len(txt) > 2500 else ""), "```", ""])
        print("✓", title)

    t = client("teacher", "DEMO-T-002", DEMO_PASSWORDS["teacher"])
    s = client("student", "st-demo01", DEMO_PASSWORDS["student"])
    adm = client("admin", "state.admin", DEMO_PASSWORDS["state"])
    me = t.get("/api/teacher/me").json()
    c5 = next(x for x in me["assignments"] if x["grade"] == 5 and x["subject_code"] == "MATH")["class_id"]

    plan = t.get("/api/teacher/saathi/plan", params={"class_id": c5, "subject_id": 3, "scope": "year"}).json()
    step("1. Teacher Saathi - academic plan summary (deterministic)", {"summary": plan["summary"],
         "first_milestones": plan["milestones"][:3]})
    los = t.get("/api/teacher/saathi/learning-outcomes", params={"subject_id": 3, "grade": 5}).json()
    frac = next(lo for lo in los if lo["topic"] == "Fractions")
    lp = t.post("/api/teacher/saathi/lesson-plans/generate", json={"class_id": c5, "subject_id": 3, "topic": "Fractions",
                                                                   "learning_outcome_id": frac["id"], "language": "hi",
                                                                   "minutes": 40}).json()
    step("2. Lesson plan drafted by Gyan SLM (Hindi), grounded in textbook pages", lp,
         ["status", "ai_generated", "model", "title", "body", "sources"])
    step("3. Teacher approves the plan", t.post(f"/api/teacher/saathi/lesson-plans/{lp['id']}/approve").json(), ["id", "status"])

    ws = t.post("/api/teacher/saathi/worksheet", json={"subject_id": 3, "grade": 5, "topic": "Fractions", "language": "en",
                                                       "count": 3}).json()
    step("4. Worksheet questions drafted (saved as DRAFT, invisible to students)", ws, ["drafts", "sources", "notice"])
    for q in ws["drafts"][:1]:
        t.post(f"/api/teacher/pariksha/bank/{q['id']}/approve")

    asm = t.post("/api/teacher/pariksha/assessments", json={"class_id": c5, "subject_id": 3, "title": "Fractions check",
                                                             "learning_outcome_ids": [frac["id"]], "qtypes": ["mcq", "short"],
                                                             "count": 5, "publish": True}).json()
    step("5. Pariksha builds an assessment from approved bank questions", asm)
    q = s.get(f"/api/student/assessments/{asm['id']}").json()
    answers = {i["id"]: (0 if i["qtype"] == "mcq" else "3 / 8 parts") for i in q["questions"]}
    ev = {"event_uid": uuid.uuid4().hex, "type": "assessment.submit", "created_at": datetime.now(timezone.utc).isoformat(),
          "payload": {"assessment_id": asm["id"], "answers": answers}}
    pushed = s.post("/api/sync/push", json={"device_uid": "sample-device-0001", "events": [ev, dict(ev)]}).json()
    step("6. Student answers offline; the queued event syncs (second copy is a duplicate)", pushed)
    rq = t.get("/api/teacher/pariksha/review-queue").json()
    step("7. Uncertain short answers wait for the teacher (not auto-marked)", rq[:2])
    for item in rq:
        t.post(f"/api/teacher/pariksha/results/{item['result_id']}/review", json={"marks": {item["item_id"]: 0}})
    rec = s.get("/api/student/record").json()
    step("8. Learner record: competency + events (same record used by all modules)",
         {"competencies": [c for c in rec["competencies"] if "MATH" in c["code"]][:3], "latest_events": rec["events"][:3]})
    pr = t.get("/api/teacher/priorities").json()
    step("9. Teacher's weekly priority list with evidence", {"week_of": pr["week_of"], "students": pr["students"][:2]})

    ans = s.post("/api/student/assistant", json={"question": "Which fraction is bigger, 1/3 or 1/5? Why?", "language": "en"}).json()
    step("10. AI Class tutor answer (Gyan SLM) with citations", ans, ["answer", "verified", "citations", "provider"])
    ans_hi = s.post("/api/student/assistant", json={"question": "भिन्न में अंश क्या बताता है?", "language": "hi"}).json()
    step("11. Hindi tutor answer", ans_hi, ["answer", "verified", "citations"])
    off = s.post("/api/student/assistant", json={"question": "Who is the captain of the Indian cricket team?"}).json()
    step("12. Off-syllabus question handled honestly", off, ["answer", "verified", "citations"])
    ask = t.post("/api/teacher/saathi/ask", json={"question": "How should I explain why 1/3 is bigger than 1/5?",
                                                  "grade": 5}).json()
    step("13. Teacher Saathi grounded Q&A", ask, ["answer", "verified", "citations", "model", "latency_ms"])

    ptl = adm.get("/api/admin/command/ptl").json()
    step("14. Command Centre - planned / taught / learned (computed from records)", {"total": ptl["total"], "rows": ptl["rows"][:2]})

    out = ROOT / "docs" / "SAMPLE_WORKFLOW.md"
    out.write_text("\n".join(log), encoding="utf-8")
    print("written", out)


if __name__ == "__main__":
    main()
