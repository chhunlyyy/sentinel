from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
FONT = 'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif"'


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;")


def text(x, y, s, size=14, fill="#e2e8f0", weight="400", anchor="middle", extra=""):
    return f'<text x="{x}" y="{y}" {FONT} font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" {extra}>{esc(s)}</text>'


def rect(x, y, w, h, fill, stroke="none", r=12, sw=0, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>'


BG = '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f172a"/><stop offset="1" stop-color="#1e1b4b"/></linearGradient>'
ARROW = '<marker id="ar" markerWidth="12" markerHeight="12" refX="9" refY="6" orient="auto"><path d="M0,0 L12,6 L0,12 z" fill="#94a3b8"/></marker>'


def overview():
    w, h = 1000, 520
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="Sentinel: one workflow and one shared repo for every AI tool">',
         "<defs>", BG, ARROW,
         '<linearGradient id="shield" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#818cf8"/><stop offset="1" stop-color="#6366f1"/></linearGradient>',
         '<linearGradient id="repo" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#34d399"/><stop offset="1" stop-color="#059669"/></linearGradient>',
         "</defs>", rect(0, 0, w, h, "url(#bg)", r=20)]
    s.append(text(500, 62, "One workflow. One shared memory.", 34, "#ffffff", "800"))
    s.append(text(500, 94, "Every teammate, every AI tool, the same rigor.", 17, "#a5b4fc"))

    tools = [("Claude Code", "#fb923c"), ("Antigravity", "#38bdf8"), ("Codex", "#a78bfa"), ("Cursor", "#f472b6")]
    for i, (name, color) in enumerate(tools):
        y = 150 + i * 62
        s.append(rect(50, y, 200, 48, "#1e293b", color, 24, 2))
        s.append(f'<circle cx="78" cy="{y + 24}" r="10" fill="{color}"/>')
        s.append(text(100, y + 30, name, 17, "#ffffff", "600", "start"))
        s.append(f'<line x1="250" y1="{y + 24}" x2="384" y2="{205 + i * 26}" stroke="#64748b" stroke-width="2" marker-end="url(#ar)"/>')

    s.append('<path d="M500 140 L612 176 L612 290 Q612 360 500 410 Q388 360 388 290 L388 176 Z" fill="url(#shield)" stroke="#c7d2fe" stroke-width="3"/>')
    s.append(text(500, 250, "SENTINEL", 28, "#ffffff", "800"))
    s.append(text(500, 280, "tiered agent workflow", 14, "#e0e7ff"))
    for i, t in enumerate(["triage", "build", "review", "test", "ship"]):
        s.append(text(500, 318 + i * 17, t, 13, "#c7d2fe"))

    s.append('<line x1="614" y1="270" x2="738" y2="270" stroke="#94a3b8" stroke-width="3" marker-end="url(#ar)"/>')
    s.append('<line x1="738" y1="318" x2="614" y2="318" stroke="#94a3b8" stroke-width="3" marker-end="url(#ar)"/>')
    s.append(text(676, 258, "push", 14, "#cbd5e1", "600"))
    s.append(text(676, 345, "pull", 14, "#cbd5e1", "600"))

    s.append('<path d="M760 190 L760 380 A95 24 0 0 0 950 380 L950 190 Z" fill="url(#repo)"/>')
    s.append('<ellipse cx="855" cy="190" rx="95" ry="24" fill="#6ee7b7"/>')
    s.append(text(855, 252, "SHARED REPO", 18, "#ffffff", "800"))
    for i, t in enumerate(["specs", "rules (invariants)", "regression tests"]):
        s.append(text(855, 292 + i * 26, t, 15, "#ecfdf5"))

    pills = [("1", "Same stages for everyone"), ("2", "Tests and specs shared"), ("3", "Logs stay on your machine")]
    for i, (n, t) in enumerate(pills):
        x = 70 + i * 300
        s.append(rect(x, 448, 270, 44, "#1e293b", "#475569", 22, 1.5))
        s.append(f'<circle cx="{x + 24}" cy="470" r="13" fill="#6366f1"/>')
        s.append(text(x + 24, 475, n, 14, "#ffffff", "700"))
        s.append(text(x + 46, 475, t, 15, "#e2e8f0", "500", "start"))
    s.append("</svg>")
    (OUT / "overview.svg").write_text("\n".join(s))


