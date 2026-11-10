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

    def test_plain_data_struct_preserves_surrounding_function_coverage(self):
        source = 'void Before() {}\nstruct Region {long X; uint8_t* Pixels;};\nvoid After() {}'
        self.assertEqual([x['signature'] for x in function_inventory(source)],
                         ['void Before()', 'void After()'])

    def test_type_methods_and_nested_types_fail_instead_of_being_skipped(self):
        for source in ['struct S {void Hidden() {}};', 'struct S {S() {}};',
                       'struct S {struct Inner {int x;};};', 'struct S {void (*callback)();};']:
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, 'cannot omit possible methods'):
                    definitions(source)

    def test_full_divers_fixture_has_one_entry_for_every_definition(self):
        import json
        fixture = Path(__file__).resolve().parents[1] / 'divers_readability_candidate.json'
        source = json.loads(fixture.read_text())['files']['src/Lionhead/LH3DLib/development/LH3DDivers.cpp']
        actual = function_inventory(source)
        helper_signatures = ('static void SampleScreenshot16(', 'static void SampleScreenshot32(', 'static void BlendScreenshotPixels(', 'static void BuildScreenshotThumbnail(', 'static void UpdateVillagerAnimationBlend(', 'static void TransformVillagerAnimation(', 'static void ProjectInBuildVertices(', 'static void DrawVillagerMesh(', 'static void LightCellAndCopies(', 'static void CalculateClipTexturePlane(', 'static LHPoint GetShadowFootPosition(', 'static uint8_t GetLightGridWeight(', 'static unsigned long SampleLightBrush(', 'static bool32_t ClipLightBrush(', 'static long* WriteInfluenceCircleStrip(', 'static void SampleScreenshotSurface(', 'static void CopyPaginationTile(', 'static void BuildInfluenceCircleMesh(', 'static bool32_t UpdateSmokeAppearance(')
        added = 0
        for signature in helper_signatures:
            if signature in source:
                added += 1
                self.assertEqual(sum(x['signature'].startswith(signature) for x in actual), 1)
        expected_count = 177 + added
        self.assertEqual(len(actual), expected_count)
        self.assertEqual(sum(x['signature'] == 'void UnidentifiedDiversRoutine()' for x in actual), 1)
        self.assertEqual(sum('operator==' in x['signature'] for x in actual), 1)
        self.assertEqual(len({x['line'] for x in actual}), len(actual))
        self.assertEqual(actual[-1]['id'], 'F%03d' % (expected_count - 1))


if __name__ == '__main__':
    unittest.main()
