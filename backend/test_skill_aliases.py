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
        "log_skill_alias_diagnostic",
        "build_skill_analysis_result",
    }
    assignment_names = {"_RAW_SKILL_ALIASES", "SKILL_ALIASES"}
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
    return namespace["build_skill_analysis_result"]


build_skill_analysis_result = load_skill_helpers()


class SkillAliasMatchingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
