import ast
import re
import unittest
from pathlib import Path


def load_skill_helpers():
    source_path = Path(__file__).with_name("main.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    helper_names = {
        "normalize_skill",
        "_normalize_alias_dictionary",
        "skill_alias_terms",
        "expand_skill_abbreviations",
        "find_exact_skill_match",
        "find_alias_skill_match",
        "build_candidate_skill_evidence",
        "_evidence_matches",
        "find_resume_evidence",
        "find_transferable_resume_evidence",
        "log_skill_alias_diagnostic",
        "build_skill_analysis_result",
    }
    assignment_names = {
        "_RAW_SKILL_ALIASES",
        "SKILL_ALIASES",
        "_DIRECT_EVIDENCE_ALIASES",
        "_TRANSFERABLE_EVIDENCE_ALIASES",
        "_DIRECT_EVIDENCE_ONLY_SKILLS",
    }
    helper_nodes = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in helper_names:
            helper_nodes.append(node)
        elif isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(target in assignment_names for target in targets):
                helper_nodes.append(node)

    module = ast.Module(body=helper_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"re": re}
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


skill_helpers = load_skill_helpers()
build_skill_analysis_result = skill_helpers["build_skill_analysis_result"]
build_candidate_skill_evidence = skill_helpers["build_candidate_skill_evidence"]


class SkillAliasMatchingTests(unittest.TestCase):
    @staticmethod
    def analyse(required, candidate):
        return build_skill_analysis_result(
            "test-match",
            required,
            candidate.get("skills", []),
            candidate_evidence=build_candidate_skill_evidence(candidate),
        )

    def test_ai_ml_matches_machine_learning_category_alias(self):
        result = build_skill_analysis_result(
            "test-match",
            ["AI/ML"],
            ["Python", "Machine Learning", "NLP", "Computer Vision"],
        )

        matched = result["matched"]
        missing = result["missing"]
        ai_ml_match = next((item for item in matched if item["required"] == "AI/ML"), None)

        self.assertIsNotNone(ai_ml_match)
        self.assertFalse(any(item["required"] == "AI/ML" for item in missing))
        self.assertIn(
            ai_ml_match["matched_with"],
            ["Machine Learning", "NLP", "Computer Vision"],
        )
        self.assertEqual(ai_ml_match["match_reason"], "category_alias")

    def test_explicit_skill_is_matched(self):
        result = self.analyse(["Python"], {"skills": ["Python"]})
        self.assertEqual(result["matched"][0]["match_reason"], "exact_normalized")

    def test_experience_evidence_is_an_experience_backed_match(self):
        result = self.analyse(
            ["AI/ML"],
            {
                "work_experience": [{
                    "title": "AI Engineer",
                    "highlights": ["Built computer vision models for production."],
                }]
            },
        )
        self.assertEqual(result["matched"][0]["classification"], "experience_backed_match")
        self.assertIn("professional_experience", result["matched"][0]["evidence_sources"])

    def test_project_evidence_is_matched(self):
        result = self.analyse(
            ["Semantic Matching"],
            {"projects": [{"description": "Built a semantic matching pipeline."}]},
        )
        self.assertEqual(result["matched"][0]["match_reason"], "resume_evidence")
        self.assertIn("projects", result["matched"][0]["evidence_sources"])

    def test_fastapi_or_rest_evidence_satisfies_generic_api_requirement(self):
        result = self.analyse(
            ["APIs"],
            {"work_experience": [{"highlights": ["Deployed REST APIs with FastAPI."]}]},
        )
        self.assertEqual([item["required"] for item in result["matched"]], ["APIs"])

    def test_github_actions_evidence_satisfies_ci_cd(self):
        result = self.analyse(["CI/CD"], {"skills": ["GitHub Actions"]})
        self.assertEqual(result["matched"][0]["match_reason"], "resume_evidence")

    def test_summary_llm_evidence_satisfies_generative_ai(self):
        result = self.analyse(
            ["Generative AI"],
            {"summary": "Built LLM-powered applications using the OpenAI API."},
        )
        self.assertEqual(result["matched"][0]["classification"], "experience_backed_match")

    def test_aws_is_transferable_not_exact_for_azure(self):
        result = self.analyse(
            ["Azure"],
            {"work_experience": [{"highlights": ["Deployed services on AWS."]}]},
        )
        self.assertFalse(result["matched"])
        self.assertEqual(result["partial"][0]["classification"], "transferable")

    def test_no_evidence_is_a_gap(self):
        result = self.analyse(["Rust"], {"summary": "Python engineer"})
        self.assertEqual([item["required"] for item in result["missing"]], ["Rust"])

    def test_generic_chatbot_does_not_match_copilot_studio(self):
        result = self.analyse(
            ["Microsoft Copilot Studio"],
            {"projects": [{"description": "Built a generic customer chatbot."}]},
        )
        self.assertEqual(result["missing"][0]["match_reason"], "no_direct_resume_evidence")

    def test_mongodb_and_postgresql_do_not_match_snowflake(self):
        result = self.analyse(
            ["Snowflake"],
            {"skills": ["MongoDB", "PostgreSQL"]},
        )
        self.assertEqual([item["required"] for item in result["missing"]], ["Snowflake"])

    def test_existing_weighting_and_response_contract_are_preserved(self):
        result = self.analyse(
            ["Python", "APIs", "Azure", "Power BI"],
            {
                "skills": ["Python"],
                "summary": "Built REST APIs and deployed workloads on AWS.",
            },
        )
        self.assertEqual(result["semantic_skill_score"], 62)
        self.assertEqual(
            set(result),
            {"match_id", "semantic_skill_score", "matched", "partial", "missing", "summary"},
        )


if __name__ == "__main__":
    unittest.main()
