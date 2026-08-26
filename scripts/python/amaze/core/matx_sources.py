"""Online sources, one adapter per library, plain stdlib HTTP + JSON (no `hou`): a `package` source ships `.mtlx` + textures translated into VOPs, a `values` source ships measured shader parameters, and the `amazepkg` source lists every entry of every store package as its own tile, read remotely by ranged requests; categories are each source's own, capitalised, unsuffixed (`_cat`). Network hardening: ▸r/matx-network-hardening."""

from __future__ import annotations

import json
import math
import os
import re
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import amaze
from amaze.core import debug
from amaze.helpers import hostos
from amaze import messages

USER_AGENT = "Amaze/1.0 (Houdini material library)"
TIMEOUT = 30



def _res_rank(label: str) -> int:
    """Sort key for a resolution label; -1 if unrecognised."""
    m = re.search(r"(\d+)\s*k", str(label).lower())
    if not m:
        return -1
    try:
        return int(m.group(1))
    except ValueError:
        return -1


def pick_resolution(available, preferred: str) -> str | None:
    """Exact match, else the NEXT HIGHEST available, else the highest below - a preference is a floor, never a hard failure; None only when nothing is available."""
    if not available:
        return None
    ranked = sorted(
        ((_res_rank(a), a) for a in available if _res_rank(a) > 0),
        key=lambda t: t[0],
    )
    if not ranked:
        return list(available)[0]
    want = _res_rank(preferred)
    if want <= 0:
        want = 2
    for rank, label in ranked:          # exact, then next highest
        if rank >= want:
            return label
    return ranked[-1][1]                # nothing higher - take the largest


_SSL_CONTEXT = None    # built once - assembling an SSL context parses the whole CA bundle


def _ssl_context():
    """A context that actually VERIFIES under Houdini - built on the certifi bundle Houdini ships, because its Python has NO system CA chain and the default context fails every https verification. ▸r/matx-network-hardening"""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        try:
            import certifi

            _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
        except Exception as exc:
            debug.note("no certifi - using the system CA store", error=str(exc))    # a host WITH one verifies fine; one without fails LOUDLY instead of succeeding unverified
            _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


ALLOWED_SCHEMES = ("https",)    # every URL here comes out of a REMOTE JSON document, and urlopen's default opener would fetch file:// - ▸r/matx-network-hardening


def _checked_url(url: str) -> str:
    """`url` when it is one we may fetch, else "" - answered once, so the first request and every redirect are held to it."""
    scheme = urllib.parse.urlparse(str(url or "")).scheme.lower()
    if scheme in ALLOWED_SCHEMES:
        return str(url)
    debug.event("online", "refused a URL the catalogue supplied",
                scheme=scheme or "(none)", url=str(url)[:120])
    return ""


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect may not downgrade the scheme - verification is only worth what the last hop kept."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _checked_url(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _request(url: str, headers=None):
    if not _checked_url(url):
        raise urllib.error.URLError(
            "refused a URL that is not https")
    req = urllib.request.Request(
        url, headers=dict({"User-Agent": USER_AGENT}, **(headers or {})))
    try:
        opener = urllib.request.build_opener(    # an opener for the redirect handler alone; the scheme checks keep the default FileHandler unreachable rather than removed - ▸r/matx-network-hardening
            urllib.request.HTTPSHandler(context=_ssl_context()),
            _HttpsOnlyRedirects())
        return opener.open(req, timeout=TIMEOUT)
    except urllib.error.URLError as exc:
        # NO UNVERIFIED RETRY - a downgrade keyed off ssl.SSLError fires on certificate failure itself; the isinstance below only chooses the SENTENCE. ▸r/matx-network-hardening
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLError):
            host = urllib.parse.urlsplit(url).netloc
            debug.note(
                "TLS verification FAILED for %s (%s) - refusing to "
                "fetch. The certificate could not be verified, which is "
                "what an intercepting proxy looks like." % (host, reason),
                host=host, error=str(reason))
        raise


def get_text(url: str) -> str:
    """A URL as decoded text - for sources whose catalogue is served as HTML rather than an API."""
    with _request(url) as response:
        return response.read().decode("utf-8", "replace")


