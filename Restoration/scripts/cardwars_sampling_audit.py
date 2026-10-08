"""Audit installed restoration sampling without modifying or launching Card Wars.

Missing mipmaps are candidates, not proof of visible aliasing. Atlas subregions,
UVs and screen coverage must be considered before producing a sampling patch.
"""
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import UnityPy

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/cardwars-antialiasing'
GAME = Path('/Users/luca/Games/CardWars/game/CardWars_Data')
FILTERS = {0: 'Point', 1: 'Bilinear', 2: 'Trilinear'}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    installation = json.loads((ROOT / 'outputs/cardwars-integrazione-2x/manifest.json').read_text())
    inventory = json.loads((ROOT / 'outputs/cardwars-inventario/inventario.json').read_text())
    inventory = {a['id']: a for a in inventory['textures']}
    cards = json.loads((ROOT / 'outputs/cardwars-carte-2x/manifest.json').read_text())
    card_ids = {a['id'] for a in cards['cards']}
    rows = []
    source_files = []
    for file in installation['files']:
        source = GAME / file['file']
        digest = sha(source)
        assert digest == file['sha256'], source
        source_files.append({'path': str(source), 'sha256': digest})
        env = UnityPy.load(str(source))
        objects = {o.path_id: o for o in env.objects}
        atlases = {}
        for atlas in file['ngui_atlases']:
            atlases.setdefault(atlas['texture'], []).append(atlas)
        for texture in file['textures']:
            original = inventory[texture['id']]
            obj = objects[texture['path_id']]
            d = obj.read_typetree()
            settings = d['m_TextureSettings']
            assert d['m_Name'] == texture['name']
            assert [d['m_Width'], d['m_Height']] == texture['size']
            assert d['m_MipCount'] == len(texture['mips'])
            width, height = texture['size']
            missing = d['m_MipCount'] == 1 and max(width, height) > 2
            point = settings['m_FilterMode'] == 0
            refs = atlases.get(texture['id'], [])
            atlas = original['atlas_hint'] or bool(refs)
            tiny_constant = max(width, height) <= 2
            name = texture['name'].lower().removeprefix('low_')
            animation = name.startswith(('nis', 'fcnis', 'fx_')) or original['category'] == 'effects'
            if tiny_constant:
                group = 'preserve_constant'
                priority = 0
                action = 'Conservare: texture costante 2×2; mipmap non utili.'
            elif point:
                group = 'point_filter_trial'
                priority = 1
                action = 'Provare Bilinear/Trilinear e confrontare piccoli dettagli; conservare mipmap già presenti.'
                if missing:
                    action += ' Preparare anche mipmap.'
            elif missing and (original['category'] == 'ui' or 'hud' in name):
                group = 'ui_mip_trial'
                priority = 1
                action = 'Preparare mipmap per icone e miniature; confrontare nitidezza alla dimensione reale.'
            elif missing and animation:
                group = 'animation_mip_review'
                priority = 3
                action = 'Provare mipmap con la stessa politica su tutti i fotogrammi; verificare scintillio e contorni alpha.'
            elif missing:
                group = 'environment_mip_trial'
                priority = 2
                action = 'Provare mipmap durante riduzione/zoom; verificare bordi alpha, UV e texture ripetute.'
            else:
                group = 'existing_mips_visual_review'
                priority = 4
                action = 'Mipmap già presenti: conservare; modificare filtro/bias solo se un confronto mostra un problema.'
            if atlas and (missing or point):
                action += ' Atlante: prima analizzare rettangoli, gutter e UV; generare riduzioni per regioni isolate, non mescolare sprite vicini.'
            extra = 0
            if missing:
                w, h = width, height
                channels = 3 if texture['format'] == 3 else 4
                while w > 1 or h > 1:
                    w, h = max(1, w // 2), max(1, h // 2)
                    extra += w * h * channels
            rows.append({
                'id': texture['id'], 'name': texture['name'], 'category': original['category'],
                'size': texture['size'], 'low_variant': original['low_variant'],
                'main_card_illustration': texture['id'] in card_ids,
                'filter': FILTERS[settings['m_FilterMode']], 'settings': settings,
                'mip_count': d['m_MipCount'], 'full_mip_count': int(math.log2(max(width, height))) + 1,
                'missing_mips': missing, 'atlas': atlas,
                'sprite_count': original['sprite_count'],
                'ngui_atlases': refs, 'priority': priority, 'review_group': group,
                'action': action, 'estimated_extra_mip_bytes': extra,
                'visible_aliasing_confirmed': False,
                'review_qualification': 'Classificazione preliminare da metadati e nomi. Nessuna misura della dimensione sullo schermo o prova in gioco.',
            })
        print('Checked', file['file'], len(file['textures']), flush=True)
    assert len(rows) == 2059 and len({r['id'] for r in rows}) == 2059
    main_cards = [r for r in rows if r['main_card_illustration']]
    assert len(main_cards) == 288 and all(r['mip_count'] > 1 for r in main_cards)
    summary = {
        'checked_textures': len(rows), 'single_level_textures': sum(r['mip_count'] == 1 for r in rows),
        'missing_mips_nonconstant': sum(r['missing_mips'] for r in rows),
        'constant_2x2': sum(r['review_group'] == 'preserve_constant' for r in rows),
        'point_filtered': sum(r['filter'] == 'Point' for r in rows),
        'main_cards_already_mipped': len(main_cards),
        'filter_counts': dict(Counter(r['filter'] for r in rows)),
        'review_groups': dict(Counter(r['review_group'] for r in rows)),
        'missing_by_category': dict(Counter(r['category'] for r in rows if r['missing_mips'])),
        'missing_atlases': sum(r['missing_mips'] and r['atlas'] for r in rows),
        'additional_full_chain_mib_estimate': round(sum(r['estimated_extra_mip_bytes'] for r in rows) / 1024**2, 1),
    }
    report = {'status': 'audit_complete', 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'game_modified': False, 'game_launched': False, 'unity_editor_used': False,
        'summary': summary, 'verified_serialized_sources': source_files,
        'patch_plan': {
            'phase_1': 'Ritratti, GUI/HUD, miniature carte, cornici e badge: mipmap protette per regione; filtro per i tre asset Point.',
            'phase_2': 'Elementi mappe/ambienti e texture autonome: mipmap, alpha corretto e controlli su UV/wrap.',
            'phase_3': 'Atlanti cinematiche ed effetti: politica identica tra fotogrammi e confronto in movimento.',
            'preservation': 'Base level 2×, alpha originale, ID, rettangoli, UV, geometria, script e salvataggi; conservare mipmap già presenti.',
            'resolution_policy': 'Mipmap per riduzione automatica; varianti low_ esistenti da conservare. Ridurre il livello base solo per asset dimostrati esclusivamente piccoli.',
            'acceptance': 'Confronti A/B alla dimensione effettiva in 1920×1080 e HiDPI, zoom/animazioni, nessun alone o colore di sprite adiacente, testo leggibile.',
        }, 'textures': rows}
    (OUT / 'audit.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    candidates = sorted((r for r in rows if r['missing_mips'] or r['filter'] == 'Point'), key=lambda r: (r['priority'], r['category'], r['name']))
    lines = ['CARD WARS — CAMPIONAMENTO E ANTI-ALIASING', '',
        'Audit completato: gioco non modificato e non avviato.',
        'I candidati indicano rischio di aliasing: la presenza di un difetto visibile richiede confronto in gioco.', '',
        json.dumps(summary, indent=2, ensure_ascii=False), '', 'ORDINE DEGLI INTERVENTI',
        *[f'{k}: {v}' for k, v in report['patch_plan'].items()], '', 'CANDIDATI']
    for r in candidates:
        lines.extend([f"P{r['priority']} | {r['id']} | {r['name']} | {r['size'][0]}×{r['size'][1]} | {r['filter']} | {r['mip_count']} livelli",
            r['action'], ''])
    (OUT / 'interventi.txt').write_text('\n'.join(lines))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
