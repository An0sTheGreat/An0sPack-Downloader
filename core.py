"""An0sPack Downloader core: modlist parsing, profiles, Nexus API, download engine (no Qt)."""
import base64, copy, ctypes, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx

import skse

APP = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
DATA = os.path.join(APP, "data")
PROFILES = os.path.join(DATA, "profiles")
for _d in (DATA, PROFILES):
    os.makedirs(_d, exist_ok=True)

API = "https://api.nexusmods.com/v1"
GAMES = {"skyrimse": "skyrimspecialedition", "skyrim": "skyrim", "fallout4": "fallout4"}  # MO2 gameName -> Nexus domain
MO2_NAME = {"skyrimspecialedition": "SkyrimSE"}
DEFAULT_PROFILE = "An0sPack - CS"  # seeded, default selection, cannot be deleted
MAX_WORKERS = 5  # ponytail: Nexus publishes no concurrent cap; rate limits (2500/day, 100/h after) are honoured via headers


# ---------- secrets (Windows DPAPI, per-user) ----------
class _Blob(ctypes.Structure):
    _fields_ = [("n", wintypes.DWORD), ("p", ctypes.POINTER(ctypes.c_char))]


def _crypt(fn, data: bytes) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    i, o = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    if not fn(ctypes.byref(i), None, None, None, None, 0, ctypes.byref(o)):
        raise OSError("DPAPI failed")
    r = ctypes.string_at(o.p, o.n)
    ctypes.windll.kernel32.LocalFree(o.p)
    return r


def protect(s: str) -> str:
    return base64.b64encode(_crypt(ctypes.windll.crypt32.CryptProtectData, s.encode())).decode() if s else ""


def unprotect(s: str) -> str:
    try:
        return _crypt(ctypes.windll.crypt32.CryptUnprotectData, base64.b64decode(s)).decode() if s else ""
    except Exception:
        return ""


# ---------- config ----------
CFG_PATH = os.path.join(DATA, "config.json")


def load_cfg() -> dict:
    c = {"theme": "Dark", "install": "", "dest": "", "dest_custom": False, "game": "", "key": "", "workers": 3, "profile": DEFAULT_PROFILE}
    try:
        c.update(json.load(open(CFG_PATH, encoding="utf8")))
    except Exception:
        pass
    if c["dest"] == os.path.join(APP, "Downloads"):  # old default; the download folder now follows the install folder
        c["dest"] = ""
    if c["theme"] == "Fantasy":  # renamed
        c["theme"] = "Rustic"
    return c


def save_cfg(c: dict):
    json.dump(c, open(CFG_PATH, "w", encoding="utf8"), indent=1)


# ---------- known re-sourcing of mods MO2 can't identify ----------
SK = "skyrimspecialedition"


def _row(name, modid=0, fileid=0, file="", version="", dl="", cat="", **extra):
    return {"name": name, "modid": modid, "game": SK if modid else "", "version": version, "file": file, "fileid": fileid, "url": "", "dl": dl, "cat": cat, "also": [], **extra}


_BELLA = "DBVO 2.0 Bella - %s 183536 FOMOD-1.6 %s.7z"
OUTPUTS = {"Pandora Output", "BodySlide Output", "xLODGen Output", "PGPatcher_Output", "DynDOLOD_Output", "An0sPack - Character Presets",
           "Community Shaders - Runtime Output", "An0sPack - Runtime Settings", "An0sPack - Veydogolt LOD Texture Path Fix", "An0sPack - Grass Cache",
           "TexGen Output - Grass LOD", "An0sPack - Norden UI Themes", "Oathvein - HUD Hook Priority Fix"}  # all shipped in one Nexus file
OUTPUT_ROW = _row("An0sPack - Required Files (generated outputs)", 194071, 814728, "An0sPack Required Files 194071 1 2026-10-04T22-07Z N2AYL5lIV.zip", "1")
# Community Shaders features: the MO2 archives are repackaged "release set" zips (not on Nexus); use each feature's current Nexus MAIN file
FEATURE_FILES = {149011: (765252, "1.1.2"), 130375: (763934, "4.2.0"), 112739: (747765, "3.1.0"), 156952: (758189, "1.4.0"), 192760: (809741, "1.0.0")}
SKSE_NAMES = {"Skyrim Script Extender", "External - SKSE [e7e73f36]"}
SKSE_ROW = _row("Skyrim Script Extender", file=skse.ARCHIVE, version="2.02.06", cat="Utilities", script="skse", src=skse.HOME,
                note="Built on this PC: downloads SKSE from skse.silverlock.org, applies the An0sPack icon to the loader and packs it as a Root Builder archive.")
