#!/usr/bin/env python3
"""
fix_avb_footer.py - reubica el bloque AVB y reescribe el pie de una imagen modificada.

Idea (observada en Magisk y en vendor_boot_twrp_fix6): el bootloader desbloqueado
tolera que el hash/firma no coincidan, pero necesita una estructura AVB bien formada:
  contenido | bloque vbmeta firmado | ... ceros ... | pie de 64 bytes al final de la particion

Uso:
  fix_avb_footer.py IMAGEN --donor DUMP_ORIGINAL_DE_LA_PARTICION [-o SALIDA] [--tam N]
  fix_avb_footer.py --check IMAGEN

--donor es un volcado COMPLETO de la misma particion, original y con pie valido.
Solo copia de ahi el bloque firmado y los bytes reservados; no firma nada.
"""
import argparse, struct, sys

PAGE = 4096
al = lambda x: (x + PAGE - 1) // PAGE * PAGE


def read_footer(d):
    f = d[-64:]
    if f[:4] != b'AVBf':
        return None
    v1, v2, orig, off, size = struct.unpack_from('>IIQQQ', f, 4)
    return dict(v=(v1, v2), orig=orig, off=off, size=size, raw=bytes(f))


def content_end(d):
    """Fin del contenido real segun la cabecera (boot/vendor_boot v3-v4). Si no se reconoce, len(d)."""
    if d[:8] == b'ANDROID!':
        ks, rs = struct.unpack_from('<II', d, 8)
        ver, = struct.unpack_from('<I', d, 0x28)
        sig = struct.unpack_from('<I', d, 1580)[0] if ver >= 4 else 0
        return PAGE + al(ks) + al(rs) + al(sig)
    if d[:8] == b'VNDRBOOT':
        rsz, = struct.unpack_from('<I', d, 24)
        hs, dtb, _a, tab, _n, _e, bc = struct.unpack_from('<IIQIIII', d, 2096)
        return al(hs) + al(rsz) + al(dtb) + al(tab) + al(bc)
    return al(len(d))


def check(path):
    d = open(path, 'rb').read()
    f = read_footer(d)
    print(f'{path}: {len(d)} bytes, contenido segun cabecera termina en {content_end(d)}')
    if not f:
        print('  SIN pie AVB valido al final (AVBf no encontrado)')
        return 1
    ok = d[f['off']:f['off'] + 4] == b'AVB0'
    print(f"  pie: original_image_size={f['orig']} vbmeta_offset={f['off']} vbmeta_size={f['size']}")
    print(f"  bloque 'AVB0' en vbmeta_offset: {'SI' if ok else 'NO  <-- el pie apunta a basura'}")
    print(f"  coincide con el fin del contenido: {'SI' if f['off'] == content_end(d) else 'no (puede ser normal si hay relleno)'}")
    return 0 if ok else 2


def fix(img_path, donor_path, out_path, part_size):
    img = open(img_path, 'rb').read()
    donor = open(donor_path, 'rb').read()
    df = read_footer(donor)
    if not df or donor[df['off']:df['off'] + 4] != b'AVB0':
        sys.exit('El donor no tiene un pie AVB valido.')
    blob = donor[df['off']:df['off'] + df['size']]
    part_size = part_size or len(donor)
    C = content_end(img)
    if C > len(img):
        sys.exit(f'La imagen es mas corta que su contenido declarado ({len(img)} < {C}).')
    if C + len(blob) + 64 > part_size:
        sys.exit(f'No entra: contenido {C} + bloque {len(blob)} + pie 64 > particion {part_size}.')
    out = bytearray(part_size)
    out[:C] = img[:C]
    out[C:C + len(blob)] = blob
    footer = bytearray(df['raw'])
    struct.pack_into('>Q', footer, 12, C)   # original_image_size
    struct.pack_into('>Q', footer, 20, C)   # vbmeta_offset
    out[-64:] = footer
    open(out_path, 'wb').write(out)
    print(f'OK -> {out_path} ({part_size} bytes). Contenido: {C}. Bloque AVB movido a {C}.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('imagen')
    ap.add_argument('--donor')
    ap.add_argument('-o', '--out')
    ap.add_argument('--tam', type=int, help='tamano de la particion (por defecto el del donor)')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    if a.check:
        sys.exit(check(a.imagen))
    if not a.donor:
        ap.error('hace falta --donor (o usa --check)')
    fix(a.imagen, a.donor, a.out or a.imagen.rsplit('.', 1)[0] + '_fixed.img', a.tam)