def get_json(url: str):
    with _request(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def repair_mtlx_references(mtlx_path: str, dest_dir: str) -> list:
    """Repoint a downloaded .mtlx at the files actually fetched and report every change - a manifest and its document can disagree on a texture's container, and a missing texture renders BLACK with nothing said. ▸r/matx-source-quirks"""
    repairs = []
    try:
        with open(mtlx_path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return repairs

    referenced = set(
        re.findall(r'value="([^"]+\.[A-Za-z][A-Za-z0-9]{1,3})"', text)    # the extension must START with a letter, or value="0.01" reads as file "0" ext "01"
    )
    if not referenced:
        return repairs

    on_disk = {}    # what we actually have, indexed by stem
    for root, _dirs, files in os.walk(dest_dir):
        for name in files:
            stem = os.path.splitext(name)[0]
            rel = os.path.relpath(os.path.join(root, name), dest_dir)
            on_disk.setdefault(stem, rel.replace(os.sep, "/"))

    changed = False
    for ref in referenced:
        if os.path.exists(os.path.join(dest_dir, ref)):
            continue
        stem = os.path.splitext(os.path.basename(ref))[0]
        have = on_disk.get(stem)
        if not have:
            repairs.append({"reference": ref, "fixed_to": None})
            continue
        text = text.replace('value="%s"' % ref, 'value="%s"' % have)
        repairs.append({"reference": ref, "fixed_to": have})
        changed = True

    if changed:
        try:
            with open(mtlx_path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as exc:
            debug.event("online", "mtlx repair could not be written",
                        path=mtlx_path, error=str(exc))    # a swallowed write failure once logged the repair as done while every texture rendered black
            debug.note(
                "the texture paths inside the downloaded material "
                "could not be updated (%s)." % exc, path=mtlx_path)    # the CAUSE only - the caller reports the consequence with the count and name this line does not have
            for entry in repairs:
                entry["fixed_to"] = None
                entry["error"] = str(exc)
    return repairs


def download(url: str, dest_path: str, on_bytes=None) -> str:
    """Stream a URL to disk and answer dest_path - on_bytes(read, total) fires per 64KB chunk (total 0 without Content-Length), the write lands whole via scratch-beside, and a short body raises rather than promoting a fragment. ▸r/matx-source-quirks"""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with hostos.scratch_beside(dest_path) as tmp_path:    # a fixed .part name was one shared buffer between concurrent fetches
        with _request(url) as resp, open(tmp_path, "wb") as fh:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            read = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                read += len(chunk)
                if on_bytes is not None:
                    on_bytes(read, total)
        if total and read != total:    # HTTPResponse does not raise on a short body, so a cut transfer exits NORMALLY and would promote a fragment - ▸r/matx-source-quirks
            raise OSError(
                "truncated download: got %d of %d bytes from %s"
                % (read, total, url)
            )
    return dest_path


def _as_text(value) -> str:
    """Whatever a source gave us, as a display string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return ", ".join(str(v) for v in value.keys())
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    return str(value)


class MatxRecord:
    """One material from any source, normalised."""

    def __init__(
        self,
        source,
        uid,
        title,
        author="",
        category="",
        tags=None,
        preview_url="",
        licence="",
        kind="package",
        payload=None,
    ):
        self.source = source
        self.uid = uid
        self.title = title
        self.author = _as_text(author)    # sources send a LIST, a dict of names or a citation string - normalised once so nothing downstream cares
        self.category = category      # capitalised, unsuffixed (see _cat)
        self.tags = tags or []
        self.preview_url = preview_url
        self.licence = licence
        self.kind = kind              # "package" | "values" | "amazepkg"
        self.payload = payload or {}

    def __repr__(self):
        return "<MatxRecord %s/%s %r>" % (self.source, self.kind, self.title)

    def to_dict(self) -> dict:
        """Plain-dict form for the on-disk catalogue cache."""
        return {
            "source": self.source, "uid": self.uid, "title": self.title,
            "author": self.author, "category": self.category,
            "tags": self.tags, "preview_url": self.preview_url,
            "licence": self.licence, "kind": self.kind,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MatxRecord":
        return cls(
            source=d.get("source", ""), uid=d.get("uid", ""),
            title=d.get("title", "Untitled"), author=d.get("author", ""),
            category=d.get("category", ""), tags=d.get("tags") or [],
            preview_url=d.get("preview_url", ""),
            licence=d.get("licence", ""), kind=d.get("kind", "package"),
            payload=d.get("payload") or {},
        )


class MatxSource:
    """Adapter interface. Subclasses must not import hou."""

    name = ""
    licence = ""
    kind = "package"

    def page_url(self, record) -> str:
        """A link back to where this material came from, for crediting the creators - the exact page where the scheme is known, else the library's home."""
        return ""

    def list_materials(self, search="", offset=0, limit=60) -> list:
        raise NotImplementedError

    def resolutions(self, record) -> list:
        return []

    def fetch(self, record, resolution, dest_dir, progress=None) -> dict:
        """Package sources download+extract and answer {"mtlx": path}, value sources {"values": {...}}; the Amaze source does not fetch - its tiles import by ranged member reads (`read_thumb_to`, `packages.import_entries`). progress(frac) gets 0..1 for THIS record's whole download when given."""
        raise NotImplementedError

    def _cat(self, name):
        """One clean Capitalised category from whatever shape a source sends (a string, a list, absent), unsuffixed - the source is already the View > Online Materials entry you came in through."""
        if isinstance(name, (list, tuple)):
            name = name[0] if name else None
        name = (str(name).strip() if name else "") or "Uncategorized"
        return " ".join(w[:1].upper() + w[1:] for w in name.split())
    def refresh(self):
        """Drop this source's cache so the next listing rebuilds - Refresh is the user asking us to go and LOOK; table-shipping sources drop their table cache too, so the next load re-queries the live site."""
        return None

    def needs_download(self, record) -> bool:
        """True when importing fetches bytes - package sources always, a values source only when its shipped table does not know the material."""
        return getattr(record, "kind", "") != "values"



class GPUOpenSource(MatxSource):
    """AMD GPUOpen MaterialX Library - true .mtlx + texture packages in resolution variants labelled like `1k 8b`, MIT Public Domain."""

    name = "GPUOpen"
    licence = "MIT Public Domain"
    API = "https://api.matlib.gpuopen.com/api"    # "matlib" is THEIR hostname, never ours to rename - ▸r/matx-source-quirks

    def page_url(self, record) -> str:
        return "https://matlib.gpuopen.com/"    # no confirmed per-material permalink scheme, so the library home

    def __init__(self):
        self._categories = None

    def _category_map(self):
        if self._categories is not None:
            return self._categories
        cats = {}    # built LOCALLY, published only on success - caching {} on failure held every material in Uncategorized for the session. ▸r/matx-source-quirks
        try:
            data = get_json(self.API + "/categories/?limit=100")
            for c in data.get("results", []):
                cats[c.get("id")] = c.get("title")
        except Exception as exc:                            # noqa: BLE001
            debug.event("online", "category lookup failed",
                        source=self.name, url=self.API, error=str(exc))
            # Uncategorized in the US spelling, matching every other surface AND the label this sentence quotes
            debug.note(
                "could not read the categories from %s (%s), so its "
                "materials are all listed under Uncategorized for "
                "now. The materials themselves are fine."
                % (self.name, exc))
            return {}       # not cached: the next call tries again
        self._categories = cats
        return self._categories

    def list_materials(self, search="", offset=0, limit=60):
        url = "%s/materials/?limit=%d&offset=%d" % (self.API, limit, offset)
        if search:
            url += "&search=" + urllib.parse.quote(search)
        data = get_json(url)
        cats = self._category_map()
        out = []
        for r in data.get("results", []):
            cat_ids = r.get("category") or []
            if not isinstance(cat_ids, list):
                cat_ids = [cat_ids]
            cat = next(
                (cats.get(c) for c in cat_ids if cats.get(c)), "Uncategorized"
            )
            renders = r.get("renders") or []
            out.append(
                MatxRecord(
                    source=self.name,
                    uid=r.get("id"),
                    title=r.get("title") or "Untitled",
                    author=r.get("author") or "",
                    category=self._cat(cat),
                    tags=[],
                    preview_url=(
                        "%s/renders/%s/download_thumbnail/"    # the verified endpoint ("/thumbnail/" 404s), a documented 302 the opener follows
                        % (self.API, renders[0])
                        if renders else ""
                    ),
                    licence=r.get("license") or self.licence,
                    kind="package",
                    payload={"packages": r.get("packages") or []},
                )
            )
        return out

    def _packages(self, record):
        """Resolve the material's package list to (resolution, id) pairs."""
        found = []
        failures = []
        for pid in record.payload.get("packages", []):
            try:
                p = get_json("%s/packages/%s/" % (self.API, pid))
            except Exception as exc:                        # noqa: BLE001
                failures.append(str(exc))    # say WHY: an unreachable host and a truly package-less material once produced the identical message
                continue
            label = p.get("label") or ""
            if _res_rank(label) > 0:
                found.append((label.split()[0], pid, p.get("file_url")))
        if not found and failures:
            debug.event("online", "package lookup failed",
                        source=self.name, title=record.title,
                        errors=failures[:3])
            debug.note(    # one sentence shape for both unreachable-host notes in this file: the site's NAME, and the HTTP text in the data
                "could not reach %s, so no download sizes are listed "
                "for %s. Try again in a moment."
                % (self.name, record.title), errors=failures[:3])
        return found

    def _resolved_packages(self, record):
        """This record's packages, looked up once and cached ON SUCCESS ONLY - caching an empty answer pins a network failure on the material until the next Refresh rebuilds the records. ▸r/matx-source-quirks"""
        cached = record.payload.get("_resolved")
        if cached:
            return cached
        found = self._packages(record)    # not setdefault: its default evaluates eagerly, which was no cache at all
        if found:
            record.payload["_resolved"] = found
        return found

    def resolutions(self, record):
        pkgs = self._resolved_packages(record)    # each resolution exists twice (8- and 16-bit) - the UI offers resolutions, not bit depths
        seen = []
        for res, _pid, _url in pkgs:
            if res not in seen:
                seen.append(res)
        return seen

    def fetch(self, record, resolution, dest_dir, progress=None):
        pkgs = self._resolved_packages(record)
        chosen = None
        for res, _pid, url in pkgs:
            if res == resolution:
                chosen = url
                break
        if chosen is None and pkgs:
            chosen = pkgs[-1][2]
        if not chosen:
            raise RuntimeError("no downloadable package for " + record.title)
        os.makedirs(dest_dir, exist_ok=True)
        zip_path = os.path.join(dest_dir, "_package.zip")

        def on_bytes(read, total):
            if progress and total:
                progress(read / total)

        download(chosen, zip_path, on_bytes=on_bytes)    # cleanup below sits IN A FINALLY: a BadZipFile (a captive portal's HTML with a correct length, past the truncation guard) once left the DESTINATION reading as already-downloaded-but-mtlx-less forever - ▸r/matx-source-quirks
        try:
            with zipfile.ZipFile(zip_path) as zf:
                safe = []    # member paths come from the NETWORK, and extractall honours ../ and absolute paths - ▸r/matx-network-hardening
                skipped = []
                for member in zf.namelist():
                    try:
                        hostos.contained_join(dest_dir, member)    # realpaths, not normpath - a planted symlink cannot be the hop out
                    except hostos.PathEscape:
                        skipped.append(member)
                    else:
                        safe.append(member)
                if skipped:
                    debug.event("online", "skipped archive paths outside "    # aggregated - one archive can carry many bad paths, and a dialog per path is a fault of its own
                                "the library", count=len(skipped),
                                members=skipped[:20])
                    debug.alert(
                        messages.UNSAFE_ARCHIVE_PATHS_SKIPPED
                        % len(skipped),
                        key="online-unsafe-archive-paths")
                zf.extractall(dest_dir, members=safe)
        finally:
            hostos.discard_scratch(zip_path)
        if progress:
            progress(1.0)
        return {"mtlx": _find_mtlx(dest_dir)}


class PolyHavenSource(MatxSource):
    """Poly Haven textures, CC0 - a real .mtlx per resolution plus an explicit manifest of its textures rather than a zip, so we fetch the document and each include."""

    name = "PolyHaven"
    licence = "CC0"
    API = "https://api.polyhaven.com"

    def page_url(self, record) -> str:
        return "https://polyhaven.com/a/%s" % record.uid

    def list_materials(self, search="", offset=0, limit=60):
        data = get_json(self.API + "/assets?type=textures")
        items = sorted(data.items(), key=lambda kv: kv[1].get("name", ""))
        if search:
            s = search.lower()
            items = [
                kv for kv in items
                if s in (kv[1].get("name", "") or "").lower()
                or any(s in t.lower() for t in (kv[1].get("tags") or []))
            ]
        out = []
        for uid, r in items[offset:offset + limit]:
            cats = r.get("categories") or []
            out.append(
                MatxRecord(
                    source=self.name,
                    uid=uid,
                    title=r.get("name") or uid,
                    author=", ".join((r.get("authors") or {}).keys()),
                    category=self._cat(cats[0] if cats else None),
                    tags=r.get("tags") or [],
                    preview_url=r.get("thumbnail_url") or "",
                    licence=self.licence,
                    kind="package",
                    payload={},
                )
            )
        return out

    def _files(self, record):
        if "_files" not in record.payload:
            record.payload["_files"] = get_json(
                "%s/files/%s" % (self.API, record.uid)
            )
        return record.payload["_files"]

    def resolutions(self, record):
        try:
            return sorted(
                (self._files(record).get("mtlx") or {}).keys(),
                key=_res_rank,
            )
        except Exception as exc:                            # noqa: BLE001
            # say WHY, as at _packages: an empty list must mean only "the API says there are no mtlx variants". ▸r/matx-source-quirks
            debug.event("online", "resolution lookup failed",
                        source=self.name, title=record.title,
                        url=self.API, error=str(exc))
            debug.note(
                "could not reach %s, so no download sizes are listed "
                "for %s. Try again in a moment."
                % (self.name, record.title), error=str(exc))
            return []

    def fetch(self, record, resolution, dest_dir, progress=None):
        mtlx_all = self._files(record).get("mtlx") or {}
        if not mtlx_all:
            raise RuntimeError(    # explicit: StopIteration's str() is EMPTY, so the caller's "Download failed: %s" printed nothing after the colon
                "no .mtlx variants listed for " + record.title)
        entry = mtlx_all.get(resolution) or next(iter(mtlx_all.values()))
        doc = entry.get("mtlx") if isinstance(entry, dict) else None
        if not doc:
            raise RuntimeError("no .mtlx for " + record.title)
        os.makedirs(dest_dir, exist_ok=True)
        mtlx_path = os.path.join(
            dest_dir, os.path.basename(urllib.parse.urlparse(doc["url"]).path)
        )
        files = [(doc["url"], mtlx_path)]    # the .mtlx plus each referenced texture; progress folds the current file's bytes into "file i of n"
        unsafe = []
        for rel, info in (doc.get("include") or {}).items():
            try:
                target = hostos.contained_join(dest_dir, rel)    # the manifest's relative paths come straight from API JSON - ▸r/matx-network-hardening
            except hostos.PathEscape:
                unsafe.append(rel)
                continue
            files.append((info["url"], target))
        if unsafe:
            debug.event("online", "skipped include paths outside the "    # same shape and the same alert KEY as the archive case - one situation to the user, never two interruptions
                        "library", count=len(unsafe), paths=unsafe[:20])
            debug.alert(
                messages.UNSAFE_ARCHIVE_PATHS_SKIPPED
                % len(unsafe),
                key="online-unsafe-archive-paths")
        n = len(files)
        for i, (url, path) in enumerate(files):
            def on_bytes(read, total, i=i):
                if progress and total:
                    progress((i + read / total) / n)
            download(url, path, on_bytes=on_bytes)
            if progress:
                progress((i + 1) / n)
        return {"mtlx": mtlx_path}


class PhysicallyBasedSource(MatxSource):
    """PhysicallyBased - MEASURED reference values, no textures: tier A preset materials (an mtlxstandard_surface set to real aluminium, real gold), the whole dataset ~69 KB of JSON."""

    name = "PhysicallyBased"
    licence = "CC0 1.0 - physicallybased.info (Anton Palmqvist)"    # stated by the project itself; the vague "see source reference" this replaced was stored verbatim on every import
    kind = "values"
    API = "https://api.physicallybased.info"

    def page_url(self, record) -> str:
        return "https://physicallybased.info/"

    TABLE_FILE = "physicallybased_materials.json"    # the shipped dataset browsing reads - instant and offline; the live API is the fallback, never a blocking fetch behind a click

    def __init__(self):
        self._all = None

    def refresh(self):
        self._all = None    # the next load (worker thread) goes to the API - never fetch HERE, refresh() runs on the UI thread

    def _usable(self, payload) -> bool:
        """Is a live response worth preferring over the shipped table - REACHABLE is not CORRECT, so it must look like the dataset: a list of name+colour entries, not dramatically smaller than what ships. ▸r/matx-source-quirks"""
        if not isinstance(payload, list) or not payload:
            return False
        good = [
            item for item in payload
            if isinstance(item, dict) and item.get("name")
            and isinstance(item.get("color"), (list, tuple))
            and len(item["color"]) >= 3
        ]
        if len(good) < len(payload) // 2:
            return False
        try:
            shipped = len(json.load(
                open(self._table_path(), encoding="utf-8")
            ).get("materials", {}))
        except (OSError, ValueError):
            shipped = 0
        return len(good) >= max(1, shipped // 2)    # a real shrink happens (withdrawn materials); losing MOST of the set means it is not the dataset

    def _table_path(self) -> str:
        return amaze.package_file("res", self.TABLE_FILE)

    def _load(self):
        """The dataset - LIVE when reachable and usable, the shipped table when not; only the catalogue WORKER calls this, so the request never touches the UI thread and the table keeps browsing offline."""
        if self._all is not None:
            return self._all
        try:
            live = get_json(self.API + "/materials")
            if self._usable(live):
                self._all = live
                debug.event("online", "PhysicallyBased from the API",
                            materials=len(live))
                return self._all
            debug.event("online", "PhysicallyBased API returned something "
                        "unusable - keeping the shipped table",
                        got=len(live) if hasattr(live, "__len__") else "?")
        except Exception as exc:                       # noqa: BLE001
            debug.event("online", "PhysicallyBased API unreachable - "
                        "using the shipped table", error=str(exc))
        try:
            with open(self._table_path(), encoding="utf-8") as handle:
                table = json.load(handle).get("materials", {})
            self._all = [    # the table is keyed by name; the class expects the API's list-of-dicts shape, name included
                dict(entry, name=name)
                for name, entry in sorted(table.items())
            ]
            debug.event("online", "PhysicallyBased table loaded",
                        materials=len(self._all))
        except (OSError, ValueError) as exc:
            debug.event("online", "PhysicallyBased table unreadable",
                        error=str(exc))
            live = get_json(self.API + "/materials")    # the transient-first-failure re-fetch, THROUGH _usable, never around it - ▸r/matx-source-quirks
            if not self._usable(live):
                raise ValueError(    # not cached: _all stays None, so a later refresh tries again instead of serving a refusal for the session
                    "the PhysicallyBased response is not the dataset, "
                    "and the shipped table could not be read"
                )
            self._all = live
            debug.event("online", "PhysicallyBased from the API - the "
                        "shipped table is unreadable",
                        materials=len(live))
        return self._all

    def list_materials(self, search="", offset=0, limit=60):
        items = self._load()
        if search:
            s = search.lower()
            def _hay(m):
                cat = m.get("category")
                if isinstance(cat, (list, tuple)):
                    cat = " ".join(str(c) for c in cat)
                return "%s %s" % (m.get("name") or "", cat or "")
            items = [m for m in items if s in _hay(m).lower()]
        out = []
        for m in items[offset:offset + limit]:
            out.append(
                MatxRecord(
                    source=self.name,
                    uid=m.get("name"),
                    title=m.get("name") or "Untitled",
                    author="Anton Palmqvist",    # NOT m["reference"] - that field is a render URL and once showed as "by https://raw.githubusercontent.com/..."
                    category=self._cat(m.get("category")),
                    tags=m.get("tags") or [],
                    preview_url="",
                    licence=self.licence,
                    kind="values",
                    payload={"values": m},
                )
            )
        return out

    def resolutions(self, record):
        return []           # nothing to download

    def fetch(self, record, resolution, dest_dir, progress=None):
        return {"values": record.payload.get("values", {})}


class RGLSource(MatxSource):
    """EPFL RGL - MEASURED materials, CC0: each ships as a measured BSDF (`tensor_file`), base colour and roughness are DERIVED from it, metalness is the one keyword-based inference (recorded in the import note), and everything else stays at shader default rather than invented. The maths and its earned word-lists: ▸r/rgl-values"""

    name = "RGL"
    licence = "CC0 1.0 - EPFL Realistic Graphics Lab"
    kind = "values"
    SITE = "https://rgl.epfl.ch/materials"
    CDN = "https://d38rqfq1h7iukm.cloudfront.net/media/materials"

    METAL_WORDS = (    # a measured BSDF cannot state conductor-ness, so the inference is keyword-based, word-boundary, and reported
        "metal", "metallic", "aluminium", "aluminum", "copper", "steel",
        "brass", "bronze", "chrome", "gold", "golden", "silver", "nickel",
        "iron", "titanium", "tin", "zinc", "foil",
    )

    DIELECTRIC_WORDS = (    # these OVERRULE a metal match outright - the earned cases live at ▸r/rgl-values
        "vinyl", "wrap", "wrapping", "fabric", "felt", "silk", "velvet",
        "wool", "cotton", "leather", "wood", "ceramic",
        "paint", "primer", "lacquer", "varnish",
    )

    DARKEST_CONDUCTOR = 0.25    # well below the darkest measured metal (Silicon 0.426), well above the dark "metallic" coatings that trip the keywords (0.09)

    TABLE_FILE = "rgl_materials.json"    # values harvested once from every published measurement - browsing shows real colour instantly, importing needs no download

    def refresh(self):
        self._names = None

    def needs_download(self, record) -> bool:
        return str(getattr(record, "uid", "")) not in self.table()    # an unknown-to-the-table material still costs a multi-hundred-KB BSDF - that one DOES need the bar

    def __init__(self):
        self._names = None
        self._table = None

    def table(self) -> dict:
        """uid -> measured values, read once from the shipped table."""
        if self._table is None:
            path = amaze.package_file("res", self.TABLE_FILE)
            try:
                with open(path, encoding="utf-8") as handle:
                    self._table = json.load(handle).get("materials", {})
            except (OSError, ValueError) as exc:
                debug.event("online", "RGL table unreadable", error=str(exc))
                self._table = {}
        return self._table

    def page_url(self, record) -> str:
        return "%s/%s" % (self.SITE, record.uid)

    def _catalogue(self):
        """Material names, the shipped table UNIONED with the live site - new publications simply appear, only the catalogue WORKER thread calls this, and unreachable means the table alone answers so offline browsing keeps working."""
        if self._names is None:
            names = sorted(self.table().keys())
            try:
                html = get_text(self.SITE)
                live = set(re.findall(
                    r"/media/materials/([a-z0-9_]+)/", html
                ))
                names = sorted(set(names) | live)    # UNION, not replace - the table's entries carry measured values the scrape does not
                debug.event("online", "RGL catalogue",
                            table=len(self.table()), live=len(live),
                            new=len(live - set(self.table())),
                            total=len(names))
            except Exception as exc:               # noqa: BLE001
                debug.event("online", "RGL site unreachable - "
                            "browsing the shipped table",
                            error=str(exc))
            self._names = names
        return self._names

    def _title(self, uid: str) -> str:
        return uid.replace("_", " ").strip().title()

    def list_materials(self, search="", offset=0, limit=60):
        names = self._catalogue()
        if search:
            needle = search.lower()
            names = [n for n in names if needle in n.lower()]
        out = []
        for uid in names[offset:offset + limit]:
            out.append(
                MatxRecord(
                    source=self.name,
                    uid=uid,
                    title=self._title(uid),
                    author="EPFL Realistic Graphics Lab",
                    category=self._cat(uid.split("_")[0]),
                    tags=["measured"] + uid.split("_"),
                    preview_url="",       # the tile is drawn, not fetched
                    licence=self.licence,
                    kind="values",
                    payload={"values": self._values_for(uid), "uid": uid},    # real measured values, so the tile shows the material's own colour; unknown materials carry {} and fill in on import
                )
            )
        return out

    def resolutions(self, record):
        return []

    def fetch(self, record, resolution, dest_dir, progress=None):
        uid = record.payload.get("uid") or record.uid    # the measurement is a means, not an asset - values sources are called with dest_dir=None, so it lands in the local cache and is reused on the next import
        entry = self.table().get(uid)
        if entry:
            values = {    # already measured at harvest time - no download, no wait
                "color": entry.get("color"),
                "roughness": entry.get("roughness"),
                "metalness": entry.get("metalness"),
            }
            return {"values": values,
                    "note": self._note(entry.get("description", ""), values)}
        folder = dest_dir or os.path.join(hostos.cache_root(), "rgl")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            folder = dest_dir or tempfile.gettempdir()    # NOT "." - a CWD target dropped .bsdf files wherever Houdini started and made the reuse check depend on it
        target = hostos.contained_join(    # uid comes from the REMOTE catalogue - safe_filename + contained_join, ▸r/matx-network-hardening
            folder, "%s_rgb.bsdf" % hostos.safe_filename(str(uid)))
        if os.path.exists(target) and not self._is_measurement(target):
            debug.event("online", "cached RGL measurement is not a "    # a cached error page would otherwise poison this material permanently
                        "tensor_file - refetching", uid=uid, path=target)
            try:
                os.remove(target)
            except OSError:
                pass
        if not os.path.exists(target):
            on_bytes = None    # a 0..1 FRACTION per fetch's contract - a string here met a numeric clamp as a TypeError, hidden while no caller passed the callback
            if progress is not None:
                def on_bytes(read, total):
                    progress(min(1.0, read / total) if total else 0.0)
            download("%s/%s/%s_rgb.bsdf" % (self.CDN, uid, uid), target,
                     on_bytes)
            if not self._is_measurement(target):
                try:
                    os.remove(target)
                except OSError:
                    pass
                raise ValueError(
                    "%s did not return a measurement (the download is "
                    "not a tensor_file)" % uid
                )
        values, note = self.values_from_bsdf(target, uid)
        return {"values": values, "note": note, "files": [target]}

    def _values_for(self, uid: str) -> dict:
        """Shading values for one material from the shipped table, in the shape the shader builder and the tile painter expect."""
        entry = self.table().get(uid)
        if not entry:
            return {}
        return {
            "color": entry.get("color"),
            "roughness": entry.get("roughness"),
            "metalness": entry.get("metalness"),
        }

    @classmethod
    def infer_metal(cls, uid: str, description: str = "",
                    color=None) -> bool:
        """Metal or dielectric from the name, the measurement description and - when known - what it actually reflects; the MEASUREMENT overrules the words, because no bare conductor is dark. ▸r/rgl-values"""
        if color and max(color) < cls.DARKEST_CONDUCTOR:
            return False
        words = set(re.findall(
            r"[a-z]+", ("%s %s" % (uid or "", description or "")).lower()
        ))
        if words & set(cls.DIELECTRIC_WORDS):
            return False
        return bool(words & set(cls.METAL_WORDS))

    @staticmethod
    def _note(description: str, values: dict) -> str:
        """How each number was arrived at - stored on the material."""
        return (
            "%s\n\nMeasured by EPFL RGL (CC0). Base colour = mean "
            "reflectance per channel at normal incidence %s; specular "
            "roughness = GGX alpha %s from the measured NDF half-width. "
            "Metalness %s was inferred from the material's name and "
            "description - the measurement itself does not state it."
            % (description, values.get("color"), values.get("roughness"),
               values.get("metalness"))
        )

    BSDF_MAGIC = b"tensor_file\0"    # every RGL measurement is a Mitsuba tensor_file; anything else is an error page or a truncated download

    @classmethod
    def _is_measurement(cls, path: str) -> bool:
        """Does this file actually start like an RGL measurement?"""
        try:
            with open(path, "rb") as handle:
                return handle.read(len(cls.BSDF_MAGIC)) == cls.BSDF_MAGIC
        except OSError:
            return False

    @classmethod
    def values_from_bsdf(cls, path: str, uid: str = ""):
        """(values, note) for one measured file - the whole extraction, a classmethod so it tests without the network; the derivations: ▸r/rgl-values"""
        from amaze.core import bsdf_reader

        data, _version, fields = bsdf_reader.read(path)
        description = ""
        if "description" in fields:
            raw, _shape = bsdf_reader.values(data, fields["description"])
            description = bytes(raw).decode("utf-8", "replace").strip()

        rgb, shape = bsdf_reader.values(data, fields["rgb"])    # base colour: mean reflectance per channel at normal incidence
        _phi, _theta, channels, height, width = shape
        plane = height * width
        colour = []
        for channel in range(channels):
            start = channel * plane
            chunk = rgb[start:start + plane]
            colour.append(round(max(0.0, sum(chunk) / len(chunk)), 5))    # clamped at zero: noise around black measures slightly negative, and that is not a colour - figures at ▸r/rgl-values

        ndf, ndf_shape = bsdf_reader.values(data, fields["ndf"])    # roughness: GGX alpha from the NDF's half-width, alpha = tan(theta_half) / 0.6436 - ▸r/rgl-values
        columns = ndf_shape[-1]
        profile = ndf[:columns]
        half = max(profile) / 2.0 if profile else 0.0
        index = next(
            (i for i, v in enumerate(profile) if v <= half), columns - 1
        )
        theta_half = (index / max(columns - 1, 1)) * (math.pi / 2)
        alpha = math.tan(theta_half) / 0.6436 if theta_half < math.pi / 2 else 1.0
        roughness = round(max(0.001, min(1.0, alpha)), 5)

        metal = cls.infer_metal(uid, description, colour)
        values = {
            "color": colour,
            "roughness": roughness,
            "metalness": 1.0 if metal else 0.0,
        }
        note = (
            "%s\n\nMeasured by EPFL RGL (CC0). Base colour = mean "
            "reflectance per channel at normal incidence %s; specular "
            "roughness = GGX alpha %.4f from the measured NDF half-width "
            "(%.1f degrees). Metalness %s was inferred from the "
            "material's name and description - the measurement itself "
            "does not state it."
            % (description, colour, roughness, math.degrees(theta_half),
               "1" if metal else "0")
        )
        return values, note


def _find_mtlx(root):
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".mtlx"):
                return os.path.join(dirpath, f)
    return None


RANGED_BLOCK = 1 << 16


class RangedFile:
    """A seekable read-only file over `get_range(start, end) -> bytes`, block-cached so zipfile's seeks cost a handful of requests - integrity per member is the zip's own CRC under TLS."""

    def __init__(self, size: int, get_range, notify=None):
        self.size = int(size)
        self._get = get_range
        self._blocks = {}
        self._pos = 0
        self.notify = notify    # notify(blocks_held, blocks_total) after every fetched block - what keeps a UI pumping through a long transfer instead of freezing

    def _total_blocks(self) -> int:
        return max(1, (self.size - 1) // RANGED_BLOCK + 1)

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        self._pos = (offset if whence == 0
                     else self._pos + offset if whence == 1
                     else self.size + offset)
        return self._pos

    def tell(self):
        return self._pos

    def _block(self, index: int) -> bytes:
        if index not in self._blocks:
            start = index * RANGED_BLOCK
            end = min(self.size, start + RANGED_BLOCK) - 1
            self._blocks[index] = self._get(start, end)
            if self.notify is not None:
                self.notify(len(self._blocks), self._total_blocks())
        return self._blocks[index]

    def read(self, n=-1) -> bytes:
        if n < 0:
            n = self.size - self._pos
        out = []
        while n > 0 and self._pos < self.size:
            index, at = divmod(self._pos, RANGED_BLOCK)
            chunk = self._block(index)[at:at + n]
            if not chunk:
                break
            out.append(chunk)
            self._pos += len(chunk)
            n -= len(chunk)
        return b"".join(out)


class AmazeSource(MatxSource):
    """Amaze packages from the official store, per TILE: the store is folders of `.amazepkg` and nothing else, each package a small remote database read with ranged requests - the folder is the category, every ENTRY in every package is one record (palette colours and the manifest entry ride the payload; a plain-file entry becomes a bare tile that lands in the library's import folder), and importing reads only the chosen tiles' members."""

    name = "Amaze"
    licence = ""
    kind = "amazepkg"
    TREE_URL = ("https://api.github.com/repos/Timour/AmazePackages/"
                "git/trees/main?recursive=1")
    RAW_BASE = "https://raw.githubusercontent.com/Timour/AmazePackages/main/"

    def __init__(self):
        self._paths = None
        self._bundles = {}
        self._manifests = {}
        self._remotes = {}    # url -> the RangedFile under the bundle, for progress_hook
        self._sizes = {}    # url -> byte size off the tree listing; a package known smaller than one block fetches whole in ONE plain request

    PACKAGES_ROOT = "packages"    # categories live UNDER this folder, so the repo root stays free for infrastructure

    @classmethod
    def _tree_rows(cls, nodes) -> list:
        """(category, filename, url, size) for every `packages/<category>/<file>.amazepkg` blob - anything shaped otherwise is invisible."""
        rows = []
        for node in nodes:
            path = str(node.get("path") or "")
            if node.get("type") != "blob" \
                    or not path.endswith(".amazepkg"):
                continue
            parts = path.split("/")
            if len(parts) != 3 or parts[0] != cls.PACKAGES_ROOT:
                continue
            rows.append((parts[1], parts[2], cls.RAW_BASE + path,
                         int(node.get("size") or 0)))
        return rows

    def _tree(self) -> list:
        rows = self._tree_rows(get_json(self.TREE_URL).get("tree", ()))
        self._sizes = {url: size for _f, _n, url, size in rows}
        return [(folder, name, url) for folder, name, url, _s in rows]    # canned test sources override this whole method with 3-tuples, so sizes stay an optional accelerant

    def _open_package(self, url: str):
        """A zipfile over ranged reads of the hosted package, cached until Refresh."""
        if url not in self._bundles:
            checked = _checked_url(url)
            known = getattr(self, "_sizes", {}).get(url)
            if known and known <= RANGED_BLOCK:    # the tree already named the size - one plain fetch, no probe-416-refetch round-trip
                with _request(checked) as response:
                    tail = response.read()
                size = len(tail)
            else:
                try:
                    with _request(checked,
                                  headers={"Range": "bytes=-%d"
                                           % RANGED_BLOCK}) as response:
                        tail = response.read()
                        spread = str(response.headers.get("Content-Range")
                                     or "")
                    size = int(spread.rsplit("/", 1)[-1]) if "/" in spread \
                        else len(tail)
                except urllib.error.HTTPError as exc:
                    if exc.code != 416:
                        raise
                    with _request(checked) as response:    # the suffix exceeded the object and the CDN answered 416, not the RFC's whole file (▸r/github-ranged-store) - a package this small IS its own tail
                        tail = response.read()
                    size = len(tail)

            def get_range(start, end, _url=checked):
                with _request(_url, headers={
                        "Range": "bytes=%d-%d" % (start, end)}) as resp:
                    return resp.read()

            remote = RangedFile(size, get_range)
            if len(tail) == size:    # the whole object arrived - seed every block, not just the last
                for n in range(0, size, RANGED_BLOCK):
                    remote._blocks[n // RANGED_BLOCK] = \
                        tail[n:n + RANGED_BLOCK]
            else:
                last = (size - 1) // RANGED_BLOCK
                remote._blocks[last] = tail[-(size - last * RANGED_BLOCK):]
            self._remotes[url] = remote
            self._bundles[url] = zipfile.ZipFile(remote)
        return self._bundles[url]

    def progress_hook(self, url: str, callback) -> None:
        """Attach (or detach with None) a per-block progress callback to the hosted package's reader - what the import doors use to keep the download bar moving and the UI pumping."""
        remote = self._remotes.get(url)
        if remote is not None:
            remote.notify = callback

    def _manifest(self, url: str) -> dict:
        if url not in self._manifests:
            from amaze.core import packages
            bundle = self._open_package(url)
            manifest = json.loads(bundle.read(packages.MANIFEST))
            got = manifest.get("format")
            if not isinstance(got, int) or got > packages.FORMAT:    # the same gate as read_manifest, HERE because the remote store is where an old build is guaranteed to meet a newer package
                raise packages.PackageError(
                    "package format %s is newer than the %s this build "
                    "reads" % (got, packages.FORMAT))
            self._manifests[url] = manifest
        return self._manifests[url]

    def refresh(self):
        self._paths = None
        self._manifests = {}
        self._bundles = {}
        self._remotes = {}
        self._sizes = {}

    def list_materials(self, search="", offset=0, limit=60) -> list:
        if self._paths is None:
            self._paths = self._tree()
        rows = []
        for folder, filename, url in self._paths:
            try:
                entries = self._manifest(url).get("entries", ())
            except Exception as exc:                      # noqa: BLE001
                debug.event("online", "package manifest unreadable",
                            url=url, error=str(exc))
                continue
            for n, entry in enumerate(entries):
                record = entry.get("record") or {}
                title = str(record.get("name")
                            or entry.get("name") or "")
                if search and search.lower() not in title.lower():
                    continue
                payload = {"package": url, "entry": entry,
                           "section": str(entry.get("section") or "")}
                colors = [str(c.get("hex") or "")
                          for c in (record.get("colors") or ())
                          if isinstance(c, dict)]
                if colors:
                    payload["colors"] = colors
                files = entry.get("files") or {}
                thumb = files.get("tile_icon") or files.get("thumbnail")    # the CHOSEN icon outranks the render, the way every local section ranks it
                if thumb:
                    payload["thumb_member"] = thumb
                rows.append(MatxRecord(
                    source=self.name,
                    uid="%s/%s#%s" % (folder, filename,
                                      entry.get("id") or n),
                    title=title,
                    category=self._cat(folder),
                    kind="amazepkg",
                    payload=payload))
        return rows[offset:offset + limit]

    def read_thumb_to(self, record, path: str) -> None:
        """One tile's thumbnail member into `path` - a single ranged member read."""
        member = str(record.payload.get("thumb_member") or "")
        if not member:
            raise ValueError("no thumbnail member for " + record.title)
        bundle = self._open_package(record.payload["package"])
        data = bundle.read(member)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)


SOURCES = (AmazeSource, GPUOpenSource, PolyHavenSource,
           PhysicallyBasedSource, RGLSource)


def all_sources():
    return [cls() for cls in SOURCES]
