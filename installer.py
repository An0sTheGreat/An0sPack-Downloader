"""An0sPack installer: apply an .an0s package (built by compiler.py) to an install folder - the Wabbajack 'install' step.

Flow (the GUI drives it): archives are downloaded to the download folder by core.Engine (tasks from `download_tasks`), then `install()`
  1. unpacks Mod Organizer 2 (portable) and every mod from the downloaded archives exactly as the author's instance had it,
  2. writes the files that only exist in the package (patches, configs),
  3. copies the game into <install>/Game Root from the user's own Skyrim SE folder,
  4. writes ModOrganizer.ini, the profile and portable.txt.
It is resumable: finished archives are recorded in <install>/.an0s/state.json and skipped on the next run.
"""
import json, os, re, shutil, subprocess, sys, zipfile, zlib

import core, skse

MARK = ".an0s"


def _protected():
    """folders Windows guards or syncs: Program Files, Windows, the user's Desktop/Downloads/Documents and OneDrive"""
    env = os.environ.get
    prof = env("USERPROFILE", "")
    out = [env("ProgramFiles"), env("ProgramFiles(x86)"), env("SystemRoot"), env("OneDrive"), env("OneDriveConsumer"), env("OneDriveCommercial")]
    out += [os.path.join(prof, d) for d in ("Desktop", "Downloads", "Documents", "OneDrive")] if prof else []
    return [os.path.normcase(os.path.abspath(p)) for p in out if p]


class Cancelled(Exception):
    pass


class InstallError(Exception):
    pass


def lp(p):
    """\\\\?\\ prefix so deep mod paths survive Windows' 260-character limit"""
    p = os.path.abspath(p)
    return p if p.startswith("\\\\?\\") else "\\\\?\\" + p


def load(pkg):
    with zipfile.ZipFile(pkg) as z:
        return json.loads(z.read("manifest.json"))


# ---------- checks ----------
def check_dirs(install, dl, game=""):
    """error text for an unusable install/download folder, or ''"""
    norm = lambda p: os.path.normcase(os.path.abspath(p))
    for what, p in (("Install", install), ("Download", dl)):
        if not p:
            return f"Choose an {what.lower()} folder."
        if os.path.dirname(norm(p)) == norm(p):
            return f"{what} folder can't be the root of a drive - pick or create a folder."
        if any(norm(p) == b or norm(p).startswith(b + os.sep) for b in _protected()):
            return f"{what} folder can't be inside Program Files, Windows, Desktop, Downloads, Documents or OneDrive - Windows protects those."
        if game and norm(p).startswith(norm(game)):
            return f"{what} folder can't be inside the Skyrim game folder."
    if os.path.isdir(install) and not os.path.isdir(os.path.join(install, MARK)):
        # leftovers of our own earlier (cancelled/failed) attempts don't count: the downloads folder and the Steam Stock Game folder
        other = [n for n in os.listdir(install) if n.lower() not in ("downloads", "stock game", MARK)]
        if other:
            return "Install folder isn't empty and isn't an earlier An0sPack install. Pick an empty folder."
    return ""