FIXUPS = {  # modlist entry name -> replacement rows
    "Silent Sound Effects - Sneak and Dagger": [_row("Silent Sound Effects - Sneak and Dagger", 49332, 726407, "Silent Sound Effects-49332-1-0-3-1772260822.zip", "1.0.3")],
    "Armor Variants Expansion - Compatibility Patches": [_row("Armor Variants Expansion - Compatibility Patches", 35176, 530347,
                                                              "Armor Variants Expansion - Patch Collection-35176-2-6-1723330050.7z", "2.6")],
    "External - SCAR-v2.01.AE.7z [d5bccb20]": [_row("SCAR 2.01 AE", file="36b13267e463-SCAR-v2.01.AE.7z", version="2.01 AE", cat="Utilities",
                                                    dl="https://github.com/SkyHorizon3/SCAR/releases/download/v2.01/SCAR-v2.01.AE.7z")],
    "Bella Voice - AYOP 1.6 Addons": [_row(f"Bella Voice - AYOP {n}", 183536, i, _BELLA % (f, t), "FOMOD-1.6") for n, i, f, t in (
        ("Main Quest (At Your Own Pace)", 806175, "At Your Own Pace", "2026-09-16T15-42Z Z3mWyI6Er"), ("Companions", 806176, "AYOP Companions", "2026-09-16T15-43Z Sx9oEwJRB"),
        ("Dark Brotherhood", 806177, "AYOP Dark Brotherhood", "2026-09-16T15-43Z L5WQbqwCn"), ("Dawnguard", 806178, "AYOP Dawnguard", "2026-09-16T15-44Z Ks18n0Fv0"),
        ("Thieves Guild", 806179, "AYOP Thieves Guild", "2026-09-16T15-45Z hfH9s6z7g"))],
}


def apply_fixups(rows):
    out, done = [], False
    for m in rows:
        if m["name"] in OUTPUTS:
            if not done:
                out.append(copy.deepcopy(OUTPUT_ROW))
                done = True
        elif m["modid"] in FEATURE_FILES and not m["fileid"]:
            m["fileid"], m["version"] = FEATURE_FILES[m["modid"]]
            m["file"] = ""
            out.append(m)
        elif m["name"] in SKSE_NAMES:  # ghost entry: always listed, built by skse.py rather than downloaded
            out.append(copy.deepcopy(SKSE_ROW))
        else:
            out += copy.deepcopy(FIXUPS[m["name"]]) if m["name"] in FIXUPS else [m]
    if not any(m.get("script") for m in out):
        out.insert(0, copy.deepcopy(SKSE_ROW))
    return out


def dlable(m):
    return bool(m["modid"] or m.get("dl") or m.get("script"))


def source_label(m):
    return str(m["modid"] or ("Script" if m.get("script") else "GitHub" if m.get("dl") else "-"))


# ---------- modlist -> profile ----------
def _ini(path):
    """tiny ini reader: {(section,key): value}; MO2 meta.ini has Qt @Variant junk configparser dislikes"""
    d, sec = {}, ""
    try:
        for ln in open(path, encoding="utf8", errors="ignore"):
            ln = ln.strip()
            if ln.startswith("[") and ln.endswith("]"):
                sec = ln[1:-1]
            elif "=" in ln:
                k, v = ln.split("=", 1)
                d[(sec, k)] = v.strip().strip('"')
    except OSError:
        pass
    return d


def find_root(modlist_path):
    """MO2 base dir = <root>/profiles/<profile>/modlist.txt -> <root>, if mods/ exists there"""
    r = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(modlist_path))))
    return r if os.path.isdir(os.path.join(r, "mods")) else None