PHASE = {"plan": "#a78bfa", "build": "#38bdf8", "verify": "#fbbf24", "ship": "#34d399", "learn": "#f472b6"}
COLS = [("Repro", "plan"), ("Spec", "plan"), ("Triage", "plan"), ("Code", "build"), ("Clean", "build"), ("Harden", "build"),
        ("Review", "verify"), ("QA", "verify"), ("Promote", "ship"), ("Check", "ship"), ("Docs", "ship"), ("Rollout", "ship"), ("Sync", "ship"), ("Retro", "learn")]
TIERS = [
    ("1", "Tiny", "typo, copy", {"Code"}),
    ("2", "Small", "bug fix", {"Repro", "Code", "Check"}),
    ("3", "Normal", "feature", {"Spec", "Triage", "Code", "Clean", "Review", "QA", "Promote", "Check", "Docs", "Sync"}),
    ("4", "Risky", "auth, schema", {c for c, _ in COLS}),
]


def workflow():
    left, cw, gap, top = 170, 62, 8, 150
    w = left + (cw + gap) * len(COLS) + 20
    h = 470
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="Bigger and riskier tasks run more stages">',
         "<defs>", BG, "</defs>", rect(0, 0, w, h, "url(#bg)", r=20)]
    s.append(text(w / 2, 52, "The bigger the risk, the longer the chain", 30, "#ffffff", "800"))
    s.append(text(w / 2, 82, "Sentinel picks the tier from the size and risk of your task. A reviewer blocker raises it.", 15, "#a5b4fc"))
    lx = 170
    for name, color in (("Plan", PHASE["plan"]), ("Build", PHASE["build"]), ("Verify", PHASE["verify"]), ("Ship", PHASE["ship"]), ("Learn", PHASE["learn"])):
        s.append(f'<circle cx="{lx}" cy="116" r="7" fill="{color}"/>')
        s.append(text(lx + 14, 121, name, 14, "#e2e8f0", "600", "start"))
        lx += 110
    s.append(text(w - 20, 121, "Sync = push to the shared repo", 13, "#94a3b8", anchor="end"))

    names = [c for c, _ in COLS]
    for r, (num, label, desc, stages) in enumerate(TIERS):
        y = top + r * 66
        s.append(rect(18, y, w - 36, 54, "#111827", "#334155", 14, 1))
        s.append(f'<circle cx="46" cy="{y + 27}" r="16" fill="#6366f1"/>')
        s.append(text(46, y + 33, num, 17, "#ffffff", "800"))
        s.append(text(74, y + 24, label, 18, "#ffffff", "700", "start"))
        s.append(text(74, y + 42, desc, 12, "#94a3b8", anchor="start"))
        included = [i for i, c in enumerate(names) if c in stages]
        for a, b in zip(included, included[1:]):
            x1 = left + a * (cw + gap) + cw
            x2 = left + b * (cw + gap)
            s.append(f'<line x1="{x1}" y1="{y + 27}" x2="{x2}" y2="{y + 27}" stroke="#64748b" stroke-width="2"/>')
        for i, (c, ph) in enumerate(COLS):
            if c in stages:
                x = left + i * (cw + gap)
                s.append(rect(x, y + 11, cw, 32, PHASE[ph], r=16))
                s.append(text(x + cw / 2, y + 32, c, 13, "#0f172a", "800"))
    s.append(text(w / 2, h - 28, "Every stage is also its own command, for example /sentinel-review.", 14, "#cbd5e1", "500"))
    s.append("</svg>")
    (OUT / "workflow.svg").write_text("\n".join(s))


if __name__ == "__main__":
    overview()
    workflow()
    print("wrote images")
