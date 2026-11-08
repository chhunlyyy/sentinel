from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def skills_dir():
    for candidate in (ROOT / "skills", ROOT.parent / "skills"):
        if (candidate / "sentinel" / "SKILL.md").exists():
            return candidate
    raise FileNotFoundError("the skills folder was not found next to the sentinel package")