def import_modlist(path, root=None, name=None):
    """parse modlist.txt (+ MO2 mods/ and downloads/ metadata when root known) into a profile dict and save it"""
    text = open(path, encoding="utf8", errors="ignore").read()
    root = root or find_root(path)
    names = [ln[1:].strip() for ln in text.splitlines() if ln.startswith("+") and not ln.strip().endswith("_separator")]
    rows, seen = [], {}
    for n in reversed(names):  # modlist.txt lists highest priority first; keep install order low->high
        m = {"name": n, "modid": 0, "game": "", "version": "", "file": "", "fileid": 0, "url": ""}
        if root:
            ini = _ini(os.path.join(root, "mods", n, "meta.ini"))
            g = lambda k: ini.get(("General", k), "")
            m["modid"] = int(g("modid") or 0) if g("modid").isdigit() else 0
            m["game"] = GAMES.get(g("gameName").lower(), g("gameName").lower())
            m["version"] = g("version")
            m["file"] = os.path.basename(g("installationFile").replace("\\", "/"))
            m["url"] = g("url") if g("hasCustomURL") == "true" or g("url") else ""
            if m["file"]:
                dm = _ini(os.path.join(root, "downloads", m["file"] + ".meta"))
                if dm.get(("General", "fileID"), "").isdigit():
                    m["fileid"] = int(dm[("General", "fileID")])
                if not m["modid"] and dm.get(("General", "modID"), "").isdigit():  # mod meta.ini lacks it; archive meta has it
                    m["modid"] = int(dm[("General", "modID")])
                    m["game"] = GAMES.get(dm.get(("General", "gameName"), "").lower(), dm.get(("General", "gameName"), "").lower())
            if not m["fileid"]:
                fids = [int(v) for (s, k), v in ini.items() if s == "installedFiles" and k.endswith("\\fileid") and v.isdigit() and int(v)]
                m["fileid"] = fids[-1] if fids else 0
            if m["modid"] and not m["game"]:
                m["game"] = "skyrimspecialedition"
        key = (m["game"], m["modid"], m["fileid"] or m["file"]) if m["modid"] else ("n", n)
        if key in seen:
            seen[key]["also"].append(n)  # several mod folders from one archive
            continue
        m["also"] = []
        seen[key] = m
        rows.append(m)
    rows = apply_fixups(rows)
    prof = {"name": name or os.path.basename(os.path.dirname(os.path.abspath(path))), "source": os.path.abspath(path),
            "root": root or "", "imported": datetime.now().isoformat(timespec="seconds"), "modlist": text, "mods": rows}
    save_profile(prof)
    return prof


def package_path(name):
    """the compiled .an0s install package of a profile, or '' (profiles imported from a modlist can only be downloaded)"""
    p = _pfile(name)[:-5] + ".an0s"
    return p if os.path.exists(p) else ""


def _pfile(name):
    return os.path.join(PROFILES, re.sub(r'[<>:"/\\|?*]', "_", name) + ".json")


def save_profile(p):
    json.dump(p, open(_pfile(p["name"]), "w", encoding="utf8"), indent=1)


def list_profiles():
    out = []
    for f in sorted(os.listdir(PROFILES)):
        if f.endswith(".json"):
            try:
                out.append(json.load(open(os.path.join(PROFILES, f), encoding="utf8")))
            except Exception:
                pass
    return out


def delete_profile(name):
    if name == DEFAULT_PROFILE:
        return
    try:
        os.remove(_pfile(name))
    except OSError:
        pass


def meta_ids(dl):
    """(modID, fileID) -> archive path for every .meta in the downloads folder"""
    out = {}
    for f in os.listdir(dl):
        if f.endswith(".meta"):
            d = _ini(os.path.join(dl, f)).get
            m, i = d(("General", "modID"), ""), d(("General", "fileID"), "")
            if m.isdigit() and i.isdigit() and os.path.exists(os.path.join(dl, f[:-5])):
                out[(int(m), int(i))] = os.path.join(dl, f[:-5])
    return out


def page_url(game, modid, fileid=0):
    return f"https://www.nexusmods.com/{game}/mods/{modid}" + (f"?tab=files&file_id={fileid}" if fileid else "?tab=files")


