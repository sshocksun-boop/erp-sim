import re
import json
from pathlib import Path
import unittest
from erp_sim.request import parse_request


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / 'AGENTS.md'
DEVELOPMENT_DOCS = ROOT / 'docs' / 'development'
FEATURE_GUIDES = (
    ROOT / 'docs' / 'features' / 'cxmr4103.md',
    ROOT / 'docs' / 'features' / 'abmr001.md',
    ROOT / 'docs' / 'features' / 'aimq131.md',
    ROOT / 'docs' / 'features' / 'aimq102.md',
    ROOT / 'docs' / 'features' / 'aimq136.md',
    ROOT / 'docs' / 'features' / 'asfi301.md',
)
EXPECTED_SECTIONS = ['Usage', 'Query behavior', 'Outputs', 'Result checks']
ROOT_FIELDS = (
    'config', 'username', 'password', 'hostname', 'listen_port',
    'timeout', 'cleanup_timeout', 'trace_dir', 'verbose', 'output',
)


class DocumentationArchitectureTests(unittest.TestCase):
    def test_root_agents_is_a_concise_router(self):
        text = AGENTS.read_text(encoding='utf-8')
        self.assertLessEqual(len(text.splitlines()), 80)
        self.assertIn('## Development documentation router', text)

    def test_every_development_document_is_routed_and_exists(self):
        text = AGENTS.read_text(encoding='utf-8')
        targets = set(re.findall(r'\]\((docs/development/[^)]+\.md)\)', text))
        actual = {
            path.relative_to(ROOT).as_posix()
            for path in DEVELOPMENT_DOCS.glob('*.md')
        }
        self.assertEqual(targets, actual)
        for target in targets:
            self.assertTrue((ROOT / target).is_file(), target)

    def test_feature_guides_share_the_same_section_structure(self):
        for path in FEATURE_GUIDES:
            text = path.read_text(encoding='utf-8')
            sections = re.findall(r'^## (.+)$', text, flags=re.MULTILINE)
            self.assertEqual(sections, EXPECTED_SECTIONS, path)

    def test_feature_usage_sections_do_not_own_shared_fields(self):
        for path in FEATURE_GUIDES:
            text = path.read_text(encoding='utf-8')
            usage = text.split('## Usage', 1)[1].split('## Query behavior', 1)[0]
            for field in ROOT_FIELDS:
                with self.subTest(path=path.name, field=field):
                    self.assertNotIn(f'`{field}`', usage)
            for raw in re.findall(r'```json\s*\n(.*?)\n```', usage, re.DOTALL):
                request = parse_request(raw)
                self.assertFalse(set(request['feature_args']) & set(ROOT_FIELDS))

    def test_documented_json_examples_validate_without_network(self):
        paths = [ROOT / 'README.md', *FEATURE_GUIDES]
        paths += list((ROOT / '.agents' / 'skills' / 'erp-sim').rglob('*.md'))
        count = 0
        for path in paths:
            for raw in re.findall(r'```json\s*\n(.*?)\n```', path.read_text(encoding='utf-8'), re.DOTALL):
                with self.subTest(path=path):
                    parse_request(raw)
                    count += 1
        self.assertGreaterEqual(count, 10)
        for path in (ROOT / 'examples').glob('*.request.json'):
            with self.subTest(path=path):
                parse_request(path.read_bytes())
                request = json.loads(path.read_text(encoding='utf-8'))
                self.assertFalse({'password','username','hostname'} & set(request))

    def test_skill_relative_links_exist(self):
        skill = ROOT / '.agents' / 'skills' / 'erp-sim'
        for path in skill.rglob('*.md'):
            for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                if '://' not in link:
                    self.assertTrue((path.parent / link.split('#')[0]).exists(), (path, link))


if __name__ == '__main__':
    unittest.main()
