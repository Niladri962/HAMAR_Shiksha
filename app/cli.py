"""Operations CLI:  python -m app.cli <command> [options]"""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, or_, select

from app import database
from app.config import get_settings


def cmd_init_db(_):
    database.init_db()
    print("Database initialised.")


def cmd_seed_demo(_):
    from app.demo_seed import DEMO_PASSWORDS, seed_demo

    database.init_db()
    with database.SessionLocal() as db:
        result = seed_demo(db)
    print("Demo data:", result)
    print("\nDEMO ACCOUNTS (demonstration only):")
    print(f"  Admin   state.admin / {DEMO_PASSWORDS['state']}       (state)")
    print(f"  Admin   district.raipur / {DEMO_PASSWORDS['district']} (district; every district: district.<name>)")
    print(f"  Admin   block.dharsiwa / {DEMO_PASSWORDS['block']}    (block)")
    print(f"  Teacher DEMO-T-001 / {DEMO_PASSWORDS['teacher']}      (head teacher, showcase school, Raipur)")
    print(f"  Teacher DEMO-T-002 / {DEMO_PASSWORDS['teacher']}      (maths & science teacher)")
    print(f"  Student st-demo01 / {DEMO_PASSWORDS['student']}       (Class 5)")
    print(f"  Student st-demo02 / {DEMO_PASSWORDS['student']}       (Class 8)")
    print("  One teacher and one student per district: docs/DEMO_ACCOUNTS.md")