# ---------- Nexus API + download engine ----------
class Engine:
    """Runs download tasks on a thread pool. Task = dict(name, game, modid, fileid, file). Reports via on_event(idx,status,done,total,msg)."""

    def __init__(self, key, dest, workers, on_event, on_done):
        self.key, self.dest, self.n = key, dest, max(1, min(MAX_WORKERS, workers))
        self.on_event, self.on_done = on_event, on_done
        self.stop = threading.Event()
        self.cancels = {}
        self.fails = {}  # idx -> (reason, source)
        self.wait_until = 0.0
        self.http = httpx.Client(headers={"apikey": key, "Application-Name": "An0sPackDownloader", "Application-Version": "1.0",
                                          "User-Agent": "An0sPackDownloader/1.0"}, timeout=30, follow_redirects=True)

    # -- API helpers
    def _note(self, r):
        try:
            if int(r.headers.get("x-rl-hourly-remaining", 99)) <= 1 and int(r.headers.get("x-rl-daily-remaining", 99)) > 0:
                reset = datetime.fromisoformat(r.headers["x-rl-hourly-reset"].replace("Z", "+00:00"))
                self.wait_until = max(self.wait_until, reset.timestamp() + 1)
        except Exception:
            pass

    def api(self, path):
        r = None
        for _ in range(4):
            while time.time() < self.wait_until and not self.stop.is_set():
                time.sleep(0.5)
            r = self.http.get(API + path)
            self._note(r)
            if r.status_code != 429:
                return r
            self.wait_until = time.time() + int(r.headers.get("retry-after", 30))
        return r

    def validate(self):
        r = self.api("/users/validate.json")
        return r.status_code, (r.json() if r.status_code == 200 else {}), r.headers

    # -- control
    def cancel(self, idx):
        self.cancels.setdefault(idx, threading.Event()).set()

    def cancel_all(self):
        self.stop.set()

    def start(self, tasks):
        for i in tasks:
            self.cancels.setdefault(i, threading.Event())
        threading.Thread(target=self._run, args=(tasks,), daemon=True).start()

    def _run(self, tasks):
        with ThreadPoolExecutor(self.n) as ex:
            list(ex.map(lambda kv: self._safe(*kv), tasks.items()))
        self.http.close()
        self.on_done()

    def _safe(self, idx, t):
        try:
            self._one(idx, t)
        except Exception as e:  # network / disk errors
            self._fail(idx, t, f"{type(e).__name__}: {str(e)[:120]}", t.get("src") or t.get("dl") or page_url(t["game"], t["modid"], t.get("fileid", 0)))

    def _fail(self, idx, t, reason, source):
        self.fails[idx] = (reason, source)
        self.on_event(idx, "Failed", 0, 0, reason)

    def _cancelled(self, idx):
        return self.stop.is_set() or self.cancels[idx].is_set()

    def _get(self, idx, uri, final, size, src):
        """stream uri into final via .part (resumable); True when the finished file is in place, else the event is already emitted"""
        ev = self.on_event
        part = final + ".part"
        total = 0
        for attempt in (0, 1):
            have = os.path.getsize(part) if os.path.exists(part) else 0
            with httpx.stream("GET", uri, headers={"Range": f"bytes={have}-"} if have else {}, follow_redirects=True,
                              timeout=httpx.Timeout(30, read=60)) as resp:
                if resp.status_code == 416:  # stale part file
                    os.remove(part)
                    continue
                if resp.status_code not in (200, 206):
                    return self._fail(idx, {}, f"Download server returned HTTP {resp.status_code}", src)
                if resp.status_code == 200:
                    have = 0
                total = have + int(resp.headers.get("content-length", 0))
                done, last = have, 0.0
                with open(part, "ab" if have else "wb") as fh:
                    for chunk in resp.iter_bytes(1 << 16):
                        if self._cancelled(idx):
                            ev(idx, "Cancelled", done, total, "Partial file kept - resumes next time")
                            return False
                        fh.write(chunk)
                        done += len(chunk)
                        if time.time() - last > 0.15:
                            last = time.time()
                            ev(idx, "Downloading", done, total, "")
            break
        if size and os.path.getsize(part) != size and os.path.getsize(part) != total:  # Nexus's API size is occasionally off by a byte; the server's length is authoritative
            return self._fail(idx, {}, f"Downloaded size mismatch ({os.path.getsize(part)} of {size} bytes) - retry", src)
        os.replace(part, final)
        return True

    def _skse(self, idx, t):
        ev = self.on_event
        if os.path.exists(os.path.join(self.dest, skse.ARCHIVE)):
            return ev(idx, "Skipped", 1, 1, "Already in download folder")
        try:
            skse.build_archive(self.dest, lambda ph, d, tot: ev(idx, ph, d, tot, ""), lambda: self._cancelled(idx))
        except skse.Cancelled:
            return ev(idx, "Cancelled", 0, 0, "")
        except Exception as e:
            return self._fail(idx, t, f"Could not build SKSE: {type(e).__name__}: {str(e)[:100]}", skse.HOME)
        ev(idx, "Done", 1, 1, "")

    def _one(self, idx, t):
        ev, g, m, f = self.on_event, t["game"], t["modid"], t.get("fileid", 0)
        src = page_url(g, m, f)
        if self._cancelled(idx):
            return ev(idx, "Cancelled", 0, 0, "")
        hint = t.get("file", "")
        hp = os.path.join(self.dest, hint)
        if hint and os.path.exists(hp) and os.path.getsize(hp):
            return ev(idx, "Skipped", 1, 1, "Already in download folder")
        if t.get("script") == "skse":
            return self._skse(idx, t)
        if t.get("dl"):  # direct (non-Nexus) link; Nexus key is never sent here
            if self._get(idx, t["dl"], hp, 0, t["dl"]):
                n = os.path.getsize(hp)
                ev(idx, "Done", n, n, "")
            return
        ev(idx, "Resolving", 0, 0, "")
        info = {}
        if f:
            r = self.api(f"/games/{g}/mods/{m}/files/{f}.json")
            if r.status_code == 200:
                info = r.json()
            elif r.status_code == 404:
                return self._fail(idx, t, "File no longer on Nexus (removed or hidden by the author)", page_url(g, m))
            elif r.status_code == 401:
                return self._fail(idx, t, "Invalid or expired API key", "https://www.nexusmods.com/settings/api-keys")
            else:
                return self._fail(idx, t, f"Nexus returned HTTP {r.status_code} looking up the file", src)
        else:
            r = self.api(f"/games/{g}/mods/{m}/files.json")
            if r.status_code != 200:
                return self._fail(idx, t, "Mod not found on Nexus (removed or hidden)" if r.status_code == 404 else f"HTTP {r.status_code}", page_url(g, m))
            files = r.json().get("files", [])
            pick = [x for x in files if hint and x["file_name"] == hint] or \
                   [x for x in files if x.get("version") == t.get("version") and x.get("category_name") == "MAIN"]
            if not pick:
                return self._fail(idx, t, "Could not tell which file of this mod is installed (no file ID recorded)", page_url(g, m))
            info, f = pick[0], pick[0]["file_id"]
            src = page_url(g, m, f)
        name = info.get("file_name") or hint or f"{m}-{f}.bin"
        size = info.get("size_in_bytes") or 0
        final = os.path.join(self.dest, name)
        if os.path.exists(final) and (not size or os.path.getsize(final) == size):
            return ev(idx, "Skipped", 1, 1, "Already in download folder")
        r = self.api(f"/games/{g}/mods/{m}/files/{f}/download_link.json")
        if r.status_code in (403, 401):
            return self._fail(idx, t, "Nexus Premium required for automatic downloads (free accounts must click Download on the site)"
                              if r.status_code == 403 else "Invalid or expired API key", src)
        if r.status_code == 429:
            return self._fail(idx, t, "Nexus rate limit reached - retry later", src)
        if r.status_code != 200 or not r.json():
            return self._fail(idx, t, f"No download link available (HTTP {r.status_code})", src)
        uri = r.json()[0]["URI"]
        if not self._get(idx, uri, final, size, src):
            return
        done = os.path.getsize(final)
        with open(final + ".meta", "w", encoding="utf8") as fh:  # lets MO2 recognise the archive
            fh.write(f"[General]\ngameName={MO2_NAME.get(g, g)}\nmodID={m}\nfileID={f}\nversion={info.get('version', '')}\nrepository=Nexus\n")
        ev(idx, "Done", done, done, "")


