#!/usr/bin/env python3
"""Ad-hoc sign Chimera.app so the whole bundle passes macOS's checks.

Go's linker signs the executable alone and marks it "linker-signed". That
runs fine, but once the app picks up a download flag (AirDrop, Messages, a
browser), macOS checks the bundle, finds no sealed resources and no bound
Info.plist, and calls the app damaged. This writes a complete ad-hoc
signature like `codesign -s -` would: _CodeSignature/CodeResources plus a
CodeDirectory that binds Info.plist, the requirements and the resources.

It doesn't need a Mac. On a Mac, `codesign --force --deep -s -` does the same.

Usage: sign_macos.py path/to/Chimera.app [bundle-identifier]
       sign_macos.py --selftest path/to/binary   (checks the hashing against Go's own signature)
"""
import base64
import hashlib
import os
import plistlib
import struct
import sys

PAGE = 4096
CSMAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
CSMAGIC_CODEDIRECTORY = 0xFADE0C02
CSMAGIC_REQUIREMENTS = 0xFADE0C01
CSMAGIC_BLOBWRAPPER = 0xFADE0B01
LC_SEGMENT_64 = 0x19
LC_CODE_SIGNATURE = 0x1D
CD_HEADER = 88  # CodeDirectory v0x20400 header size


def parse_macho(b):
    magic, cputype, _, _, ncmds, _, _, _ = struct.unpack_from("<IiiIIIII", b, 0)
    if magic != 0xFEEDFACF:
        raise SystemExit("not a 64-bit little-endian Mach-O (universal binaries aren't supported)")
    off = 32
    info = {"segments": {}, "cs": None}
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", b, off)
        if cmd == LC_SEGMENT_64:
            name = b[off + 8:off + 24].rstrip(b"\0").decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", b, off + 24)
            info["segments"][name] = {"cmd_off": off, "vmaddr": vmaddr, "vmsize": vmsize, "fileoff": fileoff, "filesize": filesize}
        elif cmd == LC_CODE_SIGNATURE:
            dataoff, datasize = struct.unpack_from("<II", b, off + 8)
            info["cs"] = {"cmd_off": off, "dataoff": dataoff, "datasize": datasize}
        off += size
    if info["cs"] is None:
        raise SystemExit("binary has no LC_CODE_SIGNATURE load command")
    return info


def code_directory(data, code_limit, ident, flags, special, exec_base, exec_limit, exec_flags):
    """special: list of slot hashes, index 0 = slot 1 (Info.plist), 1 = slot 2, ..."""
    ident_b = ident.encode() + b"\0"
    n_special = len(special)
    n_code = (code_limit + PAGE - 1) // PAGE
    hash_off = CD_HEADER + len(ident_b) + 32 * n_special
    length = hash_off + 32 * n_code
    out = bytearray()
    out += struct.pack(">IIIIIIIII", CSMAGIC_CODEDIRECTORY, length, 0x20400, flags, hash_off, CD_HEADER, n_special, n_code, code_limit)
    out += struct.pack(">BBBB", 32, 2, 0, 12)          # hashSize, SHA-256, pad, log2(page)
    out += struct.pack(">IIII", 0, 0, 0, 0)            # pad2, scatterOffset, teamOffset, pad3
    out += struct.pack(">QQQQ", 0, exec_base, exec_limit, exec_flags)
    assert len(out) == CD_HEADER
    out += ident_b
    for h in reversed(special):                        # slot -n first
        out += h
    for p in range(0, code_limit, PAGE):
        out += hashlib.sha256(bytes(data[p:min(p + PAGE, code_limit)])).digest()
    assert len(out) == length
    return bytes(out)


def super_blob(blobs):
    """blobs: list of (slot type, bytes)."""
    header = 12 + 8 * len(blobs)
    index, body, off = b"", b"", header
    for typ, blob in blobs:
        index += struct.pack(">II", typ, off)
        body += blob
        off += len(blob)
    return struct.pack(">III", CSMAGIC_EMBEDDED_SIGNATURE, off, len(blobs)) + index + body


def read_go_signature(b, cs):
    sig = b[cs["dataoff"]:cs["dataoff"] + cs["datasize"]]
    magic, length, count = struct.unpack_from(">III", sig, 0)
    assert magic == CSMAGIC_EMBEDDED_SIGNATURE
    typ, off = struct.unpack_from(">II", sig, 12)
    cd = sig[off:]
    ident_off = struct.unpack_from(">I", cd, 20)[0]
    ident = cd[ident_off:cd.index(b"\0", ident_off)].decode()
    flags = struct.unpack_from(">I", cd, 12)[0]
    exec_base, exec_limit, exec_flags = struct.unpack_from(">QQQ", cd, 64)
    return sig[:length], ident, flags, exec_base, exec_limit, exec_flags


