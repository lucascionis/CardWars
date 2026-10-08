"""Check sprite/atlas coordinates against originals and render packed sprites."""
import copy
import hashlib
import json
from pathlib import Path

import UnityPy
from PIL import Image, ImageDraw
from UnityPy.export.Texture2DConverter import parse_image_data
from UnityPy.helpers import TypeTreeHelper
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

from cardwars_integrate_2x import GAME, STAGE, ROOT, OUT, key, sprite_2x, times2, sha


def main():
    report = json.loads((OUT / 'manifest.json').read_text())
    assert report['status'] == 'verified'
    g = TypeTreeGenerator('2017.4.40f1')
    g.load_local_dll_folder(str(GAME / 'CardWars_Data/Managed'))
    node = g.get_nodes_up('Assembly-CSharp.dll', 'UIAtlas')
    next(c for c in node.m_Children if c.m_Name == 'm_Enabled').m_MetaFlag = 0x4000
    TypeTreeHelper.read_typetree_boost = None
    sample_names = {'SideQuest_Toobs_give', 'SideQuest_Marceline_done',
                    'uiButtonGreen', 'CardAmount', 'Cake_intro_01', 'Fionna_intro_01'}
    sample_pairs = []
    records = {}
    for folder, field, manifest in [('cardwars-carte-2x', 'cards', 'manifest.json'),
                                    ('cardwars-altri-asset-2x', 'assets', 'queue.json')]:
        base = ROOT / 'outputs' / folder
        for a in json.loads((base / manifest).read_text())[field]:
            records[a['id']] = base / a['original']
    counts = {'sprites': 0, 'ngui_atlases': 0, 'rendered_sprite_pairs': 0,
              'normalized_uvs_preserved': True, 'world_geometry_preserved': True,
              'physics_shapes_preserved': True, 'serialized_script_references_preserved': True}
    texture_records = {a['id']: a for f in report['files'] for a in f['textures']}
    for file in report['files']:
        name = file['file']
        old = UnityPy.load(str(GAME / 'CardWars_Data' / name))
        new = UnityPy.load(str(STAGE / 'CardWars_Data' / name))
        old_objs = {o.path_id: o for o in old.objects}
        new_objs = {o.path_id: o for o in new.objects}
        for sid in file['sprites']:
            a = old_objs[sid].read_typetree()
            b = new_objs[sid].read_typetree()
            expected = copy.deepcopy(a)
            sprite_2x(expected)
            assert b == expected, (name, sid)
            assert a['m_Rect']['width'] / a['m_PixelsToUnits'] == b['m_Rect']['width'] / b['m_PixelsToUnits']
            assert a['m_Rect']['height'] / a['m_PixelsToUnits'] == b['m_Rect']['height'] / b['m_PixelsToUnits']
            tid = key(a['m_RD']['texture'], old_objs[sid].assets_file)
            record = texture_records[tid]
            for component in ['x', 'width']:
                assert a['m_RD']['textureRect'][component] / (record['size'][0] / 2) == b['m_RD']['textureRect'][component] / record['size'][0]
            for component in ['y', 'height']:
                assert a['m_RD']['textureRect'][component] / (record['size'][1] / 2) == b['m_RD']['textureRect'][component] / record['size'][1]
            counts['sprites'] += 1
            if name == 'globalgamemanagers.assets' and a['m_Name'] in sample_names:
                # Feed SpriteHelper actual decoded stream data and original
                # exported pixels. This avoids loading every multi-GiB stream
                # merely to render a handful of cropped/tight mesh sprites.
                with (STAGE / 'CardWars_Data' / record['stream']).open('rb') as f:
                    f.seek(record['offset'])
                    raw = f.read(record['mips'][0][2])
                t = new_objs[record['path_id']].read()
                image = parse_image_data(raw, *record['size'], record['format'],
                                         new_objs[sid].assets_file.version,
                                         new_objs[sid].assets_file.target_platform, flip=False)
                old_objs[sid].assets_file._cache[record['path_id']] = Image.open(records[tid]).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                new_objs[sid].assets_file._cache[record['path_id']] = image
                before = old_objs[sid].read().image
                after = new_objs[sid].read().image
                # Float rounding at tight triangle boundaries may add one pixel.
                assert abs(after.width - before.width * 2) <= 2
                assert abs(after.height - before.height * 2) <= 2
                sample_pairs.append((a['m_Name'], before, after))
                old_objs[sid].assets_file._cache.clear()
                new_objs[sid].assets_file._cache.clear()
        for atlas in file['ngui_atlases']:
            sid = atlas['path_id']
            a = old_objs[sid].read_typetree(node)
            b = new_objs[sid].read_typetree(node)
            expected = copy.deepcopy(a)
            expected['mPixelSize'] /= 2
            if a['mCoordinates'] == 0:
                for sprite in expected['sprites']:
                    times2(sprite['inner'])
                    times2(sprite['outer'])
            assert b == expected
            assert a['m_Script'] == b['m_Script']
            for sa, sb in zip(a['sprites'], b['sprites']):
                # TexCoords rectangles remain normalized; Pixels rectangles
                # grow with the texture. Physical borders/sizes stay equal.
                pixel_multiplier = 2 if a['mCoordinates'] == 1 else 1
                for rect in ['inner', 'outer']:
                    for c in ['x', 'y', 'width', 'height']:
                        assert sa[rect][c] * a['mPixelSize'] == sb[rect][c] * b['mPixelSize'] * pixel_multiplier
            counts['ngui_atlases'] += 1
    assert counts['sprites'] == 1087 and counts['ngui_atlases'] == 44
    assert len(sample_pairs) >= 4
    sheet = Image.new('RGB', (900, 290 * len(sample_pairs)), '#dce1e5')
    draw = ImageDraw.Draw(sheet)
    for i, (name, before, after) in enumerate(sample_pairs):
        y = i * 290
        draw.text((18, y + 8), name + ' | sprite riletto dal gioco', fill='#17232e')
        for x, image, label in [(20, before, 'Originale'), (460, after, 'Restauro 2x')]:
            draw.text((x, y + 29), label + f' · {image.width} x {image.height}', fill='#17232e')
            preview = image.convert('RGBA')
            preview.thumbnail((410, 230), Image.Resampling.LANCZOS)
            sheet.paste(preview, (x + (410 - preview.width) // 2, y + 52 + (230 - preview.height) // 2), preview)
    sheet.save(OUT / 'sprite-reinseriti.png')
    counts.update(rendered_sprite_pairs=len(sample_pairs), comparison=str(OUT / 'sprite-reinseriti.png'),
                  comparison_sha256=sha(OUT / 'sprite-reinseriti.png'), status='verified', game_launched=False)
    (OUT / 'metadata-verification.json').write_text(json.dumps(counts, indent=2))
    print(json.dumps(counts, indent=2))


if __name__ == '__main__':
    main()
