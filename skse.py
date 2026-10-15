"""SKSE64 -> An0sPack: download from the official source, stamp the An0sPack icon on skse64_loader.exe, lay out for Root Builder.
`stage()` is the one pipeline; the Downloader zips its output (`build_archive`), tools/build_skse.py drops it into the MO2 mod folder."""
import ctypes, os, shutil, struct, subprocess, sys, tempfile, zipfile

import httpx
import pefile

APP = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
RES = getattr(sys, "_MEIPASS", APP)
ICO = os.path.join(RES, "assets", "An0sPack.ico")
VERSION = "2_02_06"  # matches Skyrim SE/AE 1.6.1170 (runtime dll skse64_1_6_1170.dll)
URL = f"https://skse.silverlock.org/beta/skse64_{VERSION}.7z"
HOME = "https://skse.silverlock.org/"
ARCHIVE = "Skyrim Script Extender 2.02.06 (An0sPack Root).zip"
RT_ICON, RT_GROUP_ICON = 3, 14


class Cancelled(Exception):
    pass


def seven_zip():  # bundled copy first (7-Zip, LGPL: assets/7z), then any installed one
    for p in (os.path.join(RES, "assets", "7z", "7z.exe"), shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe"):
        if p and os.path.exists(p):
            return p
    raise FileNotFoundError("7z.exe not found")


def set_icon(exe, ico=ICO):
    """replace the exe's icon with every size in the .ico (UpdateResource; the SKSE loader is unsigned)"""
    data = open(ico, "rb").read()
    n = struct.unpack_from("<H", data, 4)[0]
    ents = [struct.unpack_from("<BBBBHHII", data, 6 + 16 * i) for i in range(n)]  # w,h,colors,rsv,planes,bits,size,offset
    pe = pefile.PE(exe, fast_load=True)
    pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    types = pe.DIRECTORY_ENTRY_RESOURCE.entries if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE") else []
    old, taken = {}, set()  # group id -> (lang, icon ids); icon ids in use
    for t in types:
        if t.id == RT_ICON:
            taken |= {e.id for e in t.directory.entries}
        elif t.id == RT_GROUP_ICON:
            for g in t.directory.entries:
                lang = g.directory.entries[0]
                raw = pe.get_data(lang.data.struct.OffsetToData, lang.data.struct.Size)
                old[g.id] = (lang.id, [struct.unpack_from("<H", raw, 6 + 14 * i + 12)[0] for i in range(struct.unpack_from("<H", raw, 4)[0])])
    pe.close()
    gid, (lang, oldids) = min(old.items()) if old else (1, (0, []))
    taken -= set(oldids)
    k32 = ctypes.windll.kernel32
    k32.BeginUpdateResourceW.restype = ctypes.c_void_p
    k32.UpdateResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ushort, ctypes.c_void_p, ctypes.c_ulong]
    k32.EndUpdateResourceW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    h = k32.BeginUpdateResourceW(exe, False)
    if not h:
        raise ctypes.WinError()

    def put(rtype, rid, blob):
        buf = ctypes.create_string_buffer(blob, len(blob)) if blob else None
        if not k32.UpdateResourceW(h, rtype, rid, lang, buf, len(blob)):
            raise ctypes.WinError()
    try:
        for i in oldids:
            put(RT_ICON, i, b"")  # empty data deletes the resource
        grp, rid = struct.pack("<HHH", 0, 1, n), 0
        for w, ht, c, rsv, planes, bits, size, off in ents:
            rid += 1
            while rid in taken:
                rid += 1
            put(RT_ICON, rid, data[off:off + size])
            grp += struct.pack("<BBBBHHIH", w, ht, c, rsv, planes, bits, size, rid)
        put(RT_GROUP_ICON, gid, grp)
    except BaseException:
        k32.EndUpdateResourceW(h, True)
        raise
    if not k32.EndUpdateResourceW(h, False):
        raise ctypes.WinError()


def stage(out, progress=lambda phase, done, total: None, cancelled=lambda: False):
    """download + brand + lay out into the empty dir `out`: Root/{skse64_loader.exe, skse64_*.dll}, Scripts/, src/, readmes"""
    def check():
        if cancelled():
            raise Cancelled()
    with tempfile.TemporaryDirectory() as tmp:
        arc = os.path.join(tmp, "skse.7z")
        with httpx.stream("GET", URL, follow_redirects=True, timeout=httpx.Timeout(30, read=60), headers={"User-Agent": "An0sPackDownloader"}) as r:
            r.raise_for_status()
            total, done = int(r.headers.get("content-length", 0)), 0
            with open(arc, "wb") as f:
                for chunk in r.iter_bytes(1 << 15):
                    check()
                    f.write(chunk)
                    done += len(chunk)
                    progress("Downloading", done, total)
        check()
        progress("Building", 0, 0)
        subprocess.run([seven_zip(), "x", "-y", f"-o{tmp}", arc], check=True, capture_output=True, creationflags=0x08000000)  # no console window
        src = os.path.join(tmp, f"skse64_{VERSION}")
        set_icon(os.path.join(src, "skse64_loader.exe"))
        root = os.path.join(out, "Root")
        os.makedirs(root)
        shutil.copy2(os.path.join(src, "skse64_loader.exe"), root)
        for f in os.listdir(src):
            if f.startswith("skse64_") and f.endswith(".dll"):
                shutil.copy2(os.path.join(src, f), root)
            elif f.endswith(".txt"):
                shutil.copy2(os.path.join(src, f), out)
        shutil.copytree(os.path.join(src, "Data", "Scripts"), os.path.join(out, "Scripts"))
        shutil.copytree(os.path.join(src, "src"), os.path.join(out, "src"))
        pe = pefile.PE(os.path.join(root, "skse64_loader.exe"))  # must still parse, icon intact
        assert any(t.id == RT_GROUP_ICON for t in pe.DIRECTORY_ENTRY_RESOURCE.entries), "icon missing after patch"
        pe.close()


def build_archive(dest, progress=lambda phase, done, total: None, cancelled=lambda: False):
    """stage and zip into dest/ARCHIVE (written via .part, so a failed run leaves nothing behind)"""
    final = os.path.join(dest, ARCHIVE)
    with tempfile.TemporaryDirectory() as out:
        stage(out, progress, cancelled)
        with zipfile.ZipFile(final + ".part", "w", zipfile.ZIP_DEFLATED) as z:
            for d, _, files in os.walk(out):
                for f in files:
                    p = os.path.join(d, f)
                    z.write(p, os.path.relpath(p, out))
    os.replace(final + ".part", final)
    return final