def detect_game():
    """candidate Skyrim SE folders (registry + every Steam library)"""
    import winreg
    found = []

    def reg(root, key, val):
        try:
            with winreg.OpenKey(root, key) as k:
                return winreg.QueryValueEx(k, val)[0]
        except OSError:
            return ""
    p = reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim Special Edition", "installed path")
    if p:
        found.append(p)
    steam = reg(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath")
    libs = [steam] if steam else []
    try:
        libs += re.findall(r'"path"\s+"([^"]+)"', open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf8", errors="ignore").read())
    except OSError:
        pass
    for lib in libs:
        found.append(os.path.join(lib.replace("\\\\", "\\"), "steamapps", "common", "Skyrim Special Edition"))
    out = []
    for f in found:
        f = os.path.normpath(f)
        if os.path.exists(os.path.join(f, "SkyrimSE.exe")) and f not in out:
            out.append(f)
    return out


def crc_file(path, cancelled=lambda: False):
    c = 0
    with open(lp(path), "rb") as f:
        while True:
            b = f.read(8 << 20)
            if not b:
                return c
            if cancelled():
                raise Cancelled()
            c = zlib.crc32(b, c)


STEAM_APP = 489830
DEPOTS = [(489831, 8442952117333549665), (489832, 8042843504692938467), (489833, 1914580699073641964)]  # Skyrim SE 1.6.1170 (Steam console manifest list)
STEAM_COMMANDS = [f"download_depot {STEAM_APP} {d} {m}" for d, m in DEPOTS]
LOOSE = ("data/marketplacetextures.bsa",)  # cosmetic Creation Club files: whatever version the user has is fine


def critical(rel):
    """files that must be exactly the author's version; everything else (Creation Club, ini presets, Steam bookkeeping) may come from the user's game"""
    r = rel.lower()
    if r in LOOSE:
        return False
    if r.endswith((".exe", ".dll")):
        return True
    return r.startswith("data/") and r.count("/") == 1 and r.endswith((".esm", ".esl", ".bsa")) and not r.startswith("data/cc")


def check_game(man, game):
    """'' when `game` looks like a Skyrim SE folder, else a message (the version is dealt with by game_needs_depots)"""
    if not game or not os.path.exists(os.path.join(game, "SkyrimSE.exe")):
        return "Select your Skyrim Special Edition folder (the one containing SkyrimSE.exe)."
    return ""


def game_needs_depots(man, game):
    """True when some file An0sPack needs in its exact version (exe, dlls, base-game archives) differs from the user's game"""
    for ent in man["game_files"]:
        rel, size = ent[0], ent[1]
        if critical(rel):
            p = os.path.join(game, rel.replace("/", os.sep))
            if not os.path.exists(p) or os.path.getsize(p) != size:
                return True
    return False


QR = "@qr"  # steam_user value meaning "log in by QR code"
DD_URL = "https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_3.4.0/DepotDownloader-windows-x64.zip"
DD_SHA256 = "41c9e9f0df54b3ad02e67a11726756e5c73283bd7c2e1b04acfa5ae4c2ed3767"


def fetch_depotdownloader(progress=lambda *a: None, cancelled=lambda: False):
    """DepotDownloader (SteamRE, GPLv2): pinned release, checksum-verified, cached under data/tools"""
    import hashlib, httpx
    d = os.path.join(core.DATA, "tools", "DepotDownloader")
    exe = os.path.join(d, "DepotDownloader.exe")
    if os.path.exists(exe):
        return exe
    os.makedirs(d, exist_ok=True)
    zp, h = os.path.join(d, "dd.zip"), hashlib.sha256()
    with httpx.stream("GET", DD_URL, follow_redirects=True, timeout=httpx.Timeout(30, read=60)) as r:
        r.raise_for_status()
        total, done = int(r.headers.get("content-length", 0)), 0
        with open(zp, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                if cancelled():
                    raise Cancelled()
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                progress("Downloading the Steam download tool", done, total, "")
    if h.hexdigest() != DD_SHA256:
        os.remove(zp)
        raise InstallError("The Steam download tool did not match its expected checksum - aborted for safety.")
    with zipfile.ZipFile(zp) as z:
        z.extract("DepotDownloader.exe", d)
    os.remove(zp)
    return exe


def run_depots(exe, user, stage, cancelled):
    """one DepotDownloader run for all three 1.6.1170 depots, in its own console window: the user types their Steam password / Steam Guard code
    there. Nothing is stored - no -remember-password, the password never passes through this app, and the username is only used for this run."""
    import random, tempfile
    os.makedirs(stage, exist_ok=True)
    login = "-qr" if user == QR else f'-username "{user}"'  # QR: scan with the Steam mobile app, no password typed at all
    depots = " ".join(str(d) for d, _ in DEPOTS)
    mans = " ".join(str(m) for _, m in DEPOTS)
    lines = ["@echo off", "title An0sPack - Skyrim from Steam",
             "echo An0sPack is downloading the Skyrim files this modlist needs from Steam. Your own game is not touched.",
             "echo Log in with the Steam account that owns Skyrim. Your password and Steam Guard code are typed HERE and go only to Steam;",
             "echo nothing is saved and this window forgets them when it closes.", "echo.",
             f'"{exe}" -app {STEAM_APP} -depot {depots} -manifest {mans} {login} -loginid {random.randint(1000, 2000000000)} -dir "{stage}" -max-downloads 16',
             "if errorlevel 1 goto fail", "exit /b 0", ":fail", "echo.", "echo Download failed - read the message above. Press any key to close this window.", "pause >nul", "exit /b 1"]
    fd, cmd = tempfile.mkstemp(suffix=".cmd")
    with os.fdopen(fd, "w") as f:
        f.write("\r\n".join(lines) + "\r\n")
    try:
        p = subprocess.Popen(["cmd", "/c", cmd], creationflags=0x10)  # CREATE_NEW_CONSOLE
        while p.poll() is None:
            if cancelled():
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, creationflags=0x08000000)
                raise Cancelled()
            try:
                p.wait(0.5)
            except subprocess.TimeoutExpired:
                pass
    finally:
        os.remove(cmd)
        shutil.rmtree(lp(os.path.join(stage, ".DepotDownloader")), ignore_errors=True)  # DepotDownloader's bookkeeping, never credentials (we don't ask it to remember)
    if p.returncode != 0:
        raise InstallError("The Skyrim download from Steam did not finish (wrong password, Steam Guard code, or the account doesn't own Skyrim).")


def ensure_game_files(man, game, install, steam_user, progress=lambda *a: None, cancelled=lambda: False):
    """make sure the exact-version game files exist somewhere we can read them: the user's game, Steam's cache, or <install>/Stock Game (downloaded here)"""
    if not game_needs_depots(man, game) or depots_ready(man, game, install):
        return
    if not steam_user:
        raise InstallError("Your Skyrim isn't the version this modlist needs and no Steam account name was given for the download.")
    progress("Getting Skyrim from Steam", 0, 1, "log in in the window that opened")
    run_depots(fetch_depotdownloader(progress, cancelled), steam_user, os.path.join(install, STOCK), cancelled)
    if not depots_ready(man, game, install):
        raise InstallError("The Steam download finished but some required game files are missing from it.")


def depots_ready(man, game, install=None):
    """every exact-version file is available, either in the user's game or in Steam's 1.6.1170 depot folders. Entries flagged as edited by the author
    (cleaned masters, repacked archives) are satisfied by the stock depot version of the same file."""
    stages = steam_depot_dirs(install)
    for ent in man["game_files"]:
        rel, size = ent[0], ent[1]
        if not critical(rel):
            continue
        r = rel.replace("/", os.sep)
        edited = len(ent) > 3 and ent[3]
        if not any(os.path.exists(os.path.join(g, r)) and (edited or os.path.getsize(os.path.join(g, r)) == size) for g in stages) and \
                not (os.path.exists(os.path.join(game, r)) and os.path.getsize(os.path.join(game, r)) == size):
            return False
    return True


STOCK = "Stock Game"  # drop the downloaded depot files in <install>/Stock Game and they are used first


def steam_depot_dirs(install=None):
    """where the 1.6.1170 depot files may be: <install>/Stock Game (copied there by the user) and Steam's own `download_depot` output (<library>/steamapps/content/app_489830/depot_N)"""
    import winreg
    libs = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = winreg.QueryValueEx(k, "SteamPath")[0]
        libs.append(steam)
        libs += re.findall(r'"path"\s+"([^"]+)"', open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf8", errors="ignore").read())
    except OSError:
        pass
    out = [os.path.join(install, STOCK)] if install and os.path.isdir(os.path.join(install, STOCK)) else []
    for lib in libs:
        for d, _ in DEPOTS:
            p = os.path.normpath(os.path.join(lib.replace("\\\\", "\\"), "steamapps", "content", f"app_{STEAM_APP}", f"depot_{d}"))
            if os.path.isdir(p) and p not in out:
                out.append(p)
    return out


def space_report(man, install, dl):
    """(needed_bytes_install, needed_bytes_downloads) still to write; same-drive callers should add them"""
    st = man["stats"]
    need_install = st.get("matched_bytes", 0) + st.get("inline_bytes", 0) + st.get("game_bytes", 0)
    big = max((a["size"] for a in man["archives"]), default=0)
    have = locate(man, dl)
    need_dl = sum(a["size"] for a in man["archives"] if have.get(a["id"]) is None and a["src"]["t"] != "manual")
    return need_install + big, need_dl


def free(path):
    p = os.path.abspath(path)
    while not os.path.exists(p):
        p = os.path.dirname(p)
    return shutil.disk_usage(p).free


# ---------- archives ----------
def locate(man, dl):
    """archive id -> path of the downloaded file in `dl`, or None"""
    metas = core.meta_ids(dl) if os.path.isdir(dl) else {}
    out = {}
    for a in man["archives"]:
        s, p = a["src"], None
        if s["t"] == "nexus" and (s["mod"], s["file"]) in metas:
            p = metas[(s["mod"], s["file"])]
        else:
            n = skse.ARCHIVE if s["t"] == "script" else s.get("name") or a["name"]
            q = os.path.join(dl, n)
            if os.path.exists(q) and os.path.getsize(q):
                p = q
        out[a["id"]] = p
    return out


def download_tasks(man, start=100000):
    """Engine tasks for every archive that can be fetched (idx offset keeps them clear of table rows)"""
    tasks = {}
    for a in man["archives"]:
        s = a["src"]
        t = {"name": a["name"], "game": core.SK, "modid": 0, "fileid": 0, "file": a["name"], "version": "", "dl": "", "script": "", "src": ""}
        if s["t"] == "nexus":
            t.update(game=s["game"], modid=s["mod"], fileid=s["file"], file="")
        elif s["t"] == "url":
            t.update(dl=s["url"], file=s["name"])
        elif s["t"] == "script":
            t.update(script=s["script"], src=skse.HOME)
        else:
            continue
        tasks[start + a["id"]] = t
    return tasks


def missing_manual(man, dl):
    have = locate(man, dl)
    return [a["src"].get("name") or a["name"] for a in man["archives"] if a["src"]["t"] == "manual" and have[a["id"]] is None]


# ---------- best-effort install of an imported profile (no author package) ----------
MO2_URL = "https://github.com/ModOrganizer2/modorganizer/releases/download/v2.5.2/Mod.Organizer-2.5.2.7z"
GAME_NAMES = {"skyrimspecialedition": "Skyrim Special Edition", "skyrim": "Skyrim", "fallout4": "Fallout 4"}
DATA_DIRS = {"meshes", "textures", "scripts", "skse", "interface", "sound", "music", "shaders", "seq", "strings", "video", "grass", "lodsettings",
             "facegen", "calientetools", "platform", "netscriptframework", "skyproc patchers", "dialogueviews", "distantlod", "lodsettings"}
DATA_EXT = (".esp", ".esm", ".esl", ".bsa", ".ba2")


def simple_base():
    """just Mod Organizer 2 - what an imported profile needs besides its own mods"""
    return {"version": 1, "name": "", "profile": "", "archives": [{"id": 0, "name": "Mod.Organizer-2.5.2.7z", "size": 149660212, "src": {"t": "url", "url": MO2_URL, "name": "Mod.Organizer-2.5.2.7z"}}],
            "groups": [{"to": "", "a": 0, "strip": "", "all": True}], "inline": {}, "texts": {}, "meta": {}, "game_files": [], "game_exe": None, "ini": [], "mo2": 0, "stats": {}}


def data_prefix(paths):
    """folder inside the archive that holds the mod's Data content: every folder that directly contains a Data-type folder or a plugin/BSA is a
    candidate; the one with the most files wins (for FOMOD archives that is the biggest option), ties go to the shallowest"""
    cands = {}
    for pth in paths:
        parts = pth.replace("\\", "/").split("/")
        for k, part in enumerate(parts):
            last = k == len(parts) - 1
            if (not last and part.lower() in DATA_DIRS) or (last and part.lower().endswith(DATA_EXT)):
                pre = "/".join(parts[:k])
                cands[pre] = cands.get(pre, 0) + 1
                break
    if not cands:
        return ""
    pre = min(cands, key=lambda c: (-cands[c], c.count("/")))
    return pre + "/" if pre else ""


def fomod_pairs(archive, ents):
    """[(inner, rel)] a FOMOD installer would give with its default choices (required files + Required/Recommended options, else the first option of
    each single-choice group, + conditional installs whose flags are set), or None when the archive has no readable FOMOD"""
    import tempfile
    import xml.etree.ElementTree as ET
    cfg = next((e for e in ents if e.lower().endswith("fomod/moduleconfig.xml")), None)
    if not cfg:
        return None
    root_dir = cfg[:len(cfg) - len("fomod/ModuleConfig.xml")]
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([skse.seven_zip(), "x", "-y", "-spd", f"-o{tmp}", archive, cfg.replace("/", "\\")], capture_output=True, creationflags=0x08000000)
        f = os.path.join(tmp, cfg.replace("/", os.sep))
        if not os.path.exists(f):
            return None
        raw = open(f, "rb").read()
    try:
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", "replace")
        text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
        tree = ET.fromstring(text)
    except Exception:
        return None
    loc = lambda el: el.tag.split("}")[-1]
    kids = lambda el, n: [c for c in el if loc(c) == n]
    desc = lambda el, n: [c for c in el.iter() if loc(c) == n]
    low = {}
    for e in ents:
        low.setdefault(e.lower(), e)

    def expand(files_el):
        out = []
        for it in list(files_el):
            src = (it.get("source") or "").replace("\\", "/").strip("/")
            dst = (it.get("destination") or "").replace("\\", "/").strip("/")
            if not src:
                continue
            full = (root_dir + src).lower()
            if loc(it) == "folder":
                pre = full + "/"
                for k, e in low.items():
                    if k.startswith(pre):
                        out.append((e, (dst + "/" if dst else "") + e[len(root_dir + src) + 1:]))
            elif loc(it) == "file" and full in low:
                d0 = it.get("destination") or ""
                base = os.path.basename(src)
                rel = base if not d0.strip() else (dst + "/" + base if d0.endswith(("/", "\\")) else dst)
                out.append((low[full], rel))
        return out
    pairs, flags = [], {}
    for req in desc(tree, "requiredInstallFiles"):
        pairs += expand(req)
    for grp in desc(tree, "group"):
        plugins = [pl for pl in desc(grp, "plugin")]
        gtype = grp.get("type", "")
        chosen = []
        for pl in plugins:
            names = [t.get("name") for t in desc(pl, "type")] + [t.get("name") for t in desc(pl, "defaultType")]
            if any(n in ("Required", "Recommended") for n in names):
                chosen.append(pl)
        if gtype == "SelectAll":
            chosen = plugins
        elif not chosen and gtype in ("SelectExactlyOne", "SelectAtLeastOne") and plugins:
            chosen = plugins[:1]
        elif gtype in ("SelectExactlyOne", "SelectAtMostOne"):
            chosen = chosen[:1]
        for pl in chosen:
            for fl in desc(pl, "flag"):
                flags[fl.get("name")] = (fl.text or "").strip()
            for fe in kids(pl, "files"):
                pairs += expand(fe)
    for pat in desc(tree, "pattern"):
        deps = kids(pat, "dependencies")
        if not deps or any(loc(c) in ("fileDependency", "gameDependency", "fommDependency") for d in deps for c in d.iter()):
            continue  # depends on other installed mods/plugins: unknown here
        op = deps[0].get("operator", "And")
        res = [flags.get(c.get("flag")) == (c.get("value") or "") for c in desc(deps[0], "flagDependency")]
        if res and (all(res) if op == "And" else any(res)):
            for fe in kids(pat, "files"):
                pairs += expand(fe)
    final = {}
    for inner, rel in pairs:
        final[rel.lower()] = (inner, rel)
    return list(final.values()) or None


CC_SEP = "____________________________ CREATION CLUB _____________________________separator"
DLC_SEP = "____________________________ BASE DLC FILES _____________________________separator"


def dlc_cc_lines(game_dir):
    """modlist.txt lines for the game's unmanaged DLC and Creation Club plugins, each group followed by its separator (MO2 lists a separator after the entries it holds)"""
    try:
        files = os.listdir(os.path.join(game_dir, "Data"))
    except OSError:
        return []
    cc = sorted((os.path.splitext(f)[0] for f in files if f.lower().startswith("cc") and f.lower().endswith((".esl", ".esm", ".esp"))), key=str.lower)
    res = [os.path.splitext(f)[0] for f in files if f.lower() == "_resourcepack.esl"]
    cc = res + cc
    dlc = [os.path.splitext(f)[0] for d in ("Dawnguard", "Dragonborn", "HearthFires") for f in files if f.lower() == d.lower() + ".esm"]
    return [f"*Creation Club: {n}" for n in cc] + ["-" + CC_SEP] + [f"*DLC: {d}" for d in dlc] + ["-" + DLC_SEP]


def qs_list(items):
    """a QStringList the way QSettings writes it to an .ini value"""
    def one(s):
        e = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{e}"' if any(c in s for c in ",;=") or s != s.strip() else e
    return ", ".join(one(i) for i in items)


def set_ini(lines, section, key, value):
    """set key=value inside [section] (created when missing)"""
    out, cur, done = [], None, False
    for ln in lines:
        if ln.startswith("["):
            if cur == section and not done:
                out.append(f"{key}={value}")
                done = True
            cur = ln.strip("[]")
        if cur == section and ln.startswith(key + "="):
            if not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(ln)
    if not done:
        if cur != section:
            out.append(f"[{section}]")
        out.append(f"{key}={value}")
    return out


def game_edition(game_dir):
    """MO2's game_edition value for a Skyrim SE folder (it asks the user when this is missing)"""
    try:
        names = [n.lower() for n in os.listdir(game_dir)]
    except OSError:
        return "Steam"
    if ".egstore" in names:
        return "Epic Games"
    if any(n.startswith("goggame-") for n in names):
        return "GOG"
    return "Steam"


def simple_manifest(profile, dl_dir, game_dir, progress=lambda *a: None, cancelled=lambda: False):
    """manifest for install(): every downloaded archive is extracted into its own mod folder from its detected Data root.
    FOMOD choices, hand-edited files and the plugin order can't be known from a modlist.txt, so this is best effort."""
    import compiler
    man = simple_base()
    man["name"] = man["profile"] = profile["name"]
    metas = core.meta_ids(dl_dir) if os.path.isdir(dl_dir) else {}
    core.apply_cached_cats(profile["mods"])
    mo_cats = {}  # Nexus category name -> MO2 category id, from the shipped categories.dat
    try:
        for ln in open(os.path.join(skse.RES, "assets", "mo2_categories.dat"), encoding="utf-8").read().splitlines():
            parts = ln.split("|")
            if len(parts) >= 2 and parts[0].isdigit():
                mo_cats[parts[1].lower()] = parts[0]
    except OSError:
        pass
    keep, names = [], set()
    rows = profile["mods"]
    for n, row in enumerate(rows, 1):
        if cancelled():
            raise Cancelled()
        progress("Reading downloaded archives", n, len(rows), row["name"])
        path = None
        if row.get("script") == "skse":
            path = os.path.join(dl_dir, skse.ARCHIVE)
        elif row["modid"] and (row["modid"], row["fileid"]) in metas:
            path = metas[(row["modid"], row["fileid"])]
        elif row["file"] and os.path.exists(os.path.join(dl_dir, row["file"])):
            path = os.path.join(dl_dir, row["file"])
        if not path or not os.path.exists(path):
            continue
        ents = [e[0] for e in compiler.list_archive(path)]
        if not ents:
            continue
        aid = len(man["archives"])
        man["archives"].append({"id": aid, "name": os.path.basename(path), "size": os.path.getsize(path), "src": compiler.source_of(row)})
        pairs = fomod_pairs(path, ents)
        if pairs:
            man["groups"].append({"to": f"mods/{row['name']}/", "a": aid, "pairs": [list(x) for x in pairs]})
        else:
            man["groups"].append({"to": f"mods/{row['name']}/", "a": aid, "strip": data_prefix(ents), "all": True})
        man["meta"][row["name"]] = {"gameName": GAME_NAMES.get(row["game"], "Skyrim Special Edition"), "modid": str(row["modid"]), "version": row["version"],
                                    "installationFile": os.path.basename(path)}
        cid = mo_cats.get((row.get("cat") or "").lower())
        if cid:
            man["meta"][row["name"]]["category"] = cid + ","
        names.add(row["name"])
    lines = []
    for ln in profile["modlist"].splitlines():
        if ln.startswith("#") or ln.startswith("*") or ln.strip().endswith("_separator"):
            lines.append(ln)
            if ln.strip().endswith("_separator"):
                man["meta"].setdefault(ln[1:].strip(), {})
        elif ln.startswith("+") and ln[1:].strip() in names:
            lines.append(ln)
    for r in rows:  # script-built rows (SKSE) aren't in an imported modlist.txt: enable them anyway
        if r.get("script") and r["name"] in names and f"+{r['name']}" not in lines:
            lines.insert(1 if lines and lines[0].startswith("#") else 0, f"+{r['name']}")
    if not any(ln.startswith("*") for ln in lines):  # DLC and Creation Club content gets its own separators
        lines = [ln for ln in lines if ln.strip() not in ("-" + CC_SEP, "-" + DLC_SEP)]  # the generated block brings its own copies
        for ln in dlc_cc_lines(game_dir):
            lines.append(ln)
            if ln.startswith("-"):
                man["meta"].setdefault(ln[1:].strip(), {})
    man["texts"][f"profiles/{profile['name']}/modlist.txt"] = "\n".join(lines) + "\n"
    game = max((GAME_NAMES.get(r["game"]) for r in rows if r["game"]), key=lambda g: sum(1 for r in rows if GAME_NAMES.get(r["game"]) == g), default="Skyrim Special Edition")
    man["ini"] = ["[General]", f"gameName={game}", f"game_edition={game_edition(game_dir)}", f"selected_profile=@ByteArray({profile['name']})", "first_start=false", "[Settings]", "profile_local_inis=true", "profile_local_saves=true", "style=Paper Dark.qss"]
    # executables: "An0sPack" (the SKSE loader, which carries the An0sPack icon when it comes from the Skyrim Script Extender mod) first, then the game itself
    gd = game_dir.replace("\\", "/")
    skse_mod = next((r["name"] for r in rows if r.get("script") == "skse" and r["name"] in names), None)
    loader = f"%%INSTALL%%/mods/{skse_mod}/Root/skse64_loader.exe" if skse_mod else f"{gd}/skse64_loader.exe"
    execs = [("An0sPack", loader, True), ("Skyrim Special Edition", f"{gd}/SkyrimSE.exe", False), ("Skyrim Special Edition Launcher", f"{gd}/SkyrimSELauncher.exe", False)]
    execs.append(("SKSE", f"{gd}/skse64_loader.exe", False))  # hidden below
    man["ini"] += ["[customExecutables]", f"size={len(execs)}"]
    for i, (title, binary, bar) in enumerate(execs, 1):
        pre = f"{i}\\"  # MO2 stores the list as "<n>\key=value"
        man["ini"] += [pre + "arguments=", pre + "binary=" + binary, pre + "hide=" + ("true" if title == "SKSE" else "false"), pre + "ownicon=true", pre + "steamAppID=", pre + "title=" + title,
                       pre + "toolbar=" + ("true" if bar else "false"), pre + "workingDirectory=" + gd]
    man["game_path"] = game_dir  # the user's own game is used in place; nothing is copied
    return man


# ---------- install ----------
def _extract(seven, archive, names, out, cancelled, listfile):
    cmd = [seven, "x", "-y", "-spd", f"-o{out}", archive]
    if names is not None:
        with open(listfile, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(n.replace("/", "\\") for n in names))
        cmd += ["-scsUTF-8", "@" + listfile]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000)
    import threading
    err = []
    threading.Thread(target=lambda: err.append(p.communicate()), daemon=True).start()
    while p.poll() is None:
        if cancelled():
            p.kill()
            raise Cancelled()
        try:
            p.wait(0.3)
        except subprocess.TimeoutExpired:
            pass
    if p.returncode not in (0, 1):  # 1 = warnings (e.g. a locked file)
        out_, err_ = (err[0] if err else (b"", b""))
        raise InstallError(f"7-Zip failed on {os.path.basename(archive)}: {(err_ or out_).decode('utf-8', 'replace')[-300:]}")


def _place(src, dst, moved):
    os.makedirs(lp(os.path.dirname(dst)), exist_ok=True)
    if os.path.exists(lp(src)):
        os.replace(lp(src), lp(dst))
        moved[src] = dst
    elif src in moved:  # the same archive file is wanted twice
        if os.path.normcase(moved[src]) != os.path.normcase(dst):
            shutil.copy2(lp(moved[src]), lp(dst))
    else:
        raise InstallError(f"expected file missing after extraction: {os.path.basename(src)}")


def install(pkg, install_dir, dl_dir, game_dir, progress=lambda phase, done, total, note="": None, cancelled=lambda: False, only=None, steam_user=""):
    """run the whole install; returns a list of warnings. `only` (regex) restricts mod folders - for testing."""
    man = pkg if isinstance(pkg, dict) else load(pkg)
    seven = skse.seven_zip()
    warn = []

    def check():
        if cancelled():
            raise Cancelled()
    root = os.path.abspath(install_dir)
    state_path = os.path.join(root, MARK, "state.json")
    tmp_root = os.path.join(root, MARK, "tmp")
    os.makedirs(tmp_root, exist_ok=True)
    try:
        done = set(json.load(open(state_path)))
    except Exception:
        done = set()
    for d in ("mods", "profiles", "downloads"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    have = locate(man, dl_dir)
    # mods whose archive can only be supplied by hand (no download source) are skipped, not fatal: the rest installs and a rerun picks them up
    skipped = {a["id"] for a in man["archives"] if have[a["id"]] is None and a["src"]["t"] == "manual"}
    for aid in sorted(skipped):
        warn.append(f"Skipped - add this file to the download folder and run Install again: {man['archives'][aid]['src'].get('name') or man['archives'][aid]['name']}")
    gone = [a["name"] for a in man["archives"] if have[a["id"]] is None and a["id"] not in skipped and any(g["a"] == a["id"] for g in man["groups"])]
    if gone:
        raise InstallError("These archives aren't in the download folder yet: " + ", ".join(gone[:8]) + (" ..." if len(gone) > 8 else ""))
    pat = re.compile(only, re.I) if only else None
    want = lambda g: not pat or not g["to"].startswith("mods/") or pat.search(g["to"][5:-1]) or g["to"] == ""

    # ---- 1. mods + Mod Organizer from the archives
    by_arch = {}
    for g in man["groups"]:
        if want(g) and g["a"] not in skipped:
            by_arch.setdefault(g["a"], []).append(g)
    order = sorted(by_arch, key=lambda a: (a != man["mo2"], a))  # MO2 first
    for n, aid in enumerate(order, 1):
        check()
        arc = man["archives"][aid]
        progress("Installing mods", n - 1, len(order), arc["name"])
        if aid in done and not pat:
            continue
        tmp = os.path.join(tmp_root, str(aid))
        shutil.rmtree(lp(tmp), ignore_errors=True)
        os.makedirs(tmp)
        groups = by_arch[aid]
        names = None
        if not any(g.get("all") for g in groups):
            names = set()
            for g in groups:
                if "pairs" in g:
                    names |= {i for i, _ in g["pairs"]}
                else:
                    names |= {g["strip"] + r for r in g["files"]}
            names = sorted(names)
        _extract(seven, have[aid], names, tmp, cancelled, os.path.join(tmp_root, f"{aid}.lst"))
        moved = {}
        for g in groups:
            dest_root = os.path.join(root, g["to"].replace("/", os.sep))
            if g.get("all"):
                base = os.path.join(tmp, g["strip"].replace("/", os.sep))
                for d, _, fs in os.walk(lp(base)):
                    for f in fs:
                        src = os.path.join(d, f)
                        rel = os.path.relpath(src, lp(base))
                        _place(src[4:] if src.startswith("\\\\?\\") else src, os.path.join(dest_root, rel), moved)
            else:
                pairs = g["pairs"] if "pairs" in g else [[g["strip"] + r, r] for r in g["files"]]
                for inner, rel in pairs:
                    _place(os.path.join(tmp, inner.replace("/", os.sep)), os.path.join(dest_root, rel.replace("/", os.sep)), moved)
        shutil.rmtree(lp(tmp), ignore_errors=True)
        if not pat:
            done.add(aid)
            json.dump(sorted(done), open(state_path, "w"))
    progress("Installing mods", len(order), len(order), "")

    # ---- 2. files that exist only in the package, mod meta.ini files, mod folders
    check()
    for dest, text in man.get("texts", {}).items():
        dst = os.path.join(root, dest.replace("/", os.sep))
        os.makedirs(lp(os.path.dirname(dst)), exist_ok=True)
        with open(lp(dst), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(text)
    with (zipfile.ZipFile(pkg) if not isinstance(pkg, dict) else open(os.devnull, "rb")) as z:
        items = [(d, m) for d, m in man["inline"].items() if not pat or not d.startswith("mods/") or pat.search(d.split("/")[1]) or not d.startswith("mods/")]
        for i, (dest, member) in enumerate(items):
            check()
            if i % 200 == 0:
                progress("Writing patches and settings", i, len(items), "")
            dst = os.path.join(root, dest.replace("/", os.sep))
            os.makedirs(lp(os.path.dirname(dst)), exist_ok=True)
            with z.open(member) as s, open(lp(dst), "wb") as d:
                shutil.copyfileobj(s, d, 1 << 20)
    for mod, kv in man["meta"].items():
        if pat and not pat.search(mod):
            continue
        d = os.path.join(root, "mods", mod)
        os.makedirs(lp(d), exist_ok=True)
        with open(lp(os.path.join(d, "meta.ini")), "w", encoding="utf-8", newline="\r\n") as f:
            f.write("[General]\n" + "".join(f'{k}={chr(34) + v + chr(34) if "," in v and not v.startswith(chr(34)) else v}\n' for k, v in kv.items()))
    progress("Writing patches and settings", len(items), len(items), "")

    # ---- 3. Game Root: exact-version files from the 1.6.1170 depots (Steam console download) when the user's game differs, the rest from the user's own game
    if man["game_files"] and not pat:
        groot = os.path.join(root, "Game Root")
        ensure_game_files(man, game_dir, root, steam_user, progress, cancelled)
        stages = steam_depot_dirs(root)
        stock = os.path.join(root, STOCK)
        files = man["game_files"]
        total = sum(ent[1] for ent in files)
        copied = 0
        standard = []
        for ent in files:
            rel, size, crc = ent[:3]
            edited = len(ent) > 3 and ent[3]  # the author's copy was cleaned/repacked: the stock 1.6.1170 depot version is used instead
            check()
            r = rel.replace("/", os.sep)
            dst = os.path.join(groot, r)
            progress("Building Game Root", copied, total, rel)
            if os.path.exists(lp(dst)) and (edited or os.path.getsize(lp(dst)) == size):
                copied += size
                continue
            cands = [os.path.join(g, r) for g in [game_dir] + stages] if not critical(rel) else [os.path.join(g, r) for g in stages + [game_dir]]
            got = False
            for src in cands:
                if not os.path.exists(lp(src)):
                    continue
                own = os.path.normcase(src).startswith(os.path.normcase(game_dir))
                if critical(rel) and os.path.getsize(lp(src)) != size and not (edited and not own):
                    continue
                os.makedirs(lp(os.path.dirname(dst)), exist_ok=True)
                c = 0
                with open(lp(src), "rb") as s_, open(lp(dst) + ".part", "wb") as d_:
                    while True:
                        b = s_.read(8 << 20)
                        if not b:
                            break
                        check()
                        d_.write(b)
                        c = zlib.crc32(b, c)
                        copied += len(b)
                if c != crc and critical(rel) and not edited:
                    os.remove(lp(dst) + ".part")
                    copied -= size
                    continue
                os.replace(lp(dst) + ".part", lp(dst))
                if c != crc:
                    (standard if edited else warn).append(rel if edited else f"Different version of a non-essential game file (kept yours): {rel}")
                if os.path.normcase(src).startswith(os.path.normcase(stock)):
                    os.remove(lp(src))  # downloaded for this install only: free the space as we go
                got = True
                break
            if not got:
                if critical(rel):
                    raise InstallError(f"Can't get the right version of {rel}. Skyrim 1.6.1170 is needed - run the Steam downloads shown by the installer, then press Install again.")
                warn.append(f"Game file not found in your Skyrim folder (skipped): {rel}")
                copied += size
        if standard:
            warn.append(f"{len(standard)} base-game files use the standard 1.6.1170 version (the author's copies were cleaned/repacked): " + ", ".join(standard[:6]) + (" ..." if len(standard) > 6 else ""))
        shutil.rmtree(lp(stock), ignore_errors=True)
        progress("Building Game Root", total, total, "")

    # ---- 4. Mod Organizer settings
    check()
    progress("Configuring Mod Organizer", 0, 1, "")
    open(os.path.join(root, "portable.txt"), "w").close()
    assets = os.path.join(skse.RES, "assets")
    for src, dst in ((os.path.join(assets, "mo2_splash.png"), "splash.png"), (skse.ICO, "An0sPack.ico"),  # An0sPack branding for MO2
                     (os.path.join(assets, "mo2_categories.dat"), "categories.dat"), (os.path.join(assets, "mo2_nexuscatmap.dat"), "nexuscatmap.dat")):
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(root, dst))
    plug = os.path.join(assets, "an0spack_collapse.py")
    if os.path.exists(plug):
        os.makedirs(os.path.join(root, "plugins"), exist_ok=True)
        shutil.copy2(plug, os.path.join(root, "plugins", "an0spack_collapse.py"))
    try:
        skse.set_icon(os.path.join(root, "ModOrganizer.exe"), skse.ICO)
    except Exception as e:
        warn.append(f"Couldn't apply the An0sPack icon to ModOrganizer.exe ({e}); the shortcut still uses it.")

    def sub(m):  # token -> install path in the slash style of the surrounding text
        sep = m.group(1)
        return (root.replace("\\", "\\\\") if sep.startswith("\\") else root.replace("\\", "/")) + sep
    ini = [re.sub(r"%%INSTALL%%([\\/]*)", sub, ln) for ln in man["ini"]]
    gp = "gamePath=@ByteArray(" + (man.get("game_path") or os.path.join(root, "Game Root")).replace("\\", "\\\\") + ")"
    out, put = [], False
    for ln in ini:
        out.append(ln)
        if ln.strip() == "[General]" and not put:
            out.append(gp)
            put = True
    if not put:
        out = ["[General]", gp] + out
    out = set_ini(out, "General", "version", "2.5.2")  # no "Category Migration" prompt: it appears when the recorded version is < 2.5
    out = set_ini(out, "Settings", "style", "Paper Dark.qss")  # default theme
    out = set_ini(out, "Settings", "collapsible_separators_per_profile", "true")  # so the collapsed list below is read at first launch
    for k in ("collapsible_separators_asc", "collapsible_separators_dsc"):
        out = set_ini(out, "Settings", k, "true")
    with open(os.path.join(root, "ModOrganizer.ini"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(out) + "\n")
    # every separator starts collapsed: MO2 reads collapsed_separators from the profile's settings.ini
    prof_dir = os.path.join(root, "profiles", man["profile"])
    ml = os.path.join(prof_dir, "modlist.txt")
    if os.path.exists(ml):
        seps = [ln.strip()[1:-len("_separator")] for ln in open(ml, encoding="utf-8", errors="ignore").read().splitlines() if ln.startswith("-") and ln.strip().endswith("_separator")]
        si = os.path.join(prof_dir, "settings.ini")
        old = open(si, encoding="utf-8", errors="ignore").read().splitlines() if os.path.exists(si) else ["[General]", "LocalSaves=true", "LocalSettings=true", "AutomaticArchiveInvalidation=true"]
        old = set_ini(old, "UserInterface", "collapsed_separators", qs_list(seps))
        with open(si, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("\n".join(old) + "\n")
    _shortcut(root, man["profile"])
    shutil.rmtree(lp(tmp_root), ignore_errors=True)
    progress("Configuring Mod Organizer", 1, 1, "")
    return warn


def _shortcut(root, profile):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:AN0S_LNK);$s.TargetPath=$env:AN0S_EXE;$s.Arguments=$env:AN0S_ARGS;"
          "$s.WorkingDirectory=$env:AN0S_DIR;$s.IconLocation=$env:AN0S_ICON;$s.Save()")
    env = dict(os.environ, AN0S_LNK=os.path.join(root, "An0sPack - MO2.lnk"), AN0S_EXE=os.path.join(root, "ModOrganizer.exe"),
               AN0S_ARGS=f'--profile "{profile}"', AN0S_DIR=root, AN0S_ICON=os.path.join(root, "An0sPack.ico"))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, capture_output=True, creationflags=0x08000000)
