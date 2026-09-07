import struct
import tempfile
import unittest
from pathlib import Path

from extract_geometry import extract
from test_reference import container


class GeometryTests(unittest.TestCase):
    def test_binary_geometry_preserves_signed_origins_and_field_order(self):
        # STRG payload: one pointer to a one-character name at file offset 24.
        strings = struct.pack('<III', 1, 24, 1) + b'x\0'
        # ROOM chunk starts at 30, payload at 38, record at 46.
        room = struct.pack('<II', 1, 46) + struct.pack('<IIIII', 28, 28, 3840, 2160, 60)
        # SPRT chunk starts at 66, payload at 74, record at 82.
        sprite = struct.pack('<II', 1, 82) + struct.pack('<IIIiiiiIIIIIii',
            28, 107, 144, 0, 106, 143, 0, 0, 0, 0, 0, 1, -25, 81)
        raw = container(('STRG', strings), ('ROOM', room), ('SPRT', sprite))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.win'
            path.write_bytes(raw)
            result = extract(path)
        self.assertEqual(result['rooms'][0]['height'], 2160)
        self.assertEqual(result['rooms'][0]['width'], 3840)
        self.assertEqual(result['sprites'][0]['origin_x'], -25)
        self.assertEqual(result['sprites'][0]['separation_mask_type'], 1)
        self.assertEqual(result['sprites'][0]['margin_bottom'], 143)


if __name__ == '__main__':
    unittest.main()