def selftest(path):
    b = open(path, "rb").read()
    info = parse_macho(b)
    cs = info["cs"]
    original, ident, flags, eb, el, ef = read_go_signature(b, cs)
    cd = code_directory(b, cs["dataoff"], ident, flags, [], eb, el, ef)
    rebuilt = super_blob([(0, cd)])
    ok = rebuilt == original
    print(f"selftest: rebuilt Go's signature for '{ident}' ({len(original)} bytes): {'identical' if ok else 'DIFFERENT'}")
    return ok


CODE_RESOURCES_RULES = {
    "rules": {
        "^Resources/": True,
        "^Resources/.*\\.lproj/": {"optional": True, "weight": 1000.0},
        "^Resources/.*\\.lproj/locversion.plist$": {"omit": True, "weight": 1100.0},
        "^Resources/Base\\.lproj/": {"weight": 1010.0},
        "^version.plist$": True,
    },
    "rules2": {
        ".*\\.dSYM($|/)": {"weight": 11.0},
        "^(.*/)?\\.DS_Store$": {"omit": True, "weight": 2000.0},
        "^(Frameworks|SharedFrameworks|PlugIns|Plug-ins|XPCServices|Helpers|MacOS|Library/(Automator|Spotlight|LoginItems))/": {"nested": True, "weight": 10.0},
        "^.*": True,
        "^Info\\.plist$": {"omit": True, "weight": 20.0},
        "^PkgInfo$": {"omit": True, "weight": 20.0},
        "^Resources/": {"weight": 20.0},
        "^Resources/.*\\.lproj/": {"optional": True, "weight": 1000.0},
        "^Resources/.*\\.lproj/locversion.plist$": {"omit": True, "weight": 1100.0},
        "^Resources/Base\\.lproj/": {"weight": 1010.0},
        "^[^/]+$": {"nested": True, "weight": 10.0},
        "^embedded\\.provisionprofile$": {"weight": 20.0},
        "^version\\.plist$": {"weight": 20.0},
    },
}


def sign_bundle(app, identifier=None):
    contents = os.path.join(app, "Contents")
    info_path = os.path.join(contents, "Info.plist")
    info_bytes = open(info_path, "rb").read()
    info = plistlib.loads(info_bytes)
    exe_name = info["CFBundleExecutable"]
    identifier = identifier or info.get("CFBundleIdentifier") or exe_name
    exe_path = os.path.join(contents, "MacOS", exe_name)

    # Seal every resource except the main executable, Info.plist and the signature itself.
    files, files2 = {}, {}
    for root, _, names in os.walk(contents):
        for n in names:
            full = os.path.join(root, n)
            rel = os.path.relpath(full, contents).replace(os.sep, "/")
            if rel in ("Info.plist", "MacOS/" + exe_name) or rel.startswith("_CodeSignature/") or n == ".DS_Store":
                continue
            if rel.startswith("MacOS/"):
                raise SystemExit(f"extra executable {rel} isn't supported by this signer")
            data = open(full, "rb").read()
            sha1, sha256 = hashlib.sha1(data).digest(), hashlib.sha256(data).digest()
            files[rel] = sha1
            files2[rel] = {"hash": sha1, "hash2": sha256}
    resources = {"files": files, "files2": files2, **CODE_RESOURCES_RULES}
    sigdir = os.path.join(contents, "_CodeSignature")
    os.makedirs(sigdir, exist_ok=True)
    res_bytes = plistlib.dumps(resources, fmt=plistlib.FMT_XML, sort_keys=True)
    with open(os.path.join(sigdir, "CodeResources"), "wb") as f:
        f.write(res_bytes)

    requirements = struct.pack(">III", CSMAGIC_REQUIREMENTS, 12, 0)
    special = [
        hashlib.sha256(info_bytes).digest(),      # slot 1: Info.plist
        hashlib.sha256(requirements).digest(),    # slot 2: requirements
        hashlib.sha256(res_bytes).digest(),       # slot 3: CodeResources
    ]

    b = bytearray(open(exe_path, "rb").read())
    m = parse_macho(b)
    cs = m["cs"]
    _, _, _, eb, el, ef = read_go_signature(b, cs)
    code_limit = cs["dataoff"]

    # Work out the new signature size first (it doesn't depend on the hashes' values).
    ident_len = len(identifier) + 1
    n_code = (code_limit + PAGE - 1) // PAGE
    cd_len = CD_HEADER + ident_len + 32 * len(special) + 32 * n_code
    wrapper = struct.pack(">II", CSMAGIC_BLOBWRAPPER, 8)
    sig_len = 12 + 8 * 3 + cd_len + len(requirements) + len(wrapper)
    datasize = (sig_len + 15) & ~15

    # Grow __LINKEDIT and the signature load command to fit, before hashing pages.
    le = m["segments"]["__LINKEDIT"]
    new_filesize = code_limit + datasize - le["fileoff"]
    new_vmsize = (new_filesize + 0x3FFF) & ~0x3FFF
    struct.pack_into("<QQQQ", b, le["cmd_off"] + 24, le["vmaddr"], max(new_vmsize, le["vmsize"]), le["fileoff"], new_filesize)
    struct.pack_into("<II", b, cs["cmd_off"] + 8, code_limit, datasize)

    cd = code_directory(b, code_limit, identifier, 0x2, special, eb, el, ef)  # flags: adhoc
    assert len(cd) == cd_len
    sig = super_blob([(0, cd), (2, requirements), (0x10000, wrapper)])
    assert len(sig) == sig_len
    out = bytes(b[:code_limit]) + sig + b"\0" * (datasize - sig_len)
    with open(exe_path, "wb") as f:
        f.write(out)
    os.chmod(exe_path, 0o755)
    print(f"signed {app} as {identifier} (ad-hoc, {len(files)} sealed resource(s))")
    return verify_bundle(app)


