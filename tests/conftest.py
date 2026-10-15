import os
import tempfile

# Configure an isolated database BEFORE the app (and its settings) are imported.
_tmp = tempfile.mkdtemp(prefix="hs-test-")
os.environ["HS_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["HS_ENVIRONMENT"] = "test"
os.environ["HS_ALLOW_DEMO_DATA"] = "true"
os.environ["HS_IP_MAX_ATTEMPTS"] = "100000"
os.environ["HS_SLM_RUNTIME"] = "none"          # tests use a fake runtime unless marked `slm`
os.environ["HS_EMBEDDING_MODEL"] = ""          # keyword retrieval: fast and deterministic
os.environ["HS_STT_MODEL"] = ""                # voice input off unless a test enables it
os.environ["HS_DEMO_SCALE"] = "compact"        # 33 districts, but two classes per school
os.environ["HS_KB_DIR"] = f"{_tmp}/kb"
os.environ.pop("HS_ANTHROPIC_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database  # noqa: E402
from app.demo_seed import DEMO_PASSWORDS, seed_demo  # noqa: E402
from app.main import app  # noqa: E402
from app.slm import runtime as slm_runtime  # noqa: E402

CREDS = {
    "state": ("admin", "state.admin", DEMO_PASSWORDS["state"]),
    "district_north": ("admin", "district.raipur", DEMO_PASSWORDS["district"]),  # Raipur (2291)
    "district_south": ("admin", "district.durg", DEMO_PASSWORDS["district"]),    # Durg (2292)
    "block_amla": ("admin", "block.dharsiwa", DEMO_PASSWORDS["block"]),          # Dharsiwa block (229101)
    "head_teacher": ("teacher", "DEMO-T-001", DEMO_PASSWORDS["teacher"]),
    "math_teacher": ("teacher", "DEMO-T-002", DEMO_PASSWORDS["teacher"]),
    "other_teacher": ("teacher", "DEMO-T-005", DEMO_PASSWORDS["teacher"]),  # different school
    "student5": ("student", "st-demo01", DEMO_PASSWORDS["student"]),
    "student8": ("student", "st-demo02", DEMO_PASSWORDS["student"]),
}


class Client(TestClient):
    """TestClient that sends the CSRF header like the browser code does."""

    send_csrf = True

    def request(self, method, url, *args, **kwargs):
        if method.upper() not in ("GET", "HEAD", "OPTIONS") and self.send_csrf:
            headers = dict(kwargs.pop("headers", None) or {})
            token = self.cookies.get("hs_csrf")
            if token:
                headers.setdefault("X-CSRF-Token", token)
            kwargs["headers"] = headers
        return super().request(method, url, *args, **kwargs)


@pytest.fixture(scope="session", autouse=True)
def seeded():
    database.init_db()
    with database.SessionLocal() as db:
        seed_demo(db)
    yield


def make_client() -> Client:
    return Client(app, base_url="http://testserver")


def login(who: str) -> Client:
    portal, login_id, password = CREDS[who]
    c = make_client()
    r = c.post(f"/api/auth/{portal}/login", json={"login_id": login_id, "password": password})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def as_():
    """as_('state') -> signed-in client."""
    return login


@pytest.fixture
def anon():
    return make_client()


@pytest.fixture
def db():
    s = database.SessionLocal()
    yield s
    s.close()


class FakeSLM:
    """Deterministic stand-in for the Gyan SLM runtime.

    mode="grounded": answers by quoting the first source sentence with a [S1] citation.
    mode="ungrounded": answers with text unrelated to the sources (must be rejected).
    mode="not_found": replies NOT_FOUND.
    """

    name = "fake"

    def __init__(self, mode="grounded"):
        self.mode = mode
        self.calls = []

    def generate(self, messages, *, max_tokens, temperature, schema=None, model=None):
        import re

        user = messages[-1]["content"]
        self.calls.append({"system": messages[0]["content"], "prompt": user, "schema": schema})
        data = None
        if schema is not None:
            data = {"questions": [
                {"text": "Which is bigger, 1/3 or 1/5?", "options": ["1/3", "1/5", "Equal", "Cannot say"],
                 "answer_index": 0, "explanation": "Fewer parts means bigger parts."},
                {"text": "bad", "options": ["only one"], "answer_index": 0},  # malformed: dropped
            ]}
            text = "{}"
        elif self.mode == "not_found":
            text = "NOT_FOUND"
        elif self.mode == "ungrounded":
            text = "The Eiffel Tower is in Paris and was built for a world exhibition by engineers."
        elif self.mode == "cited_hallucination":
            # Real failure seen in eval: off-syllabus knowledge with a citation to an unrelated page.
            text = ("The Pythagoras theorem states that in a right-angled triangle the square of the "
                    "hypotenuse equals the sum of the squares of the other two sides. [S1]")
        else:
            m = re.search(r'<source id="S1"[^>]*>\n(.*?)\n</source>', user, re.S)
            first = (m.group(1) if m else "").split(". ")[0]
            text = f"{first}. [S1]"
        return slm_runtime.GenResult(text=text, model="fake-slm", runtime="fake", latency_ms=5, data=data,
                                     completion_tokens=10)

    def health(self):
        return {"ok": True, "runtime": "fake", "model": "fake-slm"}


@pytest.fixture
def fake_slm():
    fake = FakeSLM()
    slm_runtime.set_runtime(fake)
    yield fake
    slm_runtime.set_runtime(None)
