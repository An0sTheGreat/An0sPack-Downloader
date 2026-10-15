"""Author-side 'compile': turn a working MO2 instance into an .an0s install package (the Wabbajack .wabbajack equivalent).

    python compiler.py --base W:\\An0sPack --mo2 "Z:\\...\\MO2" --profile "An0sPack - CS" [--out data/profiles/<profile>.an0s]

Every file of every enabled mod (and of the MO2 program folder) is matched by (size, CRC32) against the contents of the archives the
profile downloads; matches become directives "take <inner path> from <archive>", the rest is stored inline. Game Root is recorded as a
list of game files to copy from the user's own Skyrim. Nothing under --base is modified.
"""
import argparse, collections, json, os, re, subprocess, sys, tempfile, time, zipfile, zlib
from concurrent.futures import ThreadPoolExecutor

import core, skse

SKIP_ROOT = {"logs", "crashdumps", "explorer++", "plugins2", "webcache", "__pycache__"}  # MO2 program-folder entries that are not part of a modlist
SKIP_FILES = ("unins000.", "nxmhandler.", "modorganizer.ini", "mod organizer 2-")
ALWAYS = {"splash.png", "categories.dat", "nexuscatmap.dat"}  # author customisations of files that also exist in vanilla MO2
MIN_INDEX = 1  # files of size 0 are recreated, never matched


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fwd(p):
    return p.replace("\\", "/")


def crc_file(path):
    c = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(8 << 20)
            if not b:
                return c
            c = zlib.crc32(b, c)


class CrcCache:
    """(path,size,mtime) -> crc, persisted so a re-run only re-reads changed files"""

    def __init__(self, path):
        self.path, self.d = path, {}
        try:
            self.d = json.load(open(path, encoding="utf8"))
        except Exception:
            pass

    def get(self, p):
        st = os.stat(p)
        k = f"{p}|{st.st_size}|{st.st_mtime_ns}"
        if k not in self.d:
            self.d[k] = crc_file(p)
        return st.st_size, self.d[k]

    def save(self):
        json.dump(self.d, open(self.path, "w", encoding="utf8"))


def walk(root, skip_top=()):
    out = []
    for d, dirs, files in os.walk(root):
        if d == root:
            dirs[:] = [x for x in dirs if x.lower() not in skip_top]
        for f in files:
            full = os.path.join(d, f)
            out.append((fwd(os.path.relpath(full, root)), full))
    return out


def list_archive(path):
    """[(inner, size, crc)] of every file in the archive, via `7z l -slt`"""
    r = subprocess.run([skse.seven_zip(), "l", "-slt", "-ba", "-sccUTF-8", path], capture_output=True, creationflags=0x08000000)
    ents, cur = [], {}
    for ln in r.stdout.decode("utf-8", "replace").splitlines() + [""]:
        if ln.strip() == "":
            if cur.get("Path") and cur.get("Folder") != "+" and cur.get("CRC") and "D" not in cur.get("Attributes", "")[:2]:
                try:
                    ents.append((fwd(cur["Path"]), int(cur["Size"]), int(cur["CRC"], 16)))
                except ValueError:
                    pass
            cur = {}
        elif " = " in ln:
            k, v = ln.split(" = ", 1)
            cur[k] = v
    return ents


def source_of(row):
    if row.get("script"):
        return {"t": "script", "script": row["script"]}
    if row["modid"]:
        return {"t": "nexus", "game": row["game"] or core.SK, "mod": row["modid"], "file": row["fileid"]}
    if row.get("dl"):
        return {"t": "url", "url": row["dl"], "name": row["file"]}
    return {"t": "manual", "name": row["file"]}


