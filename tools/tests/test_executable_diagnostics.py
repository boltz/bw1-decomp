"""Exercise file/layout/content distinctions with synthetic PE images."""

from pathlib import Path
import struct
import tempfile
import unittest

from tools.executable_diagnostics import diagnose, differences, render


def image(raw=b'abcdefgh', raw_offset=0x200, virtual_size=0x80):
    data = bytearray(raw_offset)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x14C, 1, 0, 0, 0, 96, 0)
    struct.pack_into('<H', data, 0x98, 0x10B)
    struct.pack_into('<I', data, 0x98 + 28, 0x400000)
    struct.pack_into('<I', data, 0x98 + 60, 0x200)
    struct.pack_into('<8sIIIIIIHHI', data, 0x98 + 96, b'.text', virtual_size, 0x1000,
                     len(raw), raw_offset if raw else 0, 0, 0, 0, 0, 0x20)
    return bytes(data) + raw


class ExecutableDiagnosticsTests(unittest.TestCase):
    def compare(self, original, built, symbol_text=''):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b, symbols = root / 'original.exe', root / 'built.exe', root / 'symbols.txt'
            a.write_bytes(original)
            if built is not None:
                b.write_bytes(built)
            symbols.write_text(symbol_text)
            return diagnose(a, b, symbols)

    def test_equal_images(self):
        result = self.compare(image(), image())
        self.assertEqual(result['status'], 'match')
        self.assertEqual(result['file_comparison']['different_bytes'], 0)
        self.assertEqual(result['sections'][0]['comparison']['different_bytes'], 0)

    def test_section_change_has_original_symbol_context(self):
        result = self.compare(image(), image(b'abXdefgh'),
                              'function = .text:0x00401000; // type:function size:0x8 scope:global\n')
        span = result['sections'][0]['comparison']['ranges'][0]
        self.assertEqual(span['original_va'], 0x401002)
        self.assertEqual(span['built_va'], 0x401002)
        self.assertEqual(span['original_symbol']['name'], 'function')
        self.assertEqual(span['original_symbol']['relation'], 'containing')
        self.assertIn('0x401002', render(result))

    def test_header_difference_is_not_reported_as_code_difference(self):
        built = bytearray(image())
        built[0x88] = 1
        result = self.compare(image(), bytes(built))
        self.assertEqual(result['headers']['different_bytes'], 1)
        self.assertEqual(result['sections'][0]['comparison']['different_bytes'], 0)

    def test_raw_section_movement_does_not_imply_changed_code(self):
        result = self.compare(image(), image(raw_offset=0x220))
        self.assertGreater(result['file_comparison']['different_bytes'], 0)
        self.assertTrue(result['sections'][0]['layout_changed'])
        self.assertEqual(result['sections'][0]['comparison']['different_bytes'], 0)

    def test_virtual_extent_changes_without_synthesizing_bss_bytes(self):
        result = self.compare(image(raw=b''), image(raw=b'', virtual_size=0x100))
        self.assertTrue(result['sections'][0]['layout_changed'])
        self.assertEqual(result['sections'][0]['comparison']['different_bytes'], 0)

    def test_missing_build_is_reported(self):
        result = self.compare(image(), None)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('built executable is missing', result['limitations'])
        self.assertIn('unavailable', render(result))

    def test_invalid_pe_still_gets_file_diagnostics(self):
        result = self.compare(b'abc', b'abcd')
        self.assertEqual(result['file_comparison']['different_bytes'], 1)
        self.assertTrue(any('PE section comparison unavailable' in note for note in result['limitations']))

    def test_locations_are_bounded_but_counts_remain_exact(self):
        result = differences(b'\0' * 100, b'\1\0' * 50)
        self.assertEqual(result['different_bytes'], 50)
        self.assertEqual(result['range_count'], 50)
        self.assertEqual(len(result['ranges']), 20)
        self.assertEqual(differences(b'abc', b'abcdef')['ranges'], [{'start': 3, 'end': 6}])

    def test_original_input_hash_mismatch_is_not_a_matching_build(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'original.exe'
            path.write_bytes(image())
            result = diagnose(path, path, expected_sha1='0' * 40)
        self.assertEqual(result['status'], 'original_hash_mismatch')


if __name__ == '__main__':
    unittest.main()
