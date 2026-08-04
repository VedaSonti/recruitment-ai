import ast
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from profile_pdf import generate_profile_pdf


def load_initial_profile_helper():
    source_path = Path(__file__).with_name("main.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_initial_uplift_profile"
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace["_initial_uplift_profile"]


class ProfileUpliftingTests(unittest.TestCase):
    def test_initial_profile_uses_candidate_fields_only(self):
        build = load_initial_profile_helper()
        candidate = {
            "name": "Verified Candidate",
            "summary": "Verified summary",
            "skills": ["Python", "SQL"],
            "work_experience": [
                {
                    "title": "Developer",
                    "company": "Verified Employer",
                    "is_current": True,
                    "highlights": ["Verified responsibility"],
                }
            ],
            "education": [],
            "key_achievements": [],
        }

        profile = build(candidate)

        self.assertEqual(profile["name"], candidate["name"])
        self.assertEqual(profile["professional_title"], "Developer")
        self.assertEqual(profile["professional_summary"], candidate["summary"])
        self.assertEqual(profile["core_skills"], candidate["skills"])
        self.assertEqual(profile["professional_experience"], candidate["work_experience"])

    def test_generated_pdf_has_selectable_verified_text_and_omits_empty_sections(self):
        profile = {
            "name": "Verified Candidate",
            "professional_title": "Platform Engineer",
            "professional_summary": "Verified professional summary.",
            "core_skills": ["Python", "Linux"],
            "technical_skills": [],
            "professional_experience": [],
            "key_achievements": [],
            "education": [],
            "certifications": [],
            "contact": {"email": "verified@example.com"},
            "additional_information": {},
            "section_visibility": {
                "contact": True,
                "summary": True,
                "skills": True,
                "experience": True,
                "achievements": True,
                "education": True,
                "certifications": True,
                "additional": True,
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "candidate-profile.pdf"
            generate_profile_pdf(profile, output)
            reader = PdfReader(output)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertTrue(output.name.endswith(".pdf"))
        self.assertIn("Verified Candidate", text.title())
        self.assertIn("Verified professional summary", text)
        self.assertIn("Python", text)
        self.assertNotIn("Professional Experience", text)
        self.assertNotIn("Certifications", text)

    def test_prepare_endpoint_declares_idempotent_upsert_and_unique_index(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        self.assertIn('name="unique_profile_match"', source)
        self.assertIn('{"$setOnInsert": new_profile}', source)
        self.assertIn('upsert=True', source)
        self.assertIn('"status": "Uplifted"', source)


if __name__ == "__main__":
    unittest.main()
