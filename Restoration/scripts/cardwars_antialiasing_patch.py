"""Prepare a reversible sampling/MSAA patch for the installed 2x restoration.

No Unity Editor, cloud computation, code/DLL modifications or game launch.
Atlas mip interiors are reduced independently. One-texel gutters are extended
only into unoccupied space. Extremely coarse, overlapping mip regions fall
back to the atlas reduction; those levels require visual review at tiny sizes.
Atlases without identified regions are deferred rather than guessed.
"""
import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import UnityPy
from PIL import Image, ImageDraw, ImageOps
from UnityPy.export.Texture2DConverter import image_to_texture2d, parse_image_data
from UnityPy.helpers import TypeTreeHelper
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

from cardwars_integrate_2x import sha, key

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/cardwars-antialiasing'
GAME = Path('/Users/luca/Games/CardWars/game')
STAGE = GAME.with_name('game-antialiasing-staging')
STREAM_LIMIT = 1536 * 1024**2


def bounds(rect, size, normalized=False, bottom_left=False):
    w, h = size
    x, y, rw, rh = (rect[k] for k in ['x', 'y', 'width', 'height'])
    if normalized:
        x, y, rw, rh = x * w, y * h, rw * w, rh * h
        bottom_left = True
    if bottom_left:
        y = h - y - rh
    b = tuple(round(v) for v in (x, y, x + rw, y + rh))
    assert 0 <= b[0] <= b[2] <= w and 0 <= b[1] <= b[3] <= h, (b, size)
    return b


def reduced(im, size):
    # Pillow's RGBA resize uses premultiplied RGBa internally. BOX avoids
    # sharpening/ringing when reducing narrow cartoon outlines.
    return im.resize(size, Image.Resampling.BOX)


