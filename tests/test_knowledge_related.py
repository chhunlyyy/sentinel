"""Tests for Sentinel 2.1 Wave 2 Item 5 backend APIs:
1. GET /api/v1/projects/{pid}/knowledge/related?q=<text>&limit=<n>
2. Task knowledge recording & knowledge_used exposed on /tasks/{slug}/specification
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from sv_helpers import SV
import knowledge


class KnowledgeRelatedTest(SV):
    def setUp(self):
        super().setUp()
        self.shared_path = self.ws / ".sentinel" / "shared"
        self.shared_path.mkdir(parents=True, exist_ok=True)
        knowledge.ensure_layout(self.shared_path)

        # Write invariants.md
        inv_content = (
            "# Project invariants\n\n"
            "- ID: INV-PAYROLL-1\n"
            "  Rule: Round once on the final net amount.\n\n"
            "- ID: INV-HR-1\n"
            "  Rule: HR data only for role HR.\n"
        )
        (self.shared_path / "invariants.md").write_text(inv_content, encoding="utf-8")

        # Create two change records
        changes_dir = self.shared_path / "knowledge" / "changes" / "backend" / "2026-11"
        changes_dir.mkdir(parents=True, exist_ok=True)

        rec1 = changes_dir / "pr-212.md"
        rec1.write_text(
            "---\n"
            "key: pr-212\n"
            "repo: backend\n"
            "title: Leave balance API\n"
            "summary: GET /leave/balance per employee\n"
            "date: '2026-11-03T11:20:00Z'\n"
            "---\n"
            "## Summary\n"
            "Provides GET /leave/balance endpoint returning leave days.\n",
            encoding="utf-8",
        )

        rec2 = changes_dir / "run-employee-search.md"
        rec2.write_text(
            "---\n"
            "key: run-employee-search\n"
            "repo: backend\n"
            "title: Employee search by ID\n"
            "summary: Adds /employees/search endpoint; HR and managers only\n"
            "date: '2026-11-20T14:32:00Z'\n"
            "---\n"
            "## Summary\n"
            "Adds fast search by primary employee ID.\n",
            encoding="utf-8",
        )

        index = {
            "pr-212": {
                "path": str(rec1.relative_to(self.shared_path)),
                "repo": "backend",
                "title": "Leave balance API",
                "summary": "GET /leave/balance per employee",
                "date": "2026-11-03T11:20:00Z",
                "reached": [{"branch": "main", "sha": "aaa1", "at": "2026-11-03T11:20:00Z"}],
            },
            "run-employee-search": {
                "path": str(rec2.relative_to(self.shared_path)),
                "repo": "backend",
                "title": "Employee search by ID",
                "summary": "Adds /employees/search endpoint; HR and managers only",
                "date": "2026-11-20T14:32:00Z",
                "reached": [{"branch": "main", "sha": "bbb2", "at": "2026-11-20T14:32:00Z"}],
            },
        }
        knowledge.write_index(self.shared_path, index)

    def test_knowledge_related_default_empty_query(self):
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/knowledge/related")
        self.assertEqual(r.status, 200, r.text)
        data = r.json
        self.assertIn("records", data)
        self.assertIn("invariants", data)
        self.assertEqual(len(data["records"]), 2)
        # Sorted by recency descending: run-employee-search (Nov 20) before pr-212 (Nov 3)
        self.assertEqual(data["records"][0]["key"], "run-employee-search")
        self.assertEqual(data["records"][1]["key"], "pr-212")
        self.assertEqual(len(data["invariants"]), 2)
        inv_ids = [inv["id"] for inv in data["invariants"]]
        self.assertIn("INV-PAYROLL-1", inv_ids)
        self.assertIn("INV-HR-1", inv_ids)

    def test_knowledge_related_query_matching(self):
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/knowledge/related?q=leave+balance")
        self.assertEqual(r.status, 200, r.text)
        data = r.json
        self.assertGreaterEqual(len(data["records"]), 1)
        self.assertEqual(data["records"][0]["key"], "pr-212")

    def test_knowledge_related_limit(self):
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/knowledge/related?limit=1")
        self.assertEqual(r.status, 200, r.text)
        data = r.json
        self.assertEqual(len(data["records"]), 1)
        self.assertEqual(len(data["invariants"]), 1)

    def test_knowledge_related_invalid_limit(self):
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/knowledge/related?limit=-1")
        self.assertEqual(r.status, 400, r.text)
        self.assertEqual(r.code, "E_VALIDATION")

        r2 = self.http.get("/api/v1/projects/digital-hr/knowledge/related?limit=abc")
        self.assertEqual(r2.status, 400, r2.text)
        self.assertEqual(r2.code, "E_VALIDATION")

    def test_knowledge_related_unknown_project(self):
        self.serve()
        r = self.http.get("/api/v1/projects/nonexistent/knowledge/related")
        self.assertEqual(r.status, 404, r.text)

    def test_specification_carries_knowledge_used(self):
        self.to_spec_review("spec-test-k", 3)
        self.serve()
        r = self.http.get("/api/v1/tasks/spec-test-k/specification")
        self.assertEqual(r.status, 200, r.text)
        data = r.json
        self.assertIn("knowledge_used", data)
        k_used = data["knowledge_used"]
        self.assertIn("records", k_used)
        self.assertIn("summaries", k_used)
        self.assertIn("invariants", k_used)

    def test_gherkin_carries_knowledge_used(self):
        self.to_gherkin_review("gherkin-test-k", 3)
        self.serve()
        r = self.http.get("/api/v1/tasks/gherkin-test-k/gherkin")
        self.assertEqual(r.status, 200, r.text)
        data = r.json
        self.assertIn("knowledge_used", data)
        k_used = data["knowledge_used"]
        self.assertIn("records", k_used)
        self.assertIn("summaries", k_used)
        self.assertIn("invariants", k_used)


if __name__ == "__main__":
    unittest.main()