def cmd_create_state_admin(args):
    from app.models import STATE_ADMIN
    from app.security import new_totp_secret, password_problems, totp_uri
    from app.services.accounts import create_user

    database.init_db()
    pw = getpass.getpass("Password (min 12 chars): ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    problems = password_problems(pw, min_length=12)
    if problems:
        sys.exit("Password " + "; ".join(problems))
    with database.SessionLocal() as db:
        user, _ = create_user(db, login_id=args.login, full_name=args.name, role_name=STATE_ADMIN,
                              granted_by=None, email=args.email, password=pw)
        user.mfa_secret = new_totp_secret()
        user.mfa_enabled = True
        from app.audit import audit
        audit(db, "admin.bootstrapped", actor_role="cli", entity_type="user", entity_id=user.id)
        db.commit()
        print(f"State administrator '{user.login_id}' created with two-step verification.")
        print("Add this key to an authenticator app now (it will not be shown again):")
        print("  secret:", user.mfa_secret)
        print("  uri:   ", totp_uri(user.mfa_secret, user.login_id))


def cmd_import_registry(args):
    from app.audit import audit
    from app.registry import import_registry_csv

    database.init_db()
    text = Path(args.csv).read_text(encoding="utf-8-sig")
    with database.SessionLocal() as db:
        res = import_registry_csv(db, text, source=args.source, source_reference=args.reference, imported_by=None)
        audit(db, "registry.imported", actor_role="cli", source=args.source, source_reference=args.reference,
              created=res.created, updated=res.updated, rejected=len(res.rejected))
        db.commit()
    print(f"created={res.created} updated={res.updated} rejected={len(res.rejected)}")
    for r in res.rejected[:50]:
        print("  line", r["line"], r["code"], "; ".join(r["reasons"]))


def cmd_recompute(args):
    from app.services import analytics

    with database.SessionLocal() as db:
        n = analytics.recompute_snapshots(db, analytics.recent_periods(args.months))
        db.commit()
    print(f"{n} school-period snapshots recomputed.")


def cmd_refresh_insights(_):
    from app.models import School
    from app.services import insights

    with database.SessionLocal() as db:
        recs = insights.refresh_school_interventions(db, list(db.scalars(select(School).where(School.status == "active"))))
        expired = insights.expire_old(db)
        db.commit()
    print(f"{len(recs)} school recommendations refreshed; {expired} expired.")


def cmd_purge_retention(_):
    from app.models import AIInteraction, AuditLog, AuthSession, LoginAttempt, PasswordResetToken, utcnow

    s = get_settings()
    now = utcnow()
    with database.SessionLocal() as db:
        counts = {
            "ai_interactions": db.execute(delete(AIInteraction).where(
                AIInteraction.created_at < now - timedelta(days=s.retention_ai_interactions_days))).rowcount,
            "sessions": db.execute(delete(AuthSession).where(
                AuthSession.expires_at < now - timedelta(days=s.retention_sessions_days))).rowcount,
            "login_attempts": db.execute(delete(LoginAttempt).where(
                LoginAttempt.at < now - timedelta(days=s.retention_login_attempts_days))).rowcount,
            "reset_tokens": db.execute(delete(PasswordResetToken).where(
                PasswordResetToken.expires_at < now - timedelta(days=1))).rowcount,
            "audit_logs": db.execute(delete(AuditLog).where(
                AuditLog.at < now - timedelta(days=s.retention_audit_days))).rowcount,
        }
        db.commit()
    print("Purged:", counts)


def cmd_purge_demo(args):
    """Remove every demonstration row (users, schools, registry entries...)."""
    from app import models as m

    if not args.yes:
        sys.exit("This deletes all demo data. Re-run with --yes to confirm.")
    with database.SessionLocal() as db:
        users = list(db.scalars(select(m.User.id).where(m.User.is_demo.is_(True))))
        schools = list(db.scalars(select(m.School.id).where(m.School.is_demo.is_(True))))
        classes = list(db.scalars(select(m.ClassSection.id).where(m.ClassSection.school_id.in_(schools or [-1]))))
        assessments = list(db.scalars(select(m.Assessment.id).where(m.Assessment.class_section_id.in_(classes or [-1]))))
        assignments = list(db.scalars(select(m.Assignment.id).where(m.Assignment.class_section_id.in_(classes or [-1]))))
        u, c = users or [-1], classes or [-1]
        demo_docs = list(db.scalars(select(m.CurriculumDocument.id).where(m.CurriculumDocument.is_demo.is_(True))))
        demo_q = list(db.scalars(select(m.Question.id).where(m.Question.is_demo.is_(True))))
        demo_plans = list(db.scalars(select(m.LessonPlan.id).where(or_(m.LessonPlan.is_demo.is_(True),
                                                                        m.LessonPlan.class_section_id.in_(c)))))
        steps = [
            delete(m.SynchronizationEvent).where(m.SynchronizationEvent.user_id.in_(u)),
            delete(m.LearnerEvent).where(m.LearnerEvent.student_user_id.in_(u)),
            delete(m.LearnerCompetency).where(m.LearnerCompetency.student_user_id.in_(u)),
            delete(m.RemediationPlan).where(m.RemediationPlan.class_section_id.in_(c)),
            delete(m.ClassSession).where(m.ClassSession.class_section_id.in_(c)),
            delete(m.TeachingMilestone).where(m.TeachingMilestone.class_section_id.in_(c)),
            delete(m.LessonPlan).where(m.LessonPlan.id.in_(demo_plans or [-1])),
            delete(m.TrainingCompletion).where(m.TrainingCompletion.teacher_user_id.in_(u)),
            delete(m.TeacherTrainingModule).where(m.TeacherTrainingModule.is_demo.is_(True)),
            delete(m.AnswerKey).where(m.AnswerKey.question_id.in_(demo_q or [-1])),
            delete(m.Question).where(m.Question.id.in_(demo_q or [-1])),
            delete(m.LearningOutcome).where(m.LearningOutcome.is_demo.is_(True)),
            delete(m.CurriculumChunk).where(m.CurriculumChunk.document_id.in_(demo_docs or [-1])),
            delete(m.CurriculumDocument).where(m.CurriculumDocument.id.in_(demo_docs or [-1])),
            delete(m.AcademicCalendar).where(m.AcademicCalendar.is_demo.is_(True)),
            delete(m.DeviceRegistry).where(m.DeviceRegistry.school_id.in_(schools or [-1])),
            delete(m.AssessmentResult).where(m.AssessmentResult.assessment_id.in_(assessments or [-1])),
            delete(m.Assessment).where(m.Assessment.id.in_(assessments or [-1])),
            delete(m.AssignmentSubmission).where(m.AssignmentSubmission.assignment_id.in_(assignments or [-1])),
            delete(m.Assignment).where(m.Assignment.id.in_(assignments or [-1])),
            delete(m.AttendanceRecord).where(or_(m.AttendanceRecord.person_user_id.in_(u),
                                                 m.AttendanceRecord.school_id.in_(schools or [-1]))),
            delete(m.ActivityCompletion).where(m.ActivityCompletion.student_user_id.in_(u)),
            delete(m.LearningProgress).where(m.LearningProgress.student_user_id.in_(u)),
            delete(m.AIInteraction).where(m.AIInteraction.student_user_id.in_(u)),
            delete(m.AIRecommendation).where(m.AIRecommendation.is_demo.is_(True)),
            delete(m.LearningActivity).where(m.LearningActivity.is_demo.is_(True)),
            delete(m.TimetableSlot).where(m.TimetableSlot.class_section_id.in_(c)),
            delete(m.TeacherClassAssignment).where(m.TeacherClassAssignment.class_section_id.in_(c)),
            delete(m.StudentEnrollment).where(m.StudentEnrollment.class_section_id.in_(c)),
            delete(m.SchoolPerformanceSnapshot).where(m.SchoolPerformanceSnapshot.school_id.in_(schools or [-1])),
            delete(m.SchoolReport).where(m.SchoolReport.school_id.in_(schools or [-1])),
            delete(m.StudentProfile).where(m.StudentProfile.user_id.in_(u)),
            delete(m.TeacherProfile).where(m.TeacherProfile.user_id.in_(u)),
            delete(m.UserRoleAssignment).where(m.UserRoleAssignment.user_id.in_(u)),
            delete(m.AuthSession).where(m.AuthSession.user_id.in_(u)),
            delete(m.PasswordResetToken).where(m.PasswordResetToken.user_id.in_(u)),
            delete(m.ClassSection).where(m.ClassSection.id.in_(c)),
            delete(m.School).where(m.School.id.in_(schools or [-1])),
        ]
        for stmt in steps:
            db.execute(stmt)
        # Audit rows are kept but detached from deleted demo users.
        from sqlalchemy import update
        db.execute(update(m.AuditLog).where(m.AuditLog.actor_user_id.in_(u)).values(actor_user_id=None))
        db.execute(delete(m.User).where(m.User.id.in_(u)))
        db.execute(delete(m.SchoolCodeRegistry).where(m.SchoolCodeRegistry.is_demo.is_(True)))
        db.execute(delete(m.Block).where(m.Block.is_demo.is_(True)))
        db.execute(delete(m.District).where(m.District.is_demo.is_(True)))
        from app.audit import audit
        audit(db, "demo.purged", actor_role="cli", users=len(users), schools=len(schools))
        db.commit()
    print(f"Removed {len(users)} demo users and {len(schools)} demo schools.")


def cmd_ingest_curriculum(args):
    from app.audit import audit
    from app.kb import retrieval
    from app.kb.ingest import ingest_manifest

    database.init_db()
    with database.SessionLocal() as db:
        out = ingest_manifest(db, Path(args.manifest), workers=args.workers)
        audit(db, "kb.manifest_ingested", actor_role="cli", manifest=str(args.manifest), documents=out)
        db.commit()
        retrieval.search(db, "warm up index")  # builds the keyword index and, if configured, the vector cache
    for d in out:
        print(("ingested " if d["created"] else "already present ") + d["title"])


def cmd_slm_status(_):
    import json

    from app.slm import gyan

    print(json.dumps(gyan.status(), indent=2))


def cmd_schema_sql(_):
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    from app import models  # noqa: F401

    for table in database.Base.metadata.sorted_tables:
        print(str(CreateTable(table).compile(dialect=postgresql.dialect())).strip() + ";\n")
        for idx in table.indexes:
            print(str(CreateIndex(idx).compile(dialect=postgresql.dialect())).strip() + ";")
        print()


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.cli", description="HAMAR SHIKSHA operations")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    sub.add_parser("seed-demo", help="load clearly-marked demonstration data").set_defaults(fn=cmd_seed_demo)
    a = sub.add_parser("create-state-admin", help="bootstrap the first state administrator (with MFA)")
    a.add_argument("--login", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--email")
    a.set_defaults(fn=cmd_create_state_admin)
    r = sub.add_parser("import-registry", help="import an official UDISE+ CSV extract")
    r.add_argument("csv")
    r.add_argument("--source", required=True, help='e.g. "UDISE+ 2025-26"')
    r.add_argument("--reference", required=True, help="letter/file number authorising the import")
    r.set_defaults(fn=cmd_import_registry)
    rc = sub.add_parser("recompute-snapshots")
    rc.add_argument("--months", type=int, default=2)
    rc.set_defaults(fn=cmd_recompute)
    sub.add_parser("refresh-insights").set_defaults(fn=cmd_refresh_insights)
    sub.add_parser("purge-retention").set_defaults(fn=cmd_purge_retention)
    pd = sub.add_parser("purge-demo")
    pd.add_argument("--yes", action="store_true")
    pd.set_defaults(fn=cmd_purge_demo)
    ig = sub.add_parser("ingest-curriculum", help="ingest authorised curriculum documents from a manifest.json")
    ig.add_argument("manifest")
    ig.add_argument("--workers", type=int, default=4, help="parallel PDF extraction processes")
    ig.set_defaults(fn=cmd_ingest_curriculum)
    sub.add_parser("slm-status", help="show Gyan SLM runtime/model health").set_defaults(fn=cmd_slm_status)
    sub.add_parser("schema-sql", help="print PostgreSQL DDL").set_defaults(fn=cmd_schema_sql)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