def clean_ini(lines):
    """ModOrganizer.ini template: drop the author's tool shortcuts (tools/ is not shipped) and renumber the rest; drop the instance version"""
    out, sec, ex = [], "", {}
    for ln in lines:
        if ln.startswith("["):
            sec = ln.strip("[]")
        if sec == "customExecutables" and re.match(r"\d+\\", ln):
            n, rest = ln.split("\\", 1)
            ex.setdefault(int(n), []).append(rest)
            continue
        if sec == "customExecutables" and ln.startswith("size="):
            continue
        if sec == "General" and ln.startswith("version="):
            continue
        out.append(ln)
        if ln.strip() == "[customExecutables]":
            out.append("%%EXECUTABLES%%")
    keep = [v for _, v in sorted(ex.items()) if not any("/tools/" in x.replace("\\\\", "/") and x.startswith("binary=") for x in v)]
    block = [f"size={len(keep)}"] + [f"{i}\\{x}" for i, v in enumerate(keep, 1) for x in v]
    i = out.index("%%EXECUTABLES%%")
    return out[:i] + block + out[i + 1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--mo2", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out")
    ap.add_argument("--only", help="regex: compile only mods whose folder name matches (testing)")
    ap.add_argument("--no-game", action="store_true")
    a = ap.parse_args()
    base, mo2, prof = a.base, a.mo2, a.profile
    dl = os.path.join(base, "downloads")
    out = a.out or os.path.join(core.PROFILES, prof + ".an0s")
    work = os.path.join(base, "work", "compile")
    os.makedirs(work, exist_ok=True)
    cache = CrcCache(os.path.join(work, "crc_cache.json"))
    profile = next(p for p in core.list_profiles() if p["name"] == prof)
    by_meta = core.meta_ids(dl)

    # ---- 1. archives the profile downloads (+ MO2 itself and the Root Builder plugin)
    skse_dir = os.path.join(work, "skse")
    os.makedirs(skse_dir, exist_ok=True)
    skse_zip = os.path.join(skse_dir, skse.ARCHIVE)
    if not os.path.exists(skse_zip):
        log("building SKSE archive")
        skse.build_archive(skse_dir)
    required = os.path.join(base, "An0sPack Required Files.zip")  # what is uploaded as Nexus 194071
    archives, by_path = [], {}

    def add_archive(path, src, name=None):
        key = os.path.normcase(path)
        if key in by_path:
            return by_path[key]
        by_path[key] = len(archives)
        archives.append({"id": len(archives), "name": name or os.path.basename(path), "size": os.path.getsize(path), "src": src, "path": path})
        return by_path[key]

    unresolved = []
    for row in profile["mods"]:
        p = None
        if row.get("script") == "skse":
            p = skse_zip
        elif row["modid"] == 194071:
            p = required
        elif row["file"] and os.path.exists(os.path.join(dl, row["file"])):
            p = os.path.join(dl, row["file"])
        elif row["modid"] and row["fileid"] and (row["modid"], row["fileid"]) in by_meta:
            p = by_meta[(row["modid"], row["fileid"])]
        if p:
            src = source_of(row)
            if src["t"] == "manual" or (src["t"] == "nexus" and not src["file"]):
                src = {"t": "manual", "name": os.path.basename(p)}
            add_archive(p, src)
        else:
            unresolved.append(row["name"])
    mo2_arch = add_archive(os.path.join(dl, "2fb7257c4a53-Mod.Organizer-2.5.2.7z"), {"t": "url", "url": "https://github.com/ModOrganizer2/modorganizer/releases/download/v2.5.2/Mod.Organizer-2.5.2.7z", "name": "Mod.Organizer-2.5.2.7z"})
    rb = [p for (m, i), p in by_meta.items() if m == 31720]
    if rb:
        add_archive(rb[0], {"t": "nexus", "game": core.SK, "mod": 31720, "file": next(i for (m, i), p in by_meta.items() if p == rb[0])})
    log(f"{len(archives)} archives; rows without a local archive: {unresolved}")

    # ---- 2. index archive contents
    idx = collections.defaultdict(list)  # (size, crc) -> [(arch id, inner)]
    entries = {}  # arch id -> [(inner, size, crc)]

    def index(arch):
        return arch["id"], list_archive(arch["path"])
    with ThreadPoolExecutor(6) as ex:
        for aid, ents in ex.map(index, archives):
            entries[aid] = ents
            for inner, size, crc in ents:
                if size >= MIN_INDEX:
                    idx[(size, crc)].append((aid, inner))
    log(f"indexed {sum(len(v) for v in entries.values())} archive entries")

    # ---- 3. match mod folders
    modlist = open(os.path.join(base, "profiles", prof, "modlist.txt"), encoding="utf8", errors="ignore").read().splitlines()
    names = [l[1:].strip() for l in modlist if l.startswith("+")]
    seps = [l[1:].strip() for l in modlist if l.startswith("-") and l.strip().endswith("_separator")]
    if a.only:
        names = [n for n in names if re.search(a.only, n, re.I)]
        seps = []
    inline, inline_src = {}, {}  # dest -> member ; member -> source path
    member_for = {}  # (size,crc) -> member
    groups, meta, stats = [], {}, collections.Counter()

    def put_inline(dest, full, size, crc):
        m = member_for.get((size, crc))
        if m is None:
            m = member_for[(size, crc)] = f"inline/{len(member_for)}"
            inline_src[m] = full
            stats["inline_bytes"] += size
        inline[dest] = m
        stats["inline_files"] += 1

    def process(root_dest, root_dir, files, prefer=None, name=""):
        """files: [(rel, full)] -> groups/inline entries"""
        matched = collections.defaultdict(list)
        for rel, full in files:
            size, crc = cache.get(full)
            if size == 0:
                put_inline(f"{root_dest}{rel}", full, 0, 0)
                continue
            cands = idx.get((size, crc))
            if not cands:
                put_inline(f"{root_dest}{rel}", full, size, crc)
                continue
            pick = [c for c in cands if c[0] == prefer] or [c for c in cands if c[1].lower().endswith(rel.lower())] or cands
            matched[pick[0][0]].append((pick[0][1], rel))
            stats["matched_bytes"] += size
        for aid, pairs in matched.items():
            inner0, rel0 = pairs[0]
            pre = inner0[:len(inner0) - len(rel0)] if inner0.lower().endswith(rel0.lower()) else None
            if pre is not None and all(i.lower() == (pre + r).lower() for i, r in pairs):
                under = [e for e in entries[aid] if e[0].lower().startswith(pre.lower()) and e[1] > 0]
                if len(under) == len(pairs):
                    groups.append({"to": root_dest, "a": aid, "strip": pre, "all": True})
                else:
                    groups.append({"to": root_dest, "a": aid, "strip": pre, "files": [r for _, r in pairs]})
            else:
                groups.append({"to": root_dest, "a": aid, "pairs": [[i, r] for i, r in pairs]})

    def folder_job(n):
        root = os.path.join(base, "mods", n)
        if not os.path.isdir(root):
            return n, None, None
        ini = core._ini(os.path.join(root, "meta.ini"))
        prefer = None
        f = os.path.basename(ini.get(("General", "installationFile"), "").replace("\\", "/"))
        if f:
            prefer = by_path.get(os.path.normcase(os.path.join(dl, f)))
        files = [(r, p) for r, p in walk(root) if r.lower() != "meta.ini"]
        keep = {k: v for (s, k), v in ini.items() if s == "General" and k in ("gameName", "modid", "version", "installationFile", "category", "repository", "comments", "notes", "color", "hasCustomURL", "url", "newestVersion")}
        return n, (files, prefer), keep

    log(f"matching {len(names) + len(seps)} mod folders")
    t0 = time.time()
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(folder_job, names + seps))
    # CRC reading happens inside process() (single-threaded bookkeeping); warm the cache in parallel first
    allfiles = [p for _, job, _ in results if job for _, p in job[0]]
    log(f"hashing {len(allfiles)} files")
    done = [0]

    def warm(p):
        cache.get(p)
        done[0] += 1
        if done[0] % 5000 == 0:
            log(f"  hashed {done[0]}/{len(allfiles)}")
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(warm, allfiles))
    cache.save()
    log(f"hashed in {time.time() - t0:.0f}s")
    missing = []
    for n, job, keep in results:
        if job is None:
            missing.append(n)
            continue
        meta[n] = keep
        process(f"mods/{n}/", None, job[0], job[1], n)
    log("mod folders missing on disk:", missing)

    # ---- 4. MO2 program folder: official 2.5.2 as shipped, Root Builder from Nexus, plus only what the author ADDED (paths absent from 2.5.2).
    # The author's own MO2 is a newer Qt6 build; its binaries are deliberately not carried over.
    vanilla = {e[0].lower() for e in entries[mo2_arch]}
    groups.append({"to": "", "a": mo2_arch, "strip": "", "all": True})
    mo2_extra = []
    for rel, full in walk(mo2, SKIP_ROOT):
        low = rel.lower()
        if low.endswith(".pyc") or any(low.startswith(s) or os.path.basename(low).startswith(s) for s in SKIP_FILES):
            continue
        if low.startswith(("plugins/data/rootbuilder", "plugins/plugin_python", "qml/", "translations/", "dlls/", "licenses/", "styles/", "resources/", "loot/")):
            continue
        if low in ALWAYS or low.startswith(("stylesheets/", "plugins/rootbuilder/")):  # everything else of the author's newer build is dropped
            mo2_extra.append((rel, full))
    log(f"MO2 additions: {len(mo2_extra)} files")
    process("", mo2, mo2_extra, None, "MO2")
    ini_text = open(os.path.join(mo2, "ModOrganizer.ini"), encoding="utf8", errors="ignore").read()

    # ---- 5. profile files
    pdir = os.path.join(base, "profiles", prof)
    for rel, full in walk(pdir, {"saves"}):
        if rel == "modlist.txt":
            keep = [l for l in modlist if l.startswith(("#", "*")) or (l[:1] == "+" and (not a.only or l[1:].strip() in names)) or l.strip().endswith("_separator")]
            full = os.path.join(work, "modlist.txt")
            open(full, "w", encoding="utf8", newline="\r\n").write("\n".join(keep) + "\n")
        size, crc = cache.get(full) if rel != "modlist.txt" else (os.path.getsize(full), crc_file(full))
        put_inline(f"profiles/{prof}/{rel}", full, size, crc)

    # ---- 6. Game Root (copied from the user's Skyrim at install time)
    game = []
    if not a.no_game:
        groot = os.path.join(base, "Game Root")
        # only real game files: Game Root also holds dev/tool leftovers (.claude, tools, .git*, Root Builder backups) that must never be listed
        gf = [(r, p) for r, p in walk(groot) if not any(x.startswith(".") for x in r.split("/")) and not r.lower().startswith(("tools/", "data/backup/"))]
        log(f"hashing {len(gf)} game files")
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(lambda rp: (rp[0],) + cache.get(rp[1]), gf))
        cache.save()
        game = [[r, s, c] for r, s, c in res]
        # base-game files the author edited (cleaned masters, repacked BSAs) differ from the stock depot copy; flag them so installs fall back to the stock version
        import installer
        depots = installer.steam_depot_dirs(None)
        edited = 0
        for g in game:
            if installer.critical(g[0]):
                hit = [os.path.join(d, g[0].replace("/", os.sep)) for d in depots if os.path.exists(os.path.join(d, g[0].replace("/", os.sep)))]
                if hit and tuple(cache.get(hit[0])) != (g[1], g[2]):
                    g.append(1)
                    edited += 1
        cache.save()
        log(f"{edited} critical game files differ from the stock depot copies (flagged)")
        stats["game_bytes"] = sum(s for _, s, _ in res)

    # ---- 7. ModOrganizer.ini template: install/game paths become tokens, per-machine sections dropped
    ini = []
    skip_sec = False
    for ln in ini_text.splitlines():
        if ln.startswith("["):
            skip_sec = ln.strip("[]") in ("recentDirectories", "Geometry", "Widgets", "CompletedWindowTutorials", "Servers", "PluginPersistance")
        if skip_sec and not ln.startswith("["):
            continue
        if ln.startswith(("base_directory=", "gamePath=", "download_directory=", "mod_directory=")):
            continue
        ln = re.sub(r"[A-Za-z]:[\\/]+(=GAME MODDING=[\\/]+SKYRIM MODDING TOOLS[\\/]+MO2|An0sPack)", lambda m: "%%INSTALL%%", ln)
        ini.append(ln.replace("External - SKSE [e7e73f36]", "Skyrim Script Extender"))
    ini = clean_ini(ini)

    # ---- 8. write the package
    arch_out = [{k: v for k, v in x.items() if k != "path"} for x in archives]
    gexe = next((g for g in game if g[0].lower() == "skyrimse.exe"), None)
    manifest = {"version": 1, "name": prof, "profile": prof, "game": "SkyrimSE", "game_exe": gexe, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "archives": arch_out, "groups": groups, "inline": inline, "meta": meta, "game_files": game, "ini": ini, "mo2": mo2_arch,
                "stats": {**stats, "download_bytes": sum(x["size"] for x in archives if x["src"]["t"] != "manual")}}
    tmp = out + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
        for m, full in inline_src.items():
            z.write(full, m)
    os.replace(tmp, out)
    log(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB) | groups {len(groups)}, inline files {stats['inline_files']} = {stats['inline_bytes'] / 1e6:.1f} MB, "
        f"matched {stats['matched_bytes'] / 1e9:.1f} GB, game {stats.get('game_bytes', 0) / 1e9:.1f} GB")


if __name__ == "__main__":
    main()
