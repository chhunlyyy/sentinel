from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
FONT = "font-family=\"-apple-system,Segoe UI,Helvetica,Arial,sans-serif\""


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;")


def text(x, y, s, size=14, fill="#1f2937", weight="400", anchor="middle"):
    return f'<text x="{x}" y="{y}" {FONT} font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{esc(s)}</text>'


def box(x, y, w, h, fill, stroke, r=10, sw=1.5):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


def arrow(x1, y1, x2, y2, color="#475569"):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="2" marker-end="url(#a)"/>'


DEFS = '<defs><marker id="a" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#475569"/></marker></defs>'


def overview():
    w, h = 1000, 560
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="Sentinel gives a team one agent workflow and one shared repo">', DEFS,
         f'<rect width="{w}" height="{h}" rx="16" fill="#ffffff" stroke="#d1d5db"/>']
    s.append(text(500, 40, "The problem Sentinel solves", 22, weight="700"))
    s.append(text(500, 64, "AI agents help one person. A team needs one workflow and one shared memory.", 14, "#475569"))

    s.append(box(30, 90, 440, 200, "#fef2f2", "#fca5a5"))
    s.append(text(250, 118, "Without Sentinel", 16, "#991b1b", "700"))
    items = ["Everyone writes their own agent prompts", "Different tools, different rigor per person", "Specs and tests stay on one laptop", "Regression suite goes stale", "Logs and caches pile up, secrets leak"]
    for i, t in enumerate(items):
        s.append(text(56, 150 + i * 28, "x  " + t, 14, "#7f1d1d", anchor="start"))

    s.append(box(530, 90, 440, 200, "#f0fdf4", "#86efac"))
    s.append(text(750, 118, "With Sentinel", 16, "#166534", "700"))
    items = ["One tiered workflow, sized to the task", "Same stages in Claude Code, Antigravity, Codex, Cursor", "Every stage runs in a clean context", "Specs and regression tests shared by the whole team", "Logs stay local; secrets scrubbed before sharing"]
    for i, t in enumerate(items):
        s.append(text(556, 150 + i * 28, "+  " + t, 14, "#14532d", anchor="start"))

    s.append(arrow(480, 190, 520, 190))

    s.append(text(500, 330, "How a team works together", 18, weight="700"))
    people = [("Dev A", "Claude Code", 110), ("Dev B", "Antigravity", 290), ("Dev C", "Codex", 470), ("Dev D", "Cursor", 650)]
    for name, tool, x in people:
        s.append(box(x - 70 + 40, 350, 140, 56, "#eff6ff", "#93c5fd"))
        s.append(text(x + 40, 374, name, 14, "#1e3a8a", "700"))
        s.append(text(x + 40, 394, tool, 12, "#475569"))
    s.append(box(150, 440, 420, 56, "#fff7ed", "#fdba74"))
    s.append(text(360, 463, "/sentinel  tiered workflow", 15, "#9a3412", "700"))
    s.append(text(360, 483, "triage, spec, code, review, QA, release check", 12, "#475569"))
    for name, tool, x in people:
        s.append(arrow(x + 40, 406, 360 + (x + 40 - 360) * 0.35, 438))

    s.append(box(720, 420, 250, 110, "#f5f3ff", "#c4b5fd", sw=2))
    s.append(text(845, 446, "Shared repo (private git)", 14, "#5b21b6", "700"))
    for i, t in enumerate(["specs + index", "invariants", "regression suite"]):
        s.append(text(845, 470 + i * 20, t, 13, "#475569"))
    s.append(arrow(572, 455, 716, 455))
    s.append(text(644, 445, "push branch", 11, "#475569"))
    s.append(arrow(716, 485, 572, 485))
    s.append(text(644, 505, "pull latest", 11, "#475569"))
    s.append("</svg>")
    (OUT / "overview.svg").write_text("\n".join(s))


COLS = ["Repro", "Spec", "Re-triage", "Code", "Clean", "Harden", "Review", "QA", "Promote", "Release check", "Docs", "Rollout", "Retro", "Sync push"]
TIERS = [
    ("Tier 1", "typo, copy, one-line fix", {"Code"}),
    ("Tier 2", "small change or bug fix", {"Repro", "Code", "Release check"}),
    ("Tier 3", "normal feature", {"Spec", "Re-triage", "Code", "Clean", "Review", "QA", "Promote", "Release check", "Docs", "Sync push"}),
    ("Tier 4", "risky: auth, schema, security", set(COLS)),
]
NOTES = {("Tier 2", "Repro"): "bugs", ("Tier 3", "QA"): "targeted", ("Tier 4", "QA"): "full"}
SHARED = {"Spec", "Promote", "Sync push"}


def workflow():
    left, cw, top = 200, 55, 150
    w, h = left + cw * len(COLS) + 30, 480
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="Sentinel stages by tier">', DEFS,
         f'<rect width="{w}" height="{h}" rx="16" fill="#ffffff" stroke="#d1d5db"/>']
    s.append(text(w / 2, 38, "The workflow: stages grow with the size and risk of the task", 20, weight="700"))
    s.append(text(w / 2, 60, "Size and risk pick the tier. A reviewer blocker raises the tier automatically.", 13, "#475569"))
    for i, c in enumerate(COLS):
        x = left + i * cw + cw / 2
        s.append(f'<text transform="translate({x},{top - 8}) rotate(-45)" {FONT} font-size="12" font-weight="600" fill="#1f2937">{esc(c)}</text>')
    for r, (tier, desc, stages) in enumerate(TIERS):
        y = top + r * 62
        s.append(text(24, y + 26, tier, 15, weight="700", anchor="start"))
        s.append(text(24, y + 44, desc, 11, "#475569", anchor="start"))
        for i, c in enumerate(COLS):
            x = left + i * cw + 4
            if c in stages:
                fill, stroke = ("#ede9fe", "#7c3aed") if c in SHARED else ("#dbeafe", "#2563eb")
                s.append(box(x, y + 8, cw - 8, 40, fill, stroke, 8))
                s.append(text(x + (cw - 8) / 2, y + 33, NOTES.get((tier, c), "\u2713"), 11, "#1f2937"))
            else:
                s.append(box(x, y + 8, cw - 8, 40, "#f9fafb", "#e5e7eb", 8, 1))
    ly = top + 4 * 62 + 14
    s.append(box(left, ly, 18, 14, "#dbeafe", "#2563eb", 4))
    s.append(text(left + 26, ly + 12, "runs in your repos, each stage in a clean context", 12, "#475569", anchor="start"))
    s.append(box(left + 380, ly, 18, 14, "#ede9fe", "#7c3aed", 4))
    s.append(text(left + 406, ly + 12, "reads or writes the shared repo", 12, "#475569", anchor="start"))
    s.append(text(24, ly + 40, "Every stage is also its own skill, for example /sentinel-review or /sentinel-release-check.", 12, "#475569", anchor="start"))
    s.append("</svg>")
    (OUT / "workflow.svg").write_text("\n".join(s))


if __name__ == "__main__":
    overview()
    workflow()
    print("wrote images")
