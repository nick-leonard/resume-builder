import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "resume_pdf_to_yaml.py"
SPEC = importlib.util.spec_from_file_location("resume_pdf_to_yaml", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ResumePdfToYamlTests(unittest.TestCase):
    def test_sanitization_removes_identity_contact_education_and_footer(self):
        text = """
        Jordan Example
        Technical Engineering Leader | CTO
        555-010-0199 | jordan@example.com | www.linkedin.com/in/jordanexample
        • Built a platform.
        Jordan Example | 1
        Education
        Example University
        """
        cleaned = MODULE.sanitize_resume_text(text)
        self.assertNotIn("Jordan Example", cleaned)
        self.assertNotIn("555-010-0199", cleaned)
        self.assertNotIn("jordan@example.com", cleaned)
        self.assertNotIn("Education", cleaned)
        self.assertIn("Technical Engineering Leader | CTO", cleaned)
        self.assertIn("Built a platform", cleaned)

    def test_canonical_yaml_has_quoted_dates_and_skills_last(self):
        document = MODULE.ResumeDocument(
            headline="Technical Leader | CTO",
            summary_bullets=[
                MODULE.ContentItem(id="sum_exec", text="Built reliable platforms.")
            ],
            experience=[
                MODULE.Experience(
                    company="Example Co",
                    location=None,
                    positions=[
                        MODULE.Position(
                            title_lines=["Chief Technology Officer"],
                            dates=["Dec 2025 - Present"],
                            summary=None,
                            bullets=[],
                        )
                    ],
                )
            ],
            skills=MODULE.Skills(
                ai=["RAG"],
                languages=["Python"],
                tools=["AWS"],
                architecture_patterns=["event-driven systems"],
            ),
        )
        rendered = MODULE.render_resume_yaml(document)
        MODULE.validate_resume_yaml(rendered)
        parsed = yaml.safe_load(rendered)
        self.assertEqual(
            list(parsed), ["headline", "summary_bullets", "experience", "skills"]
        )
        self.assertIn('- "Dec 2025 - Present"', rendered)
        self.assertTrue(rendered.rstrip().endswith('- "event-driven systems"'))


if __name__ == "__main__":
    unittest.main()