def atlas_mip(im, regions, level):
    scale = 2**level
    size = (max(1, im.width // scale), max(1, im.height // scale))
    result = reduced(im, size)
    rectangles = []
    for b in regions:
        r = tuple(round(v / scale) for v in b)
        if r[2] - r[0] >= 2 and r[3] - r[1] >= 2:
            rectangles.append((b, r))
    mask = Image.new('L', size)
    draw = ImageDraw.Draw(mask)
    for _, r in rectangles:
        draw.rectangle((r[0], r[1], r[2] - 1, r[3] - 1), fill=255)
    # Larger/contained regions first; contained sprite aliases then get their
    # own interior samples. Only free gutter pixels can be overwritten.
    rectangles.sort(key=lambda pair: -(pair[0][2] - pair[0][0]) * (pair[0][3] - pair[0][1]))
    for b, r in rectangles:
        interior = reduced(im.crop(b), (r[2] - r[0], r[3] - r[1]))
        result.paste(interior, r[:2])
        x0, y0, x1, y1 = r
        for a, strip in [
            ((x0 - 1, y0, x0, y1), interior.crop((0, 0, 1, interior.height))),
            ((x1, y0, x1 + 1, y1), interior.crop((interior.width - 1, 0, interior.width, interior.height))),
            ((x0, y0 - 1, x1, y0), interior.crop((0, 0, interior.width, 1))),
            ((x0, y1, x1, y1 + 1), interior.crop((0, interior.height - 1, interior.width, interior.height))),
        ]:
            if a[0] < 0 or a[1] < 0 or a[2] > size[0] or a[3] > size[1]:
                continue
            available = ImageOps.invert(mask.crop(a))
            result.paste(strip, a[:2], available)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    os.nice(10)
    manifest_path = OUT / 'patch-manifest.json'
    assert not manifest_path.exists(), 'A patch already exists; inspect its manifest before rerunning.'
    assert not STAGE.exists(), 'A staging copy exists; inspect it before rerunning.'
    audit = json.loads((OUT / 'audit.json').read_text())
    restoration = json.loads((ROOT / 'outputs/cardwars-integrazione-2x/manifest.json').read_text())
    textures = {a['id']: a for f in restoration['files'] for a in f['textures']}
    reviews = {a['id']: a for a in audit['textures']}
    files = {f['file']: f for f in restoration['files']}
    cameras = json.loads((OUT / 'cameras-before.json').read_text())
    sources = sorted(set(files) | {c['file'] for c in cameras})
    source_hashes = {name: sha(GAME / 'CardWars_Data' / name) for name in sources}
    for file in files.values():
        assert source_hashes[file['file']] == file['sha256']
    subprocess.run(['/bin/cp', '-cR', str(GAME), str(STAGE)], check=True)
    generator = TypeTreeGenerator('2017.4.40f1')
    generator.load_local_dll_folder(str(GAME / 'CardWars_Data/Managed'))
    atlas_node = generator.get_nodes_up('Assembly-CSharp.dll', 'UIAtlas')
    next(c for c in atlas_node.m_Children if c.m_Name == 'm_Enabled').m_MetaFlag = 0x4000
    TypeTreeHelper.read_typetree_boost = None
    report = {'status': 'preparing', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'parent_restoration_manifest_sha256': sha(ROOT / 'outputs/cardwars-integrazione-2x/manifest.json'),
        'staging_game': str(STAGE), 'msaa_quality_samples': 4, 'camera_msaa_enabled': 0,
        'mipmaps_added': [], 'filters_changed': [], 'deferred_atlases': [], 'files': [],
        'base_pixels_preserved': True, 'sprite_rects_uvs_geometry_scripts_preserved': True,
        'game_launched': False, 'unity_editor_used': False,
        'atlas_policy': 'BOX reductions of isolated identified rectangles and free gutters; coarsest overlapping regions need in-game review.'}
    previews = []
    for name in sources:
        print('Preparing', name, flush=True)
        env = UnityPy.load(str(GAME / 'CardWars_Data' / name))
        objects = {o.path_id: o for o in env.objects}
        af = next(o.assets_file for o in env.objects)
        before_hashes = {o.path_id: hashlib.sha256(o.get_raw_data()).hexdigest() for o in env.objects}
        changed = {}
        regions = {}
        named_regions = {}
        for atlas in files.get(name, {}).get('ngui_atlases', []):
            d = objects[atlas['path_id']].read_typetree(atlas_node)
            tid = atlas['texture']
            for sprite in d['sprites']:
                b = bounds(sprite['outer'], textures[tid]['size'], normalized=d['mCoordinates'] == 1)
                regions.setdefault(tid, set()).add(b)
                named_regions.setdefault(tid, {})[sprite['name']] = b
        for obj in env.objects:
            if obj.type.name != 'Sprite':
                continue
            d = obj.read_typetree()
            tid = key(d['m_RD']['texture'], af)
            if tid not in textures:
                continue
            b = bounds(d['m_RD']['textureRect'], textures[tid]['size'], bottom_left=True)
            regions.setdefault(tid, set()).add(b)
            named_regions.setdefault(tid, {})[d['m_Name']] = b
        stream = None
        streams = []
        additions = []
        for obj in env.objects:
            oid = f'{name}:{obj.path_id}'
            if obj.type.name == 'Camera':
                d = obj.read_typetree()
                if not d['m_AllowMSAA'] and d['m_TargetTexture']['m_PathID'] == 0:
                    before = copy.deepcopy(d)
                    d['m_AllowMSAA'] = True
                    obj.save_typetree(d)
                    report['camera_msaa_enabled'] += 1
                    assert {k: v for k, v in d.items() if k != 'm_AllowMSAA'} == {k: v for k, v in before.items() if k != 'm_AllowMSAA'}
                    changed[obj.path_id] = hashlib.sha256(obj.data).hexdigest()
                continue
            if oid not in textures:
                continue
            t = obj.read()
            a = textures[oid]
            review = reviews[oid]
            add_mips = review['missing_mips']
            if add_mips and review['atlas'] and oid not in regions:
                report['deferred_atlases'].append({'id': oid, 'name': t.m_Name, 'reason': 'No identified region rectangles; UV shell analysis required.'})
                add_mips = False
            filter_change = (t.m_MipCount > 1 or add_mips) and t.m_TextureSettings.m_FilterMode != 2
            if not add_mips and not filter_change:
                continue
            t.save()
            assert obj.data == obj.get_raw_data(), ('Texture roundtrip', oid)
            if filter_change:
                report['filters_changed'].append({'id': oid, 'name': t.m_Name, 'from': t.m_TextureSettings.m_FilterMode, 'to': 2})
                t.m_TextureSettings.m_FilterMode = 2
            if add_mips:
                with (GAME / 'CardWars_Data' / a['stream']).open('rb') as f:
                    f.seek(a['offset'])
                    base_bytes = f.read(a['mips'][0][2])
                im = parse_image_data(base_bytes, *a['size'], a['format'], af.version, af.target_platform, t.m_PlatformBlob).convert(a['mode'])
                assert hashlib.sha256(im.tobytes()).hexdigest() == a['pixel_sha256']
                count = int(math.log2(max(im.size))) + 1
                encoded = bytearray(base_bytes)
                sizes = [a['mips'][0]]
                mip_hashes = [hashlib.sha256(base_bytes).hexdigest()]
                roi = regions.get(oid, set())
                for level in range(1, count):
                    size = (max(1, im.width // 2**level), max(1, im.height // 2**level))
                    mip = atlas_mip(im, roi, level) if roi else reduced(im, size)
                    raw, fmt = image_to_texture2d(mip, a['format'], af.target_platform, t.m_PlatformBlob)
                    assert int(fmt) == a['format']
                    encoded.extend(raw)
                    sizes.append([*size, len(raw)])
                    mip_hashes.append(hashlib.sha256(raw).hexdigest())
                if stream is None or stream.tell() + len(encoded) + 16 > STREAM_LIMIT:
                    if stream:
                        stream.close()
                    path = f'GameToMac_Antialiasing_{Path(name).stem}_{len(streams):03d}.resS'
                    stream = (STAGE / 'CardWars_Data' / path).open('wb')
                    streams.append({'file': path})
                stream.write(b'\0' * ((-stream.tell()) % 16))
                offset = stream.tell()
                stream.write(encoded)
                t.m_MipCount = count
                t.m_CompleteImageSize = len(encoded)
                t.image_data = b''
                t.m_StreamData.path = streams[-1]['file']
                t.m_StreamData.offset = offset
                t.m_StreamData.size = len(encoded)
                record = {'id': oid, 'name': t.m_Name, 'size': a['size'], 'format': a['format'],
                    'mips': sizes, 'mip_hashes': mip_hashes, 'base_pixel_sha256': a['pixel_sha256'],
                    'stream': streams[-1]['file'], 'offset': offset, 'bytes': len(encoded),
                    'encoded_sha256': hashlib.sha256(encoded).hexdigest(), 'isolated_regions': len(roi)}
                additions.append(record)
                report['mipmaps_added'].append(record)
                if oid == 'globalgamemanagers.assets:2358':
                    b = named_regions[oid]['Portrait_Finn_Round']
                    icon = im.crop(b)
                    # Approximate GPU bilinear minification with Pillow's
                    # fixed 2x2 bilinear footprint, and area prefiltering.
                    for pixels in [48, 72, 96]:
                        before = icon.transform((pixels, pixels), Image.Transform.AFFINE,
                            (icon.width / pixels, 0, 0, 0, icon.height / pixels, 0),
                            resample=Image.Resampling.BILINEAR)
                        after = reduced(icon, (pixels, pixels))
                        previews.append((pixels, before, after))
                del encoded, im, base_bytes
            t.save()
            changed[obj.path_id] = hashlib.sha256(obj.data).hexdigest()
        if stream:
            stream.close()
        if not changed:
            continue
        target = STAGE / 'CardWars_Data' / name
        temp = target.with_suffix('.aa-tmp')
        temp.write_bytes(af.save())
        temp.replace(target)
        check = UnityPy.load(str(target))
        verified_objects = {o.path_id: o for o in check.objects}
        assert set(before_hashes) == set(verified_objects)
        for oid, obj in verified_objects.items():
            assert hashlib.sha256(obj.get_raw_data()).hexdigest() == changed.get(oid, before_hashes[oid]), (name, oid)
        for r in additions:
            obj = verified_objects[int(r['id'].rsplit(':', 1)[1])]
            t = obj.read()
            assert t.m_MipCount == len(r['mips']) and t.m_TextureSettings.m_FilterMode == 2
            assert t.m_CompleteImageSize == r['bytes'] == t.m_StreamData.size
            assert t.m_StreamData.path == r['stream'] and t.m_StreamData.offset == r['offset']
            with (STAGE / 'CardWars_Data' / r['stream']).open('rb') as f:
                f.seek(r['offset'])
                for size, digest in zip(r['mips'], r['mip_hashes']):
                    raw = f.read(size[2])
                    assert hashlib.sha256(raw).hexdigest() == digest
                    decoded = parse_image_data(raw, *size[:2], r['format'], af.version, af.target_platform, t.m_PlatformBlob)
                    assert list(decoded.size) == size[:2]
                    if size == r['mips'][0]:
                        assert hashlib.sha256(decoded.tobytes()).hexdigest() == r['base_pixel_sha256']
        for s in streams:
            s.update(bytes=(STAGE / 'CardWars_Data' / s['file']).stat().st_size, sha256=sha(STAGE / 'CardWars_Data' / s['file']))
            assert s['bytes'] < STREAM_LIMIT
        report['files'].append({'file': name, 'original_sha256': source_hashes[name], 'sha256': sha(target),
            'changed_objects': len(changed), 'unchanged_objects_verified': len(before_hashes) - len(changed), 'streams': streams})
        print('Verified', name, len(additions), 'new mip chains;', len(changed), 'changed objects', flush=True)
    report['status'] = 'verified'
    report['verified_at_utc'] = datetime.now(timezone.utc).isoformat()
    if previews:
        sheet = Image.new('RGB', (960, 690), '#dde1e5')
        draw = ImageDraw.Draw(sheet)
        draw.text((20, 14), 'Finn: simulazione di riduzione, non screenshot del gioco', fill='#17232e')
        for i, (pixels, before, after) in enumerate(previews):
            y = 52 + i * 210
            draw.text((20, y), f'{pixels} px - bilinear senza mipmap', fill='#17232e')
            draw.text((500, y), f'{pixels} px - prefiltraggio area', fill='#17232e')
            for x, icon in [(30, before), (510, after)]:
                enlarged = icon.resize((pixels * 2, pixels * 2), Image.Resampling.NEAREST)
                sheet.paste(enlarged, (x, y + 22), enlarged.getchannel('A'))
        sheet.save(OUT / 'finn-sampling-preview.png')
    if args.install:
        processes = subprocess.run(['pgrep', '-f', '^/Users/luca/Games/CardWars/game/CardWars.exe'], capture_output=True, text=True)
        assert processes.returncode == 1, 'Close Card Wars before installation.'
        for name, digest in source_hashes.items():
            assert sha(GAME / 'CardWars_Data' / name) == digest
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        backup = GAME.parent / 'backups' / f'before-antialiasing-{stamp}'
        backup.mkdir(parents=True)
        GAME.rename(backup / 'game')
        try:
            STAGE.rename(GAME)
        except Exception:
            (backup / 'game').rename(GAME)
            raise
        report.update(status='installed', installed_game=str(GAME), backup=str(backup), installed_at_utc=datetime.now(timezone.utc).isoformat())
    manifest_path.write_text(json.dumps(report, indent=2))
    marker = {'status': 'verified', 'msaa_samples': 4, 'camera_msaa_enabled': report['camera_msaa_enabled'],
        'mipmaps_added': len(report['mipmaps_added']), 'filters_changed': len(report['filters_changed']),
        'manifest': str(manifest_path), 'manifest_sha256': sha(manifest_path)}
    marker_game = GAME if args.install else STAGE
    (marker_game / 'GameToMac-antialiasing.json').write_text(json.dumps(marker, indent=2))
    restoration_marker = marker_game / 'GameToMac-restoration-2x.json'
    d = json.loads(restoration_marker.read_text())
    d['sampling_patch'] = marker
    restoration_marker.write_text(json.dumps(d, indent=2))
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items() if k in ['status', 'camera_msaa_enabled', 'mipmaps_added', 'filters_changed', 'deferred_atlases', 'backup']}, indent=2))


if __name__ == '__main__':
    main()
