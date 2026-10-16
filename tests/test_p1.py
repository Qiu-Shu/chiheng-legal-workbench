from __future__ import annotations

import hashlib
import json
import re
import yaml
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cn-litigation-redteam"
DIST = ROOT / "dist" / "cn-litigation-redteam.zip"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml(path: Path):
    text = read(path)
    try:
        if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text)):
            raise ValueError('YAML aliases are not permitted')
        value = yaml.safe_load(text)
        json.dumps(value, allow_nan=False)  # Preserve the original plain JSON types only.
        return value
    except (yaml.YAMLError, TypeError) as error:
        raise ValueError('Unsafe or invalid YAML') from error


class P1SkillTests(unittest.TestCase):
    def test_behavior_inputs_cover_all_cases_and_criminal_policy_is_current(self):
        root = SKILL.parents[1]
        cases = json.loads((root/'tests/behavior/inputs-2026-09-28.json').read_text())['cases']
        self.assertEqual([case['id'] for case in cases], [f'B{i:02d}' for i in range(1, 51)])
        self.assertTrue(all(case['prompt'].strip() for case in cases))
        specs = json.loads((root/'tests/behavior/scenarios.yaml').read_text())['scenarios']
        criminal = next(case for case in specs if case['test_id'] == 'B31')
        self.assertNotIn('直接形成刑事对外稿', criminal['forbidden_behavior'])
        self.assertIn('套用民事证明责任或自认规则认定犯罪', criminal['forbidden_behavior'])

    def test_required_files_exist(self):
        required = {
            "SKILL.md",
            "LICENSE",
            "NOTICE",
            "README.md",
            "agents/openai.yaml",
            "references/workflow.md",
            "references/failure-modes-cn.md",
            "references/authority-and-temporal-rules.md",
            "references/evidence-and-admissions.md",
            "references/confidentiality-and-network.md",
            "references/jurisdiction-routing.md",
            "references/source-registry.yaml",
            "references/coverage.yaml",
            "references/scrapling-integration.md",
            "references/worked-examples-cn.md",
            "references/tool-contract.md",
            "assets/matter-intake.yaml",
            "assets/internal-review.md",
            "assets/proposed-external-draft.md",
            "assets/attack-audit-schema.json",
            "assets/entrypoint-profile.yaml",
        }
        actual = {
            path.relative_to(SKILL).as_posix()
            for path in SKILL.rglob("*")
            if path.is_file()
        }
        self.assertTrue(required <= actual, sorted(required - actual))

    def test_skill_frontmatter_and_chinese_core(self):
        text = read(SKILL / "SKILL.md")
        match = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(match)
        frontmatter = match.group(1)
        self.assertIn("name: cn-litigation-redteam", frontmatter)
        self.assertRegex(frontmatter, r"description:\s*>?-?\s*\n?\s*Use when")
        for phrase in (
            "模式 A",
            "模式 B",
            "阶段 0",
            "保留 / 限定保留 / 待补证 / 待核法 / 删除 / 需律师决策",
            "内部审查",
            "拟对外稿",
            "待承办律师复核",
        ):
            self.assertIn(phrase, text)

    def test_removed_upstream_absolutes(self):
        text = read(SKILL / "SKILL.md")
        for forbidden in (
            "Formal, precise British English",
            "between two and five",
            "Five heads is the ceiling",
            "Concede early and specifically",
            "No hedging qualifiers",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("允许 0 个或 1 个", text)
        self.assertIn("不得自动新增事实承认", text)

    def test_references_are_relative_and_resolve(self):
        text = read(SKILL / "SKILL.md")
        linked = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
        local = [target.split("#", 1)[0] for target in linked if "://" not in target]
        self.assertGreaterEqual(len(local), 9)
        for target in local:
            self.assertFalse(target.startswith("/"), target)
            self.assertTrue((SKILL / target).exists(), target)

    def test_openai_yaml_is_supported_and_explicit_only(self):
        config = load_yaml(SKILL / "agents" / "openai.yaml")
        self.assertEqual(set(config), {"interface", "policy"})
        self.assertEqual(config["interface"]["display_name"], "持衡·中国诉讼攻防审查")
        self.assertIn("$cn-litigation-redteam", config["interface"]["default_prompt"])
        self.assertTrue(config["policy"]["allow_implicit_invocation"])

    def test_coverage_does_not_overclaim(self):
        coverage = load_yaml(SKILL / "references" / "coverage.yaml")
        modules = coverage["modules"]
        self.assertEqual(modules["civil_commercial"]["status"], "experimental")
        self.assertEqual(modules["criminal"]["status"], "experimental")
        self.assertNotIn("reviewed", {item["status"] for item in modules.values()})
        self.assertEqual(coverage["local_enhancement"]["status"], "experimental")

    def test_source_registry_preserves_research_seed_status(self):
        registry = load_yaml(SKILL / "references" / "source-registry.yaml")
        self.assertGreaterEqual(len(registry["sources"]), 2)
        for source in registry["sources"]:
            self.assertEqual(source["review_state"], "research_seed_only")
            self.assertIsNone(source["last_success_at"])
            self.assertEqual(source["approved_fetch_modes"], [])

    def test_attack_audit_schema_is_valid_json(self):
        schema = json.loads(read(SKILL / "assets" / "attack-audit-schema.json"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        required = set(schema["required"])
        self.assertTrue(
            {
                "attack_id",
                "target_claim",
                "requested_legal_effect",
                "fact_ids",
                "evidence_refs",
                "law_fragment_refs",
                "case_refs",
                "burden_holder",
                "burden_rule_ref",
                "strongest_reply",
                "response_summary",
                "failure_mode_results",
                "adverse_authorities",
                "disposition",
                "disposition_reason",
                "materiality",
                "unresolved_items",
                "admission_review_ids",
                "external_use_status",
            }
            <= required
        )
        dispositions = schema["properties"]["disposition"]["enum"]
        self.assertEqual(
            dispositions,
            ["保留", "限定保留", "待补证", "待核法", "删除", "需律师决策"],
        )

    def test_behavior_matrix_has_exactly_fifty_unique_scenarios(self):
        scenarios = json.loads(read(ROOT / "tests" / "behavior" / "scenarios.yaml"))
        ids = [item["test_id"] for item in scenarios["scenarios"]]
        self.assertEqual(len(ids), 50)
        self.assertEqual(len(set(ids)), 50)
        self.assertEqual(ids, [f"B{i:02d}" for i in range(1, 51)])
        for item in scenarios["scenarios"]:
            self.assertTrue(item["expected_behavior"])
            self.assertTrue(item["forbidden_behavior"])

    def test_license_and_notice_preserve_attribution(self):
        upstream = ROOT / "upstream" / "original"
        self.assertEqual(
            hashlib.sha256((SKILL / "LICENSE").read_bytes()).hexdigest(),
            hashlib.sha256((upstream / "LICENSE").read_bytes()).hexdigest(),
        )
        notice = read(SKILL / "NOTICE")
        upstream_notice = read(upstream / "NOTICE").rstrip()
        self.assertTrue(notice.startswith(upstream_notice + "\n\n---\n"))
        for phrase in (
            "Seth J. Chandler",
            "Larissa Meredith-Flister",
            "cn-litigation-redteam",
            "No endorsement",
        ):
            self.assertIn(phrase, notice)

    def test_no_private_or_absolute_paths_in_distributable(self):
        forbidden = (
            "/Users/",
            "身份证号",
            "BEGIN OPENSSH PRIVATE KEY",
            "api_key=",
            "sk-",
        )
        for path in SKILL.rglob("*"):
            if not path.is_file():
                continue
            text = read(path)
            for marker in forbidden:
                self.assertNotIn(marker, text, f"{marker} in {path}")

    def test_package_has_single_top_level_and_expected_files(self):
        self.assertTrue(DIST.exists())
        with zipfile.ZipFile(DIST) as archive:
            names = archive.namelist()
            self.assertTrue(names)
            self.assertEqual({name.split("/", 1)[0] for name in names}, {"cn-litigation-redteam"})
            self.assertIn("cn-litigation-redteam/SKILL.md", names)
            self.assertIn("cn-litigation-redteam/LICENSE", names)
            self.assertIn("cn-litigation-redteam/NOTICE", names)
            self.assertFalse(any(".." in Path(name).parts for name in names))


if __name__ == "__main__":
    unittest.main()
