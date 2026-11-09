import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from divers_function_inventory import definitions, function_inventory


class DiversInventoryTests(unittest.TestCase):
    def test_directives_do_not_consume_following_empty_functions(self):
        source = '#if defined(A) || defined(B)\nvoid Empty() {}\nvoid After() {return;}\n#endif\n'
        actual = function_inventory(source)
        self.assertEqual([x['signature'] for x in actual], ['void Empty()', 'void After()'])
        self.assertEqual([x['line'] for x in actual], [2, 3])

    def test_literals_comments_and_aggregate_braces_are_not_functions(self):
        source = 'int table[] = {1, 2};\n// void Fake() {}\nvoid Real() {const char* s="{}"; /* } */}\n'
        self.assertEqual([x.signature for x in definitions(source)], ['void Real()'])

    def test_constructors_const_methods_and_nested_bodies(self):
        source = 'Thing::Thing(int x) : member(x) {if(x) {member++;}}\nint Thing::Get() const {return member;}\n'
        actual = definitions(source)
        self.assertEqual(len(actual), 2)
        self.assertEqual(actual[1].signature, 'int Thing::Get() const')
        self.assertEqual(source[actual[0].end], '\n')

    def test_multiline_preprocessor_directive(self):
        source = '#define VALUE(x) \\\n  (x)\nvoid Next() {}\n'
        self.assertEqual(function_inventory(source)[0]['line'], 3)

    def test_unknown_scope_fails_instead_of_silently_losing_definitions(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported top-level scope'):
            definitions('namespace nested {void Hidden() {}}')

    def test_full_divers_fixture_has_one_entry_for_every_definition(self):
        import json
        fixture = Path(__file__).resolve().parents[1] / 'divers_readability_candidate.json'
        source = json.loads(fixture.read_text())['files']['src/Lionhead/LH3DLib/development/LH3DDivers.cpp']
        actual = function_inventory(source)
        helpers = ('SampleScreenshot16', 'SampleScreenshot32', 'BlendScreenshotPixels', 'BuildScreenshotThumbnail')
        added = sum('static void ' + name + '(' in source for name in helpers)
        expected_count = 177 + added
        self.assertEqual(len(actual), expected_count)
        for name in helpers:
            if 'static void ' + name + '(' in source:
                self.assertEqual(sum(x['signature'].startswith('static void ' + name + '(') for x in actual), 1)
        self.assertEqual(sum(x['signature'] == 'void UnidentifiedDiversRoutine()' for x in actual), 1)
        self.assertEqual(sum('operator==' in x['signature'] for x in actual), 1)
        self.assertEqual(len({x['line'] for x in actual}), len(actual))
        self.assertEqual(actual[-1]['id'], 'F%03d' % (expected_count - 1))


if __name__ == '__main__':
    unittest.main()
