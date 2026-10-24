#!/usr/bin/env python3
"""Make Chimera's app icons from chimera_icon.png.

Writes chimera.icns (macOS), chimera.ico (Windows) and, in the Go package
folder, rsrc_windows_amd64.syso so the Windows build gets the icon.
Needs Pillow. Usage: python3 make_icons.py path/to/chimera_icon.png
"""
import io, os, struct, sys
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)


def rounded(src, size, radius_frac, margin_frac, shadow=False):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = int(round(size * (1 - 2 * margin_frac)))
    off = (size - inner) // 2
    if shadow:
        sh = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        m = Image.new("L", (size, size), 0)
        ImageDraw.Draw(m).rounded_rectangle([off, off + size * 0.012, off + inner, off + inner + size * 0.012], radius=inner * radius_frac, fill=110)
        m = m.filter(ImageFilter.GaussianBlur(size * 0.012))
        sh.putalpha(m)
        canvas = Image.alpha_composite(canvas, sh)
    im = src.resize((inner, inner), Image.LANCZOS)
    scale = 4
    mask = Image.new("L", (inner * scale, inner * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, inner * scale - 1, inner * scale - 1], radius=int(inner * scale * radius_frac), fill=255)
    mask = mask.resize((inner, inner), Image.LANCZOS)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer.paste(im, (off, off), mask)
    return Image.alpha_composite(canvas, layer)


def png_bytes(img):
    b = io.BytesIO()
    img.save(b, format="PNG", optimize=True)
    return b.getvalue()


def write_syso(images, path):
    """A COFF object with RT_ICON + RT_GROUP_ICON resources for Go's linker."""
    RT_ICON, RT_GROUP_ICON, LANG = 3, 14, 0x0409
    n = len(images)
    grp = struct.pack("<HHH", 0, 1, n)
    for i, (w, h, data) in enumerate(images, 1):
        grp += struct.pack("<BBBBHHIH", w if w < 256 else 0, h if h < 256 else 0, 0, 0, 1, 32, len(data), i)

    def dir_size(entries):
        return 16 + 8 * entries

    # layout: root, icon-type dir, group-type dir, n icon lang dirs, 1 group lang dir, data entries, blobs
    off_root = 0
    off_icon_dir = off_root + dir_size(2)
    off_group_dir = off_icon_dir + dir_size(n)
    off_icon_lang = [off_group_dir + dir_size(1) + i * dir_size(1) for i in range(n)]
    off_group_lang = off_group_dir + dir_size(1) + n * dir_size(1)
    off_data_entries = off_group_lang + dir_size(1)
    off_icon_data_entry = [off_data_entries + 16 * i for i in range(n)]
    off_group_data_entry = off_data_entries + 16 * n
    pos = off_group_data_entry + 16
    blobs, blob_offsets = [], []
    for _, _, data in images:
        pos = (pos + 7) & ~7
        blob_offsets.append(pos)
        blobs.append(data)
        pos += len(data)
    pos = (pos + 7) & ~7
    grp_offset = pos
    pos += len(grp)
    raw = bytearray((pos + 7) & ~7)
    relocs = []

    def put_dir(at, entries):
        named = 0
        struct.pack_into("<IIHHHH", raw, at, 0, 0, 0, 0, named, len(entries))
        for k, (ident, target, is_dir) in enumerate(entries):
            struct.pack_into("<II", raw, at + 16 + 8 * k, ident, target | (0x80000000 if is_dir else 0))

    def put_data_entry(at, data_off, size):
        struct.pack_into("<IIII", raw, at, data_off, size, 0, 0)
        relocs.append(at)  # OffsetToData becomes an RVA when linked

    put_dir(off_root, [(RT_ICON, off_icon_dir, True), (RT_GROUP_ICON, off_group_dir, True)])
    put_dir(off_icon_dir, [(i + 1, off_icon_lang[i], True) for i in range(n)])
    put_dir(off_group_dir, [(1, off_group_lang, True)])
    for i in range(n):
        put_dir(off_icon_lang[i], [(LANG, off_icon_data_entry[i], False)])
        put_data_entry(off_icon_data_entry[i], blob_offsets[i], len(blobs[i]))
    put_dir(off_group_lang, [(LANG, off_group_data_entry, False)])
    put_data_entry(off_group_data_entry, grp_offset, len(grp))
    for o, b in zip(blob_offsets, blobs):
        raw[o:o + len(b)] = b
    raw[grp_offset:grp_offset + len(grp)] = grp

    IMAGE_REL_AMD64_ADDR32NB = 3
    hdr_size, sec_size = 20, 40
    p_raw = hdr_size + sec_size
    p_rel = p_raw + len(raw)
    p_sym = p_rel + 10 * len(relocs)
    out = bytearray()
    out += struct.pack("<HHIIIHH", 0x8664, 1, 0, p_sym, 1, 0, 0)
    out += struct.pack("<8sIIIIIIHHI", b".rsrc", 0, 0, len(raw), p_raw, p_rel, 0, len(relocs), 0, 0x40000040)
    out += raw
    for r in relocs:
        out += struct.pack("<IIH", r, 0, IMAGE_REL_AMD64_ADDR32NB)
    out += struct.pack("<8sIhHBB", b".rsrc", 0, 1, 0, 3, 0)
    out += struct.pack("<I", 4)  # empty string table
    with open(path, "wb") as f:
        f.write(out)


def main():
    src_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(APP, "..", "chimera_icon.png")
    src = Image.open(src_path).convert("RGBA")

    # macOS: Big Sur style grid (824 of 1024, ~22% corner radius) with a soft shadow.
    mac = rounded(src, 1024, 0.225, 0.0977, shadow=True)
    mac.save(os.path.join(HERE, "chimera.icns"), format="ICNS")
    mac.save(os.path.join(HERE, "icon-1024.png"))

    # Windows: rounded square, small margin.
    sizes = [16, 24, 32, 48, 64, 128, 256]
    win_imgs = []
    for s in sizes:
        im = rounded(src, s, 0.2, 0.03 if s >= 32 else 0.0)
        win_imgs.append((s, s, png_bytes(im)))
    big = rounded(src, 256, 0.2, 0.03)
    big.save(os.path.join(HERE, "chimera.ico"), format="ICO", sizes=[(s, s) for s in sizes])
    write_syso(win_imgs, os.path.join(APP, "rsrc_windows_amd64.syso"))
    print("wrote chimera.icns, chimera.ico, rsrc_windows_amd64.syso")


if __name__ == "__main__":
    main()
