"""Phase 5 / item 9 — container hygiene (static checks; the live `docker compose` run is in the regression script)."""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


def _lines(p: Path):
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]


def test_dockerignore_keeps_secrets_and_junk_out_of_the_image():
    path = BACKEND / ".dockerignore"
    assert path.exists(), "without a .dockerignore, `COPY . .` bakes .env (all secrets) and .venv into the image"
    rules = _lines(path)
    for must in (".env", ".venv", "tests", "__pycache__", ".pytest_cache", ".git"):
        assert any(r.strip("/*") == must or r.startswith(must) or r.endswith(must) for r in rules), f".dockerignore must exclude {must}"
    assert not any(r.startswith("!.env") and r != "!.env.example" for r in rules)


def test_dockerfile_runs_unprivileged_and_declares_a_healthcheck():
    text = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^USER\s+(?!root)\S+", text, flags=re.M)
    assert "HEALTHCHECK" in text and "/api/health" in text
    assert "shipora_secret" not in text and "JWT_SECRET" not in text      # secrets are injected at run time, never built in


def test_dockerfile_has_no_literal_backslash_n_sequences():
    # Found by the first real `docker compose build`: a literal "\n" where a "\" line continuation was meant
    # made `HEALTHCHECK ... \n  CMD ...` fail to parse, and the grep-style checks above could not see it.
    text = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "\\n" not in text, "a literal backslash-n in the Dockerfile is almost certainly a broken line continuation"


def test_compose_has_health_checks_and_no_inline_secrets():
    text = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert text.count("healthcheck:") >= 2                                # mongo and backend
    assert re.search(r"depends_on:\s*\n\s+mongo:\s*\n\s+condition:\s*service_healthy", text)
    assert "JWT_SECRET" not in text and "mongodb+srv" not in text         # comes from env_file only
    assert "27017:27017" not in text                                      # the database is not published to the host
    assert "MONGO_URI: mongodb://mongo:27017" in text                    # the container talks to its own database service
