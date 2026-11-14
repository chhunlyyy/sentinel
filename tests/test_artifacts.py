"""Phase B part 1 (PB-01): spec and Gherkin artifacts, validators, coverage table, hashing."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import artifacts as A  # noqa: E402
from errors import SentinelError  # noqa: E402

LITE = ["Problem statement", "Scope", "Out of scope", "Functional requirements",
        "Acceptance criteria", "Edge cases", "Security considerations", "Risks and assumptions"]
FULL = ["Problem statement", "Objectives", "Scope", "Out of scope", "Functional requirements",
        "Non-functional requirements", "Acceptance criteria", "Business rules", "Edge cases",
        "Validation rules", "Security considerations", "API or interface changes", "Database changes",
        "Dependencies", "Risks and assumptions", "Expected deliverables"]
DOCS = ["Problem statement", "Scope", "Expected deliverables"]
SETS = {"lite": LITE, "full": FULL, "docs-only": DOCS}


def make_spec(sections, slug="leave-balance", tier=1, version=1, front=True, bodies=None,
              reqs=("REQ-1: first", "REQ-2: second"), acs=("AC-1 (REQ-1): a", "AC-2 (REQ-2): b"),
              heads=None, extra=""):
    bodies = dict(bodies or {})
    heads = heads or {}
    out = []
    if front is True:
        out.append(f"---\nrun: {slug}\nversion: {version}\ntier: {tier}\n---\n")
    elif front:
        out.append(front)
    for s in sections:
        out.append(heads.get(s, f"## {s}") + "\n")
        if s in bodies:
            body = bodies[s]
        elif s == "Functional requirements":
            body = "\n".join(f"- {r}" for r in reqs)
        elif s == "Acceptance criteria":
            body = "\n".join(f"- {a}" for a in acs)
        else:
            body = f"Text for {s}."
        out.append(body + "\n")
    out.append(extra)
    return "\n".join(out)


def v(text, tier=1, typ="feature", slug="leave-balance"):
    return A.validate_spec(text, slug, tier, run_type=typ)


def feat(scenarios, feature_tags="@REQ-1", rule=None):
    lines = [feature_tags, "Feature: F", ""] if feature_tags else ["Feature: F", ""]
    if rule is not None:
        lines += [f"  {rule[0]}" if rule[0] else "", "  Rule: R", ""]
    for tags, name in scenarios:
        lines += [f"  {tags}", f"  Scenario: {name}", "    Given x", "    When y", "    Then z", ""]
    return "\n".join(lines)


SPEC3 = make_spec(LITE, tier=1, reqs=("REQ-1: a", "REQ-2: b"),
                  acs=("AC-1 (REQ-1): a", "AC-2 (REQ-1): b", "AC-3 (REQ-2): c"), version=2)


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name)
        self.slugdir = self.root / "specs" / "leave-balance"
        self.fdir = self.slugdir / "features"

    def write(self, rel, data):
        p = self.slugdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        return p

    def gv(self, files, spec=SPEC3):
        for n, t in files.items():
            self.write(f"features/{n}", t)
        return A.validate_gherkin(self.fdir, spec)


GOOD = {"balance.feature": feat([("@AC-1 @unit @P1", "a"), ("@AC-2 @integration @P1", "b")]),
        "form.feature": feat([("@AC-3 @e2e @P2", "c")], feature_tags="@REQ-2")}


class SpecHash(Tmp):
    def test_AC_ART_01a_spec_hash_is_sha256_of_bytes(self):
        p = self.write("spec.md", b"abc")
        self.assertEqual(A.spec_hash(p), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_AC_ART_01a_missing_spec(self):
        with self.assertRaises(SentinelError) as c:
            A.spec_hash(self.slugdir / "spec.md")
        self.assertEqual(c.exception.code, "E_NOT_FOUND")

    def test_AC_SPA_08e_byte_exact_no_normalization(self):
        a = A.spec_hash(self.write("spec.md", b"x\n"))
        b = A.spec_hash(self.write("spec.md", b"x\r\n"))
        self.assertNotEqual(a, b)


class GherkinHash(Tmp):
    def h(self, files):
        for n, t in files:
            self.write(f"features/{n}", t)
        return A.gherkin_set_hash(self.fdir)

    def test_AC_GHA_05d_set_hash_vectors(self):
        rows = [
            ([("a.feature", b"Feature: A\n"), ("b.feature", b"Feature: B\n")],
             "55133db39e515460c49c08d68269d97b894480c28a0128b5f71102a985b2961f"),
            ([("a.feature", b"Feature: A\r\n"), ("b.feature", b"Feature: B\n")],
             "b88a68a0997f7b88ee807fc488c754537003b6032330eaae60dbb64bf4ac4d30"),
            ([("c.feature", b"Feature: A\n"), ("b.feature", b"Feature: B\n")],
             "f60aa394be8808985a51b3b9f438d222930ed6ab603bccaa6da99fd1ceedbf38"),
            ([("a.feature", b"Feature: A\nFeature: B\n")],
             "704e1bc94339c6136561786edc81d5cee464d9ea02c1f1dc4adf3e0bf8c26130"),
        ]
        for i, (files, want) in enumerate(rows):
            with self.subTest(row=i):
                import shutil
                shutil.rmtree(self.fdir, ignore_errors=True)
                self.assertEqual(self.h(files)[0], want)

    def test_AC_GHA_05e_creation_order_irrelevant(self):
        h, paths = self.h([("b.feature", b"Feature: B\n"), ("a.feature", b"Feature: A\n")])
        self.assertEqual(h, "55133db39e515460c49c08d68269d97b894480c28a0128b5f71102a985b2961f")
        self.assertEqual(paths, ["features/a.feature", "features/b.feature"])

    def test_AC_GHA_05f_which_files_count(self):
        base, _ = self.h([("balance.feature", b"Feature: B\n")])
        cases = {}
        self.write("features/notes.md", b"hi")
        cases["notes"] = A.gherkin_set_hash(self.fdir)[0] == base
        self.assertTrue(cases["notes"], "notes.md is ignored")
        self.write("features/admin/approve.feature", b"Feature: X\n")
        h2, paths = A.gherkin_set_hash(self.fdir)
        self.assertNotEqual(h2, base)
        self.assertIn("features/admin/approve.feature", paths)
        (self.fdir / "admin" / "approve.feature").unlink()
        self.assertEqual(A.gherkin_set_hash(self.fdir)[0], base)
        (self.fdir / "balance.feature").rename(self.fdir / "leave.feature")
        self.assertNotEqual(A.gherkin_set_hash(self.fdir)[0], base)
        (self.fdir / "leave.feature").rename(self.fdir / "balance.feature")
        os.utime(self.fdir / "balance.feature", (1, 1))
        self.assertEqual(A.gherkin_set_hash(self.fdir)[0], base)

    def test_gherkin_set_order_is_byte_order_not_locale(self):
        _, paths = self.h([("B.feature", b"x"), ("a.feature", b"y"), ("_z.feature", b"z")])
        self.assertEqual(paths, ["features/B.feature", "features/_z.feature", "features/a.feature"])

    def test_gherkin_set_hash_of_empty_or_missing_dir(self):
        self.assertEqual(A.gherkin_set_hash(self.fdir), (hashlib.sha256(b"").hexdigest(), []))


class SpecValidation(unittest.TestCase):
    def test_AC_SPA_01a_valid_full_spec(self):
        r = v(make_spec(FULL, tier=3), tier=3)
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.warnings, [])

    def test_AC_SPA_02a_section_set_follows_tier(self):
        rows = [("feature", 1, "lite", None), ("feature", 2, "lite", None),
                ("feature", 3, "lite", ("Objectives", 8)), ("feature", 3, "full", None),
                ("feature", 4, "full", None), ("feature", 1, "docs-only", ("Out of scope", 6)),
                ("docs", 1, "docs-only", None), ("docs", 4, "docs-only", None)]
        for typ, tier, st, err in rows:
            with self.subTest(typ=typ, tier=tier, set=st):
                r = v(make_spec(SETS[st], tier=tier), tier=tier, typ=typ)
                if err is None:
                    self.assertTrue(r.ok, r.errors)
                else:
                    self.assertFalse(r.ok)
                    self.assertEqual(len(r.errors), err[1])
                    self.assertIn(f"missing section: {err[0]}", r.errors)

    def test_AC_SPA_02b_missing_section_named(self):
        rows = [("feature", 1, LITE, "Acceptance criteria"), ("feature", 2, LITE, "Security considerations"),
                ("feature", 3, FULL, "Database changes"), ("feature", 4, FULL, "Risks and assumptions"),
                ("docs", 2, DOCS, "Expected deliverables")]
        for typ, tier, st, miss in rows:
            with self.subTest(section=miss):
                r = v(make_spec([s for s in st if s != miss], tier=tier), tier=tier, typ=typ)
                self.assertEqual(r.errors, [f"missing section: {miss}"])

    def test_AC_SPA_02c_not_applicable_needs_reason(self):
        rows = [("Not applicable: no schema change in this task.", True), ("Not applicable.", False),
                ("not applicable", False), ("Not applicable:", False), ("Not applicable:   ", False)]
        for body, ok in rows:
            with self.subTest(body=body):
                r = v(make_spec(FULL, tier=3, bodies={"Database changes": body}), tier=3)
                if ok:
                    self.assertTrue(r.ok, r.errors)
                else:
                    self.assertEqual(r.errors, ["Database changes: not applicable needs a reason"])

    def test_AC_SPA_02d_empty_content(self):
        for content in ("", "  \n\n \n"):
            with self.subTest(content=repr(content)):
                r = v(content)
                self.assertIn("missing front matter", r.errors)
                for s in LITE:
                    self.assertIn(f"missing section: {s}", r.errors)
                self.assertEqual(len(r.errors), 9)
        with self.subTest(case="empty scope"):
            self.assertIn("Scope: section is empty", v(make_spec(LITE, bodies={"Scope": ""})).errors)
        with self.subTest(case="comment only"):
            r = v(make_spec(LITE, bodies={"Edge cases": "<!-- todo\nmore -->"}))
            self.assertIn("Edge cases: section is empty", r.errors)

    def test_AC_SPA_02e_second_level_headings_only(self):
        rows = [("## Scope", True), ("## scope", True), ("##  Scope", True), ("##   SCOPE  ", True),
                ("### Scope", False), ("# Scope", False), ("**Scope**", False)]
        for head, ok in rows:
            with self.subTest(heading=head):
                self.assertEqual(v(make_spec(LITE, heads={"Scope": head})).ok, ok)

    def test_AC_SPA_02f_extra_sections_allowed(self):
        r = v(make_spec(LITE + ["Glossary"]))
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.warnings, [])

    def test_AC_SPA_02g_front_matter(self):
        rows = [
            (None, "missing front matter"),
            ("---\nrun: other-run\nversion: 1\ntier: 3\n---\n", 'front matter run "other-run" does not match "leave-balance"'),
            ("---\nrun: leave-balance\nversion: 1\ntier: 2\n---\n", "front matter tier 2 does not match run tier 3"),
            ('---\nrun: leave-balance\nversion: 1\ntier: "high"\n---\n', "front matter tier must be an integer from 1 to 4"),
            ("---\nrun: leave-balance\ntier: 3\n---\n", "front matter version is missing"),
            ("---\nrun: [unclosed\n  : :\n---\n", "front matter is not valid YAML"),
            ("---\nrun: leave-balance\nversion: 1\n---\n", "front matter tier is missing"),
            ("---\nversion: 1\ntier: 3\n---\n", "front matter run is missing"),
        ]
        for fm, err in rows:
            with self.subTest(error=err):
                text = make_spec(FULL, tier=3, front=fm if fm else False)
                r = v(text, tier=3)
                self.assertFalse(r.ok)
                self.assertIn(err, r.errors)

    def test_AC_SPA_02g_tier_integer_bool_rejected(self):
        r = v(make_spec(LITE, front="---\nrun: leave-balance\nversion: 1\ntier: true\n---\n"))
        self.assertIn("front matter tier must be an integer from 1 to 4", r.errors)

    def test_AC_SPA_03a_linked_ids_become_trace_links(self):
        r = v(make_spec(LITE, reqs=("REQ-1: a", "REQ-2: b"), acs=("AC-1 (REQ-1): x", "AC-2 (REQ-1, REQ-2): y")))
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.warnings, [])
        links = r.data["trace_links"]
        for l in (("REQ-1", "AC-1"), ("REQ-1", "AC-2"), ("REQ-2", "AC-2")):
            self.assertIn(l, [tuple(x) for x in links])
        self.assertEqual(len(links), 3)

    def test_AC_SPA_03b_broken_ids(self):
        rows = [
            (("REQ-1", "REQ-2", "REQ-2"), ("AC-1 (REQ-1)", "AC-2 (REQ-2)"), "duplicate id REQ-2"),
            (("REQ-1",), ("AC-1 (REQ-1)", "AC-1 (REQ-1)"), "duplicate id AC-1"),
            (("REQ-1",), ("AC-1",), "AC-1 is not linked to a requirement"),
            (("REQ-1",), ("AC-1 (REQ-9)",), "AC-1 links unknown REQ-9"),
            (("REQ-one",), ("AC-1 (REQ-one)",), 'invalid requirement id "REQ-one"'),
            ((), ("AC-1 (REQ-1)",), "no requirements found"),
            (("REQ-1",), (), "no acceptance criteria found"),
        ]
        for reqs, acs, err in rows:
            with self.subTest(error=err):
                r = v(make_spec(LITE, bodies={
                    "Functional requirements": "\n".join(f"- {x}: t" for x in reqs) or "Nothing listed.",
                    "Acceptance criteria": "\n".join(f"- {x}: t" for x in acs) or "Nothing listed."}))
                self.assertFalse(r.ok)
                self.assertIn(err, r.errors)

    def test_AC_SPA_03c_req_without_criterion_is_warning(self):
        r = v(make_spec(LITE, reqs=("REQ-1: a", "REQ-2: b"), acs=("AC-1 (REQ-1): x",)))
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.warnings, ["REQ-2 has no acceptance criterion"])

    def test_AC_SPA_03f_bold_and_numbered_ids(self):
        r = v(make_spec(LITE, bodies={"Functional requirements": "1. **REQ-1**: a",
                                      "Acceptance criteria": "* **AC-1** (REQ-1): x"}))
        self.assertTrue(r.ok, r.errors)

    def test_AC_SPA_03g_headings_in_code_fence_ignored(self):
        r = v(make_spec(LITE, bodies={"Scope": "```\n## Out of scope\n```\nText"}))
        self.assertTrue(r.ok, r.errors)

    def test_AC_SPA_03h_docs_only_has_no_id_rules(self):
        r = v(make_spec(DOCS), tier=1, typ="docs")
        self.assertTrue(r.ok, r.errors)

    def test_AC_SPA_03i_nonfunctional_requirements_count(self):
        r = v(make_spec(FULL, tier=3, bodies={"Non-functional requirements": "- REQ-3: fast"},
                        acs=("AC-1 (REQ-1): a", "AC-2 (REQ-2): b", "AC-3 (REQ-3): c")), tier=3)
        self.assertTrue(r.ok, r.errors)


class GherkinParse(unittest.TestCase):
    def p(self, text):
        return A.parse_gherkin(text, "features/x.feature")

    def test_AC_GHA_01c_every_construct_parses(self):
        text = '''# a comment
@REQ-1
Feature: Everything
  Some description text.

  Background:
    Given a thing

  @REQ-2
  Rule: R

    @AC-1 @unit @P1
    Scenario: S
      Given a doc
        """
        text <not_a_placeholder>
        """
      When a table
        | a | b |
        | 1 | 2 |
      Then ok
      And fine
      But not bad

    @AC-2 @unit @P1
    Scenario Outline: O <x>
      Given <x>
      Then <y>
      @ex
      Examples:
        | x | y |
        | 1 | 2 |
'''
        pf = self.p(text)
        self.assertEqual(pf.errors, [])
        self.assertEqual([s.name for s in pf.scenarios], ["S", "O <x>"])
        s, o = pf.scenarios
        self.assertEqual(s.tags, ["AC-1", "unit", "P1"])
        self.assertEqual(s.inherited_req, ["REQ-1", "REQ-2"])
        self.assertEqual((s.line, o.line), (13, 26))
        self.assertEqual(o.kind, "outline")
        self.assertEqual(o.example_rows, 1)

    def test_AC_GHA_03c_unsupported_subset(self):
        base = "Feature: F\n  Scenario: S\n    Given a\n    Then b\n"
        rows = [
            ("Given a\n" + base, 1, "step outside a scenario"),
            ("Feature: F\n\n  Scenario Outline: O\n    Given <a>\n", 3, "Scenario Outline has no Examples"),
            ("Feature: F\n  Scenario Outline: O\n    Given <a>\n    Examples:\n      | a |\n", 4, "Examples table has no rows"),
            ("Feature: F\n  Scenario Template: O\n    Given a\n", 2, 'unsupported keyword "Scenario Template"'),
            ("# language: fr\n" + base, 1, "only English Gherkin is supported"),
            (base + "Feature: G\n", 5, "more than one Feature in a file"),
            ("Feature: F\n  Scenario Outline: O\n    Given <a> and <q>\n    Examples:\n      | a |\n      | 1 |\n", 3,
             "placeholder has no Examples column"),
        ]
        for text, line, err in rows:
            with self.subTest(error=err):
                self.assertIn(f"features/x.feature:{line}: {err}", self.p(text).errors)

    def test_AC_GHA_03c_language_en_ok(self):
        self.assertEqual(self.p("# language: en\nFeature: F\n  Scenario: S\n    Given a\n").errors, [])

    def test_AC_GHA_03d_empty_and_featureonly(self):
        for text in ("", "  \n\n"):
            self.assertEqual(self.p(text).errors, ["features/x.feature: file is empty"])
        self.assertEqual(self.p("Feature: F\n").errors, ["features/x.feature: Feature has no scenarios"])

    def test_AC_GHA_03j_placeholder_in_docstring_ignored(self):
        t = 'Feature: F\n  Scenario: S\n    Given a\n      """\n      <x>\n      """\n'
        self.assertEqual(self.p(t).errors, [])


class GherkinValidation(Tmp):
    def test_AC_GHA_01a_valid_set(self):
        r = self.gv(GOOD)
        self.assertTrue(r.ok, r.errors)
        d = r.data
        self.assertEqual(d["paths"], ["features/balance.feature", "features/form.feature"])
        self.assertEqual(d["hash"], A.gherkin_set_hash(self.fdir)[0])
        got = {(l[1], l[3]) for l in d["trace_links"]}
        self.assertEqual({a for a, _ in got}, {"AC-1", "AC-2", "AC-3"})
        self.assertEqual(len(d["coverage"]["rows"]), 15)

    def test_AC_GHA_02a_scenario_tags(self):
        P = "features/balance.feature:7: "
        rows = [
            ("@AC-1 @unit @P1", []),
            ("@AC-1 @security @regression @P3", []),
            ("@unit @P1", [P + "scenario has no @AC tag", "AC-1 has no scenario"]),
            ("@AC-1 @P1", [P + "scenario has no type tag"]),
            ("@AC-1 @unit", [P + "scenario has no priority tag"]),
            ("@AC-1 @unit @P4", [P + "unknown priority tag @P4"]),
            ("@AC-1 @unit @P1 @P2", [P + "more than one priority tag"]),
            ("@AC-1 @smoke @P1", [P + "scenario has no type tag"]),
        ]
        for tags, errs in rows:
            with self.subTest(tags=tags):
                bal = "\n".join(["@REQ-1", "Feature: F", "", "", "", f"  {tags}", "  Scenario: a", "    Given x", ""])
                files = {"balance.feature": bal,
                         "other.feature": feat([("@AC-2 @unit @P1", "b"), ("@AC-3 @unit @P1", "c")])}
                r = self.gv(files)
                self.assertEqual(r.errors, errs)

    def test_AC_GHA_02b_only_req_inherited(self):
        rows = [("@REQ-1", None, "@AC-1 @unit @P1", True), (None, "@REQ-1", "@AC-1 @unit @P1", True),
                ("@AC-1", None, "@unit @P1", False), ("@unit @P1", None, "@AC-1", False),
                (None, "@unit", "@AC-1 @P1", False)]
        for ft, rt, st, ok in rows:
            with self.subTest(ft=ft, rt=rt):
                import shutil
                shutil.rmtree(self.fdir, ignore_errors=True)
                text = ((ft + "\n") if ft else "") + "Feature: F\n" + (f"  {rt}\n  Rule: R\n" if rt else "") \
                    + f"  {st}\n  Scenario: a\n    Given x\n"
                files = {"balance.feature": text,
                         "other.feature": feat([("@AC-2 @unit @P1", "b"), ("@AC-3 @unit @P1", "c")])}
                self.assertEqual(self.gv(files).ok, ok)

    def test_AC_GHA_02c_wrong_req_is_warning(self):
        files = {"a.feature": feat([("@REQ-2 @AC-1 @unit @P1", "a"), ("@AC-2 @unit @P1", "b"), ("@AC-3 @unit @P1", "c")],
                                   feature_tags="")}
        r = self.gv(files)
        self.assertTrue(r.ok, r.errors)
        self.assertIn("AC-1 is not linked to REQ-2 in the approved specification", r.warnings)

    def test_AC_GHA_03a_dangling_tags(self):
        rows = [("@AC-9 @unit @P1", "AC-9 is not in approved specification version 2"),
                ("@REQ-7 @AC-1 @unit @P1", "REQ-7 is not in approved specification version 2")]
        for tags, err in rows:
            with self.subTest(tags=tags):
                import shutil
                shutil.rmtree(self.fdir, ignore_errors=True)
                files = dict(GOOD)
                files["extra.feature"] = feat([(tags, "e")], feature_tags="")
                r = self.gv(files)
                self.assertFalse(r.ok)
                self.assertIn(err, r.errors)

    def test_AC_GHA_03b_criterion_without_scenario(self):
        r = self.gv({"balance.feature": GOOD["balance.feature"]})
        self.assertEqual(r.errors, ["AC-3 has no scenario"])

    def test_AC_GHA_03c_parse_errors_reach_report(self):
        files = dict(GOOD)
        files["balance.feature"] = "Given a\n" + GOOD["balance.feature"]
        r = self.gv(files)
        self.assertIn("features/balance.feature:1: step outside a scenario", r.errors)

    def test_AC_GHA_03d_empty_set(self):
        msg = "no feature files in specs/leave-balance/features"
        with self.subTest(content="missing"):
            self.assertIn(msg, A.validate_gherkin(self.fdir, SPEC3).errors)
        with self.subTest(content="empty dir"):
            self.fdir.mkdir(parents=True)
            self.assertIn(msg, A.validate_gherkin(self.fdir, SPEC3).errors)
        with self.subTest(content="notes only"):
            self.write("features/notes.md", "x")
            self.assertIn(msg, A.validate_gherkin(self.fdir, SPEC3).errors)
        with self.subTest(content="0 bytes"):
            self.write("features/balance.feature", b"")
            self.assertIn("features/balance.feature: file is empty", A.validate_gherkin(self.fdir, SPEC3).errors)
        with self.subTest(content="feature only"):
            self.write("features/balance.feature", "Feature: F\n")
            self.assertIn("features/balance.feature: Feature has no scenarios",
                          A.validate_gherkin(self.fdir, SPEC3).errors)

    def test_AC_GHA_03k_spec_version_from_front_matter(self):
        files = dict(GOOD)
        files["extra.feature"] = feat([("@AC-9 @unit @P1", "e")], feature_tags="")
        r = self.gv(files, spec=make_spec(LITE, version=5, reqs=("REQ-1: a", "REQ-2: b"),
                                          acs=("AC-1 (REQ-1)", "AC-2 (REQ-1)", "AC-3 (REQ-2)")))
        self.assertIn("AC-9 is not in approved specification version 5", r.errors)

    def test_AC_GHA_04a_fifteen_rows(self):
        r = self.gv(GOOD)
        rows = r.data["coverage"]["rows"]
        self.assertEqual([x["category"] for x in rows], A.CATEGORIES)
        self.assertEqual(len(A.CATEGORIES), 15)
        for x in rows:
            self.assertIn(x["state"], ("covered", "not applicable", "missing"))

    def test_AC_GHA_04d_missing_is_warning_not_block(self):
        r = self.gv(GOOD)
        self.assertTrue(r.ok)
        self.assertIn("concurrency: missing", r.warnings)

    def test_AC_GHA_04e_unknown_cov_tag(self):
        files = dict(GOOD)
        files["balance.feature"] = feat([("@AC-1 @unit @P1 @cov-speed", "a"), ("@AC-2 @integration @P1", "b")])
        r = self.gv(files)
        self.assertTrue(r.ok, r.errors)
        self.assertIn("unknown coverage tag @cov-speed", r.warnings)


def sc(*tags):
    return A.Scenario(name="s", kind="scenario", tags=list(tags), inherited_req=[], line=1, path="features/a.feature")


def spec_with_edge(line):
    return make_spec(LITE, bodies={"Edge cases": line} if line else None)


class Coverage(unittest.TestCase):
    def row(self, t, cat):
        return next(r for r in t["rows"] if r["category"] == cat)

    def test_AC_GHA_04b_status_from_tags_and_spec(self):
        rows = [
            ("authz", [sc("unit", "P1", "cov-authz")], None, "covered by 1 scenario", []),
            ("authn", [sc("unit", "P1")], "- n/a @cov-authn: no login in this change",
             "not applicable: no login in this change", []),
            ("concurrency", [sc("unit", "P1")], None, "missing", ["concurrency: missing"]),
            ("authn", [sc("unit", "P1")], "- n/a @cov-authn:", "missing",
             ["authn: missing", "n/a for authn has no reason"]),
            ("regression", [sc("regression", "P1")], None, "covered by 1 scenario", []),
            ("happy-path", [sc("unit", "P1"), sc("unit", "P2")], None, "covered by 2 scenarios", []),
        ]
        for cat, scs, decl, status, warns in rows:
            with self.subTest(category=cat, status=status):
                t = A.coverage_table(scs, spec_with_edge(decl))
                self.assertEqual(self.row(t, cat)["status"], status)
                self.assertEqual([w for w in t["warnings"] if w.startswith(cat + ":") or f"for {cat} " in w], warns)

    def test_AC_GHA_04b_covered_beats_na(self):
        t = A.coverage_table([sc("unit", "P1", "cov-authn")], spec_with_edge("- n/a @cov-authn: nope"))
        self.assertEqual(self.row(t, "authn")["status"], "covered by 1 scenario")

    def test_AC_GHA_04c_never_reported_complete(self):
        t = A.coverage_table([sc("unit", "P1"), sc("unit", "P1"), sc("unit", "P1")], spec_with_edge(None))
        self.assertEqual(self.row(t, "happy-path")["state"], "covered")
        self.assertEqual([r["state"] for r in t["rows"]].count("missing"), 14)
        self.assertEqual(t["summary"], "coverage incomplete: 14 categories missing")

    def test_AC_GHA_04c_summary_never_says_complete_alone(self):
        import re
        scs = [sc("unit", "P1", f"cov-{c}") for c in A.CATEGORIES]
        t = A.coverage_table(scs, spec_with_edge(None))
        self.assertFalse(re.search(r"(?<!in)complete", t["summary"]))
        self.assertEqual(t["warnings"], [])

    def test_AC_GHA_04e_unknown_tag_warning(self):
        t = A.coverage_table([sc("unit", "P1", "cov-speed")], spec_with_edge(None))
        self.assertIn("unknown coverage tag @cov-speed", t["warnings"])


class StoreVersion(Tmp):
    def test_store_spec_copy(self):
        sdir = self.root / ".sentinel"
        src = self.write("spec.md", b"abc")
        ver, sha, path = A.store_version(sdir, "leave-balance", "spec", src, 1)
        self.assertEqual((ver, sha), (1, hashlib.sha256(b"abc").hexdigest()))
        self.assertEqual(Path(path).read_bytes(), b"abc")
        self.assertTrue(str(path).startswith(str(sdir / "runs" / "leave-balance" / "artifacts")))
        with self.assertRaises(SentinelError):  # a stored version is never overwritten
            A.store_version(sdir, "leave-balance", "spec", src, 1)
        self.assertEqual(A.store_version(sdir, "leave-balance", "spec", src, 2)[0], 2)

    def test_AC_GHA_01a_store_gherkin_copy(self):
        sdir = self.root / ".sentinel"
        for n, t in GOOD.items():
            self.write(f"features/{n}", t)
        h, paths = A.gherkin_set_hash(self.fdir)
        ver, sha, path = A.store_version(sdir, "leave-balance", "gherkin", self.fdir, 1)
        self.assertEqual((ver, sha), (1, h))
        for rel in paths:
            self.assertEqual((Path(path) / rel).read_bytes(), (self.slugdir / rel).read_bytes())
        self.assertEqual(A.gherkin_set_hash(Path(path) / "features")[0], h)

    def test_AC_ART_01b_verify_stored_detects_tamper(self):
        sdir = self.root / ".sentinel"
        src = self.write("spec.md", b"abc")
        ver, sha, path = A.store_version(sdir, "leave-balance", "spec", src, 1)
        A.verify_stored(sdir, "leave-balance", "spec", ver, sha)
        Path(path).write_bytes(b"abd")
        with self.assertRaises(SentinelError) as c:
            A.verify_stored(sdir, "leave-balance", "spec", ver, sha)
        self.assertEqual(c.exception.code, "E_INTEGRITY")

    def test_store_version_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            A.store_version(self.root, "x", "other", self.root, 1)


if __name__ == "__main__":
    unittest.main()
