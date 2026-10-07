import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'src' / 'erp_sim'


def module_name(path):
    relative = path.relative_to(PACKAGE).with_suffix('')
    parts = ['erp_sim', *relative.parts]
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def imported_modules(path):
    current = module_name(path)
    package = current.split('.') if path.name == '__init__.py' else current.split('.')[:-1]
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package) - (node.level - 1)
                prefix = package[:keep]
                suffix = node.module.split('.') if node.module else []
                yield '.'.join([*prefix, *suffix])
            elif node.module:
                yield node.module


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_lower_layers_do_not_import_higher_layers(self):
        rules = {
            PACKAGE / 'request.py': ('erp_sim.features', 'erp_sim.session', 'erp_sim.cli',
                                     'erp_sim.config', 'erp_sim.auth', 'erp_sim.protocol'),
            PACKAGE / 'session.py': ('erp_sim.features', 'erp_sim.cli'),
            PACKAGE / 'navigation.py': ('erp_sim.features', 'erp_sim.session', 'erp_sim.cli'),
        }
        for path in (PACKAGE / 'auth').glob('*.py'):
            rules[path] = ('erp_sim.features', 'erp_sim.session', 'erp_sim.cli')
        for path in (PACKAGE / 'protocol').glob('*.py'):
            rules[path] = ('erp_sim.features', 'erp_sim.session', 'erp_sim.cli',
                           'erp_sim.navigation', 'erp_sim.auth', 'erp_sim.config')
        for path, forbidden in rules.items():
            for imported in imported_modules(path):
                with self.subTest(path=path.name, imported=imported):
                    self.assertFalse(imported.startswith(forbidden))

    def test_shared_runtime_layers_do_not_name_erp_programs(self):
        programs = {
            path.stem.lower() for path in (PACKAGE / 'features').glob('*.py')
            if path.stem not in {'__init__', 'base'}
        }
        protected = [PACKAGE / 'session.py', PACKAGE / 'navigation.py']
        protected += list((PACKAGE / 'auth').glob('*.py'))
        protected += list((PACKAGE / 'protocol').glob('*.py'))
        for path in protected:
            text = path.read_text(encoding='utf-8').lower()
            for program in programs:
                with self.subTest(path=path.name, program=program):
                    self.assertNotIn(program, text)


if __name__ == '__main__':
    unittest.main()