# ---------- Nexus categories ----------
NC_PATH = os.path.join(DATA, "nexus_cache.json")


def _nc():
    try:
        return json.load(open(NC_PATH, encoding="utf8"))
    except Exception:
        return {"cats": {}, "mods": {}}


def apply_cached_cats(mods):
    mc = _nc()["mods"]
    for m in mods:
        if m["modid"] and not m.get("cat"):
            m["cat"] = mc.get(m["game"], {}).get(str(m["modid"]), "")


def fetch_categories(key, mods, on_progress):
    """fill m['cat'] with each mod's Nexus category (cached in nexus_cache.json); raises on bad key"""
    cache, e = _nc(), Engine(key, "", 1, lambda *a: 0, lambda: 0)
    todo = [m for m in mods if m["modid"] and str(m["modid"]) not in cache["mods"].get(m["game"], {})]
    for g in {m["game"] for m in todo}:
        if g not in cache["cats"]:
            r = e.api(f"/games/{g}.json")
            if r.status_code in (401, 403):
                raise PermissionError("Invalid API key")
            r.raise_for_status()
            cache["cats"][g] = {str(c["category_id"]): c["name"] for c in r.json().get("categories", [])}
    lock, n = threading.Lock(), [0]

    def one(m):
        r = e.api(f"/games/{m['game']}/mods/{m['modid']}.json")
        if r.status_code == 200:
            name = cache["cats"].get(m["game"], {}).get(str(r.json().get("category_id")), "Miscellaneous")
        elif r.status_code in (403, 404):
            name = "Removed from Nexus"
        else:
            name = ""  # transient; retried on next refresh
        with lock:
            if name:
                cache["mods"].setdefault(m["game"], {})[str(m["modid"])] = name
            n[0] += 1
            on_progress(n[0], len(todo))
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, todo))
    e.http.close()
    json.dump(cache, open(NC_PATH, "w", encoding="utf8"))
    apply_cached_cats(mods)
