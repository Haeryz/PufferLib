"""Extract room and sprite header geometry directly from data.win.

Binary field order reference: UndertaleModLib Models/UndertaleRoom.cs and
Models/UndertaleSprite.cs in https://github.com/UnderminersTeam/UndertaleModTool.
These are resource dimensions, not verified gameplay movement boundaries or
collision masks. Runtime code can change dimensions and collision behavior.
"""
import argparse
import json
import struct
from pathlib import Path

from inspect_game import DataWin, fingerprint


def axe_masks(data, sprite):
    """Read this build's normal v3 AxeSwing sprite with full-size bounds."""
    offset = sprite['offset']
    if (data.u32(offset + 56), data.u32(offset + 60), data.u32(offset + 64)) != (0xffffffff, 3, 0):
        raise ValueError('Unsupported AxeSwing sprite format')
    if (sprite['margin_left'], sprite['margin_top'], sprite['margin_right'] + 1,
            sprite['margin_bottom'] + 1) != (0, 0, sprite['width'], sprite['height']):
        raise ValueError('Mask bounds require a version-specific decoder')
    if data.u32(offset + 76) or data.u32(offset + 80):
        raise ValueError('Unexpected sequence or nine-slice data')
    frames = data.u32(offset + 84)
    mask_offset = offset + 88 + 4 * frames
    masks = data.u32(mask_offset)
    stride = (sprite['width'] + 7) // 8
    size = stride * sprite['height']
    data.require(mask_offset + 4, size * masks)
    return {'frame_count': frames, 'mask_count': masks, 'row_stride_bytes': stride,
            'playback_speed': struct.unpack_from('<f', data.data, offset + 68)[0],
            'playback_speed_type': data.u32(offset + 72),
            'mask_data_offset': mask_offset + 4,
            'mask_bytes_hex': [data.data[mask_offset + 4 + i * size:
                                         mask_offset + 4 + (i + 1) * size].hex()
                               for i in range(masks)]}


def extract(path):
    data = DataWin(path.read_bytes())
    rooms = []
    for record in data.records('ROOM'):
        offset = record['offset']
        data.require(offset, 20)
        rooms.append({**record, 'width': data.u32(offset + 8),
                      'height': data.u32(offset + 12),
                      'stored_speed': data.u32(offset + 16)})
    sprites = []
    fields = ('width', 'height', 'margin_left', 'margin_right', 'margin_bottom',
              'margin_top', 'transparent', 'smooth', 'preload', 'bbox_mode',
              'separation_mask_type', 'origin_x', 'origin_y')
    for record in data.records('SPRT'):
        offset = record['offset']
        data.require(offset + 4, 52)
        values = struct.unpack_from('<IIiiiiIIIIIii', data.data, offset + 4)
        sprite = {**record, **dict(zip(fields, values))}
        if record['name'] in ('spr_SuiseiAxeSwing', 'spr_SuiseiAxeSwing2'):
            sprite['collision_masks'] = axe_masks(data, sprite)
        sprites.append(sprite)
    return {'schema_version': 1, 'source': fingerprint(path),
            'status': 'static_resource_headers; runtime_bounds_and_masks_unverified',
            'format_reference': 'https://github.com/UnderminersTeam/UndertaleModTool/tree/master/UndertaleModLib/Models',
            'rooms': rooms, 'sprites': sprites}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_win', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.data_win)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'rooms': len(result['rooms']), 'sprites': len(result['sprites']),
                      'output': str(args.out)}))
