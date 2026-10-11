"""Documentation generated from the code must match the code: regenerate with the commands in each message."""

from io import StringIO
from pathlib import Path

from django.core.management import call_command

DOCS = Path(__file__).resolve().parents[2] / "docs"


def normalized(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def test_openapi_file_matches_the_api(tmp_path):
    target = tmp_path / "openapi.yaml"
    call_command("spectacular", file=str(target), stdout=StringIO(), stderr=StringIO())
    generated = normalized(target.read_text(encoding="utf-8"))
    committed = normalized((DOCS / "openapi.yaml").read_text(encoding="utf-8"))
    assert generated == committed, (
        "docs/openapi.yaml is stale. Regenerate: cd backend && python manage.py spectacular --file ../docs/openapi.yaml"
    )


def test_er_diagrams_match_the_models():
    out = StringIO()
    call_command("er_diagram", stdout=out)
    assert normalized(out.getvalue()) == normalized((DOCS / "er-diagram.md").read_text(encoding="utf-8")), (
        "docs/er-diagram.md is stale. Regenerate: cd backend && python manage.py er_diagram > ../docs/er-diagram.md"
    )