def verify_bundle(app):
    """Re-reads the bundle and checks every hash the signature claims."""
    contents = os.path.join(app, "Contents")
    info_bytes = open(os.path.join(contents, "Info.plist"), "rb").read()
    info = plistlib.loads(info_bytes)
    exe = open(os.path.join(contents, "MacOS", info["CFBundleExecutable"]), "rb").read()
    res_bytes = open(os.path.join(contents, "_CodeSignature", "CodeResources"), "rb").read()
    m = parse_macho(exe)
    cs = m["cs"]
    sig = exe[cs["dataoff"]:cs["dataoff"] + cs["datasize"]]
    magic, length, count = struct.unpack_from(">III", sig, 0)
    assert magic == CSMAGIC_EMBEDDED_SIGNATURE and count == 3, (hex(magic), count)
    slots = {}
    for i in range(count):
        typ, off = struct.unpack_from(">II", sig, 12 + 8 * i)
        slots[typ] = off
    cd_off = slots[0]
    cdm, cdlen, ver, flags, hash_off, ident_off, n_special, n_code, code_limit = struct.unpack_from(">IIIIIIIII", sig, cd_off)
    cd = sig[cd_off:cd_off + cdlen]
    assert cdm == CSMAGIC_CODEDIRECTORY and ver == 0x20400 and flags == 0x2 and code_limit == cs["dataoff"]
    req = sig[slots[2]:slots[2] + 12]
    want = {1: hashlib.sha256(info_bytes).digest(), 2: hashlib.sha256(req).digest(), 3: hashlib.sha256(res_bytes).digest()}
    for slot, h in want.items():
        assert cd[hash_off - 32 * slot:hash_off - 32 * (slot - 1)] == h, f"special slot {slot} mismatch"
    for i in range(n_code):
        page = exe[i * PAGE:min((i + 1) * PAGE, code_limit)]
        assert cd[hash_off + 32 * i:hash_off + 32 * (i + 1)] == hashlib.sha256(page).digest(), f"page {i} mismatch"
    le = m["segments"]["__LINKEDIT"]
    assert le["fileoff"] + le["filesize"] == len(exe), "__LINKEDIT doesn't end at end of file"
    resources = plistlib.loads(res_bytes)
    for rel, entry in resources["files2"].items():
        data = open(os.path.join(contents, rel), "rb").read()
        assert entry["hash2"] == hashlib.sha256(data).digest(), f"resource {rel} mismatch"
    ident = cd[ident_off:cd.index(b"\0", ident_off)].decode()
    cdhash = hashlib.sha256(cd).hexdigest()[:40]
    print(f"verified: identifier {ident}, {n_code} pages, Info.plist bound, {len(resources['files2'])} resource(s) sealed, cdhash {cdhash}")
    return True


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(0 if selftest(sys.argv[2]) else 1)
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sign_bundle(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
