from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def skills_dir():
    for candidate in (ROOT / "skills", ROOT.parent / "skills"):
        if (candidate / "sentinel" / "SKILL.md").exists():
            return candidate
    raise FileNotFoundError("the skills folder was not found next to the sentinel package")


def valid_slug(slug):
    import re
    import sys
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", slug or "") or ".." in slug or slug.endswith((".", ".lock")):
        sys.exit(f"invalid slug {slug!r}: use 1 to 64 lowercase letters, digits, dots, dashes or underscores, starting with a letter or digit")
    return slug
