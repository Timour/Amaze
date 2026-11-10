"""Online material sources, one adapter per library, stdlib HTTP only. ▸r/matx-network-hardening"""

from __future__ import annotations

import contextlib
import functools
import json
import math
import os
import posixpath
import re
import ssl
import struct
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib

import amaze
from amaze.core import debug
from amaze.helpers import hostos, wording
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


COLOUR_MAP_STEMS = ("col1", "coll1", "albedo")    # Poly Haven colour maps named `diff` ▸r/matx-source-quirks


def pick_resolution(available, preferred: str) -> str | None:
    """Exact match, else the next highest, else the highest below; None only when none exist."""
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


@functools.cache
def _ssl_context():
    """A verifying SSL context, built once, since a build parses every CA. ▸r/matx-network-hardening"""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception as exc:
        debug.note("no certifi - using the system CA store", error=str(exc))    # never unverified
        return ssl.create_default_context()


ALLOWED_SCHEMES = ("https",)    # remote JSON supplies every URL here ▸r/matx-network-hardening


def _checked_url(url: str) -> str:
    """`url` when it is one we may fetch, else ""; the first request and every redirect ask it."""
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
        opener = urllib.request.build_opener(    # https only, redirects too ▸r/matx-network-hardening
            urllib.request.HTTPSHandler(context=_ssl_context()),
            _HttpsOnlyRedirects())
        return opener.open(req, timeout=TIMEOUT)
    except urllib.error.URLError as exc:
        # never retried unverified; the check below only picks the message ▸r/matx-network-hardening
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
    """Repoint a downloaded .mtlx at the files fetched; a list of every change. ▸r/matx-source-quirks"""
    repairs = []
    try:
        with open(mtlx_path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return repairs

    referenced = set(
        re.findall(r'value="([^"]+\.[A-Za-z][A-Za-z0-9]{1,3})"', text)    # extension starts with a letter
    )
    if not referenced:
        return repairs

    base = os.path.dirname(mtlx_path)    # a reference is relative to its document, as translated
    on_disk = {}    # what we actually have, indexed by stem
    for root, _dirs, files in os.walk(dest_dir):
        for name in files:
            stem = os.path.splitext(name)[0]
            rel = os.path.relpath(os.path.join(root, name), base)
            on_disk.setdefault(stem, rel.replace(os.sep, "/"))

    changed = False
    for ref in referenced:
        if os.path.exists(os.path.join(base, ref)):
            continue
        stem = os.path.splitext(os.path.basename(ref))[0]
        have = on_disk.get(stem)
        if not have and "_diff_" in stem:    # one colour role, several stems ▸r/matx-source-quirks
            for other in COLOUR_MAP_STEMS:
                have = on_disk.get(stem.replace("_diff_", "_%s_" % other))
                if have:
                    break
        if not have:
            repairs.append({"reference": ref, "fixed_to": None})
            continue
        text = text.replace('value="%s"' % ref, 'value="%s"' % have)
        repairs.append({"reference": ref, "fixed_to": have})
        changed = True

    if changed:
        try:
            with open(mtlx_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError as exc:
            debug.event("online", "mtlx repair could not be written",
                        path=mtlx_path, error=str(exc))
            debug.note(
                "the texture paths inside the downloaded material "
                "could not be updated (%s)." % exc, path=mtlx_path)    # the cause; the caller reports the rest
            for entry in repairs:
                entry["fixed_to"] = None
                entry["error"] = str(exc)
    return repairs


class ShortDownload(OSError):
    """A body that ended before the length its server declared; `read` and `total` say where."""

    def __init__(self, url: str, read: int, total: int) -> None:
        super().__init__("truncated download: got %d of %d bytes from %s"
                         % (read, total, url))
        self.read = read
        self.total = total


class DownloadTooLarge(OSError):
    """A body over the ceiling its caller set, refused as declared or as it arrives."""

    def __init__(self, ceiling: int) -> None:
        super().__init__(messages.DOWNLOAD_TOO_LARGE % wording.byte_size(ceiling))


def _drain(resp, write, on_bytes=None, total=0) -> int:
    """A response body through `write` in 64 KB chunks, on_bytes(read, total) after each."""
    read = 0
    while True:
        chunk = resp.read(1 << 16)
        if not chunk:
            break
        write(chunk)
        read += len(chunk)
        if on_bytes is not None:
            on_bytes(read, total)
    return read


def stream_into(url: str, path: str, on_bytes=None, ceiling: int = 0) -> int:
    """The body at `url` into `path`; the bytes read, or ShortDownload or DownloadTooLarge."""
    with _request(url) as resp, open(path, "wb") as fh:
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        if ceiling and total > ceiling:    # the server's own word, before a byte is read
            raise DownloadTooLarge(ceiling)

        def counted(read, total):
            if ceiling and read > ceiling:    # what arrives, whatever the server declared
                raise DownloadTooLarge(ceiling)
            if on_bytes is not None:
                on_bytes(read, total)

        read = _drain(resp, fh.write, counted, total)
    if total and read != total:    # a short body ends the loop normally ▸r/matx-source-quirks
        raise ShortDownload(url, read, total)
    return read


def ranged_reader(url: str):
    """`get_range(start, end, on_bytes=None)` over one object; on_bytes streams it in chunks."""
    def get_range(start, end, on_bytes=None):
        want = end - start + 1
        with _request(url, headers={"Range": "bytes=%d-%d" % (start, end)}) as resp:
            if on_bytes is None:
                data = resp.read()
            else:
                chunks = []
                _drain(resp, chunks.append, on_bytes, want)
                data = b"".join(chunks)
        if len(data) != want:    # a host that ignores Range answers the whole object
            raise ShortDownload(url, len(data), want)
        return data
    return get_range


def spanned_reader(parts):
    """`get_range` over an archive published in parts [(url, size)], read as one file."""
    spans, offset = [], 0
    for url, size in parts:
        spans.append((offset, int(size), ranged_reader(url)))
        offset += int(size)

    def get_range(start, end, on_bytes=None):
        chunks, done = [], 0
        for first, size, read in spans:
            lo, hi = max(start, first), min(end, first + size - 1)
            if lo > hi:
                continue
            if on_bytes is None:
                chunk = read(lo - first, hi - first)
            else:
                chunk = read(lo - first, hi - first,
                             lambda n, _t, d=done: on_bytes(d + n, end - start + 1))
            chunks.append(chunk)
            done += len(chunk)
        return b"".join(chunks)
    return get_range


def report_unsafe(kind: str, paths) -> None:
    """One log line and ONE alert for remote paths refused for leaving the library."""
    if not paths:
        return
    debug.event("online", "skipped %s paths outside the library" % kind,
                count=len(paths), paths=list(paths)[:20])
    debug.alert(messages.UNSAFE_ARCHIVE_PATHS_SKIPPED % len(paths),
                key="online-unsafe-archive-paths")


@contextlib.contextmanager
def download_operation(name: str):
    """Esc and a progress bar around a download: yields on_bytes(read, total); an Esc is OSError."""
    import hou
    try:
        with hou.InterruptableOperation(name, open_interrupt_dialog=True) as op:    # as online_import
            def on_bytes(read, total):
                op.updateProgress(min(read / total, 1.0) if total else -1.0)
            yield on_bytes
    except hou.OperationInterrupted:
        raise OSError(messages.DOWNLOAD_STOPPED) from None


def download(url: str, dest_path: str, on_bytes=None, ceiling=None) -> str:
    """A URL streamed to `dest_path` through a scratch beside it, refused past an import's own cap."""
    if ceiling is None:
        from amaze.core import packages
        ceiling = packages.MAX_UNPACKED_BYTES    # one figure for what one import brings in ▸r/zip-declared-size
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with hostos.scratch_beside(dest_path) as tmp_path:    # a fixed .part name was one shared buffer between concurrent fetches
        stream_into(url, tmp_path, on_bytes, ceiling)
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
        self.author = _as_text(author)    # a list, a dict of names or a string, as one string
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
    PREVIEWS = ""    # Amaze's own renders of this source, a hosted zip ▸r/simready-release

    def page_url(self, record) -> str:
        """A link to where this material came from: its own page where known, else the library's."""
        return ""

    def list_materials(self, search="", offset=0, limit=60) -> list:
        raise NotImplementedError

    def remember(self, records) -> None:
        """Before a refresh: this source's records from the last full listing, to reuse."""

    def resolutions(self, record) -> list:
        return []

    def fetch(self, record, resolution, dest_dir, progress=None) -> dict:
        """Fetch one record: {"mtlx": path} or {"values": {...}}; progress(0..1) over its download."""
        raise NotImplementedError

    def _cat(self, name):
        """One capitalised category from a string, a list or nothing; "Uncategorized" for none."""
        if isinstance(name, (list, tuple)):
            name = name[0] if name else None
        name = (str(name).strip() if name else "") or "Uncategorized"
        return " ".join(w[:1].upper() + w[1:] for w in name.split())
    def refresh(self):
        """Drop this source's caches so the next listing rebuilds; never fetches; subclasses call it."""
        self._previews = None    # the hosted pictures' places, owned here: a subclass calls super()

    def needs_download(self, record) -> bool:
        """True when importing `record` downloads bytes."""
        return getattr(record, "kind", "") != "values"

    def with_previews(self, records) -> list:
        """`records`, each one with a hosted picture carrying its place in PREVIEWS."""
        places = self._preview_places() if self.PREVIEWS else {}
        for record in records:
            place = places.get(record.uid + ".jpg")
            if place:
                record.payload["preview"] = dict(place)
        return records

    def _preview_places(self) -> dict:
        """Each hosted picture's place {offset, size, crc} off the zip's directory; {} unread."""
        if getattr(self, "_previews", None) is None:
            try:
                bundle, _remote = open_remote_zip([(self.PREVIEWS, remote_size(self.PREVIEWS))])
            except Exception as exc:                      # noqa: BLE001
                debug.event("online", "hosted previews unreadable", source=self.name,
                            error=str(exc))
                return {}
            self._previews = {
                info.filename: {"offset": info.header_offset, "size": info.compress_size,
                                "crc": info.CRC}
                for info in bundle.infolist()
                if info.compress_type == zipfile.ZIP_STORED and info.filename.endswith(".jpg")}
        return self._previews

    def read_thumb_to(self, record, path: str) -> None:
        """A tile's picture: one ranged read of its member's 30-byte header, name and data."""
        place = record.payload.get("preview") or {}
        start, size = int(place["offset"]), int(place["size"])
        last = start + 30 + 1024 + size - 1
        with _request(self.PREVIEWS, {"Range": "bytes=%d-%d" % (start, last)}) as resp:
            blob = resp.read()
        local = len(blob) >= 30 and blob[:4] == b"PK\x03\x04"
        skip = 30 + sum(struct.unpack("<HH", blob[26:30])) if local else 0
        data = blob[skip:skip + size]
        if not skip or len(data) != size or zlib.crc32(data) != int(place["crc"]):
            raise ValueError("the hosted picture for %s is not the one listed" % record.title)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)



class GPUOpenSource(MatxSource):
    """AMD GPUOpen MaterialX Library: .mtlx and texture packages per resolution, like `1k 8b`."""

    name = "GPUOpen"
    licence = "MIT Public Domain"
    PREVIEWS = ("https://github.com/Timour/AmazePackages/releases/download/"
                "gpuopen-previews/gpuopen-previews.zip")
    API = "https://api.matlib.gpuopen.com/api"    # "matlib" is THEIR hostname, never ours to rename - ▸r/matx-source-quirks

    def page_url(self, record) -> str:
        return "https://matlib.gpuopen.com/"    # no confirmed per-material permalink scheme, so the library home

    def __init__(self):
        self._categories = None

    def refresh(self):
        self._categories = None    # never fetch here: refresh() runs on the UI thread
        super().refresh()

    def _category_map(self):
        if self._categories is not None:
            return self._categories
        cats = {}    # cached only on success ▸r/matx-source-quirks
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
                        "%s/renders/%s/download_thumbnail/"    # a 302 the opener follows
                        % (self.API, renders[0])
                        if renders else ""
                    ),
                    licence=r.get("license") or self.licence,
                    kind="package",
                    payload={"packages": r.get("packages") or []},
                )
            )
        return self.with_previews(out)

    def _packages(self, record):
        """Resolve the material's package list to (resolution, id) pairs."""
        found = []
        failures = []
        for pid in record.payload.get("packages", []):
            try:
                p = get_json("%s/packages/%s/" % (self.API, pid))
            except Exception as exc:                        # noqa: BLE001
                failures.append(str(exc))
                continue
            label = p.get("label") or ""
            if _res_rank(label) > 0:
                found.append((label.split()[0], pid, p.get("file_url")))
        if not found and failures:
            debug.event("online", "package lookup failed",
                        source=self.name, title=record.title,
                        errors=failures[:3])
            debug.note(    # the site's name in the sentence, the HTTP text in the data
                "could not reach %s, so no download sizes are listed "
                "for %s. Try again in a moment."
                % (self.name, record.title), errors=failures[:3])
        return found

    def _resolved_packages(self, record):
        """This record's packages, looked up once, cached on success only. ▸r/matx-source-quirks"""
        cached = record.payload.get("_resolved")
        if cached:
            return cached
        found = self._packages(record)
        if found:
            record.payload["_resolved"] = found
        return found

    def resolutions(self, record):
        pkgs = self._resolved_packages(record)    # 8- and 16-bit collapse to one resolution
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

        download(chosen, zip_path, on_bytes=on_bytes)    # the zip is discarded even on failure ▸r/matx-source-quirks
        try:
            with zipfile.ZipFile(zip_path) as zf:
                safe = []    # members that stay inside dest_dir ▸r/matx-network-hardening
                skipped = []
                for member in zf.namelist():
                    try:
                        hostos.contained_join(dest_dir, member)    # realpaths, not normpath - a planted symlink cannot be the hop out
                    except hostos.PathEscape:
                        skipped.append(member)
                    else:
                        safe.append(member)
                from amaze.core import packages
                needed = packages.unpacked_bytes(zf, safe)
                if needed > packages.MAX_UNPACKED_BYTES:    # before the alert, which says the rest imported
                    raise OSError(messages.PACKAGE_TOO_LARGE % (
                        wording.byte_size(needed), wording.byte_size(packages.MAX_UNPACKED_BYTES)))
                report_unsafe("archive", skipped)
                zf.extractall(dest_dir, members=safe)
        finally:
            hostos.discard_scratch(zip_path)
        if progress:
            progress(1.0)
        return {"mtlx": _find_mtlx(dest_dir)}


class PolyHavenSource(MatxSource):
    """Poly Haven textures, CC0: a .mtlx per resolution, fetched with each texture it includes."""

    name = "PolyHaven"
    licence = "CC0"
    API = "https://api.polyhaven.com"
    PREVIEWS = ("https://github.com/Timour/AmazePackages/releases/download/"
                "polyhaven-previews/polyhaven-previews.zip")

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
        return self.with_previews(out)

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
            # a failure is said aloud; [] alone means no mtlx variants ▸r/matx-source-quirks
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
            raise RuntimeError(
                "no .mtlx variants listed for " + record.title)
        entry = mtlx_all.get(resolution) or next(iter(mtlx_all.values()))
        doc = entry.get("mtlx") if isinstance(entry, dict) else None
        if not doc:
            raise RuntimeError("no .mtlx for " + record.title)
        os.makedirs(dest_dir, exist_ok=True)
        mtlx_path = os.path.join(
            dest_dir, os.path.basename(urllib.parse.urlparse(doc["url"]).path)
        )
        files = [(doc["url"], mtlx_path)]    # the .mtlx plus each referenced texture
        unsafe = []
        for rel, info in (doc.get("include") or {}).items():
            try:
                target = hostos.contained_join(dest_dir, rel)    # remote paths ▸r/matx-network-hardening
            except hostos.PathEscape:
                unsafe.append(rel)
                continue
            files.append((info["url"], target))
        report_unsafe("include", unsafe)
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
    """PhysicallyBased: measured reference values, no textures, as preset standard surfaces."""

    name = "PhysicallyBased"
    licence = "CC0 1.0 - physicallybased.info (Anton Palmqvist)"    # as the project states it
    kind = "values"
    API = "https://api.physicallybased.info"
    PREVIEWS = ("https://github.com/Timour/AmazePackages/releases/download/"
                "physicallybased-previews/physicallybased-previews.zip")

    def page_url(self, record) -> str:
        return "https://physicallybased.info/"

    TABLE_FILE = "physicallybased_materials.json"    # the shipped dataset, read offline

    def __init__(self):
        self._all = None

    def refresh(self):
        self._all = None    # never fetch here: refresh() runs on the UI thread
        super().refresh()

    def _usable(self, payload) -> bool:
        """Does a live response look like the dataset, half the shipped size or more? ▸r/matx-source-quirks"""
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
            with open(self._table_path(), encoding="utf-8") as handle:
                shipped = len(json.load(handle).get("materials", {}))
        except (OSError, ValueError):
            shipped = 0
        return len(good) >= max(1, shipped // 2)

    def _table_path(self) -> str:
        return amaze.package_file("res", self.TABLE_FILE)

    def _load(self):
        """The dataset, live when usable, else the shipped table; call from a worker thread only."""
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
            self._all = [    # the name-keyed table in the API's list-of-dicts shape
                dict(entry, name=name)
                for name, entry in sorted(table.items())
            ]
            debug.event("online", "PhysicallyBased table loaded",
                        materials=len(self._all))
        except (OSError, ValueError) as exc:
            debug.event("online", "PhysicallyBased table unreadable",
                        error=str(exc))
            live = get_json(self.API + "/materials")    # one re-fetch, through _usable ▸r/matx-source-quirks
            if not self._usable(live):
                raise ValueError(    # not cached: a later call tries again
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
                    author="Anton Palmqvist",    # m["reference"] is a render URL, not an author
                    category=self._cat(m.get("category")),
                    tags=m.get("tags") or [],
                    preview_url="",
                    licence=self.licence,
                    kind="values",
                    payload={"values": m},
                )
            )
        return self.with_previews(out)

    def resolutions(self, record):
        return []           # nothing to download

    def fetch(self, record, resolution, dest_dir, progress=None):
        return {"values": record.payload.get("values", {})}


class RGLSource(MatxSource):
    """EPFL RGL measured BSDFs, CC0: colour and roughness derived, metalness inferred. ▸r/rgl-values"""

    name = "RGL"
    licence = "CC0 1.0 - EPFL Realistic Graphics Lab"
    kind = "values"
    SITE = "https://rgl.epfl.ch/materials"
    CDN = "https://d38rqfq1h7iukm.cloudfront.net/media/materials"
    PREVIEWS = ("https://github.com/Timour/AmazePackages/releases/download/"
                "rgl-previews/rgl-previews.zip")

    METAL_WORDS = (    # whole words that infer a metal
        "metal", "metallic", "aluminium", "aluminum", "copper", "steel",
        "brass", "bronze", "chrome", "gold", "golden", "silver", "nickel",
        "iron", "titanium", "tin", "zinc", "foil",
    )

    DIELECTRIC_WORDS = (    # these overrule a metal match ▸r/rgl-values
        "vinyl", "wrap", "wrapping", "fabric", "felt", "silk", "velvet",
        "wool", "cotton", "leather", "wood", "ceramic",
        "paint", "primer", "lacquer", "varnish",
    )

    DARKEST_CONDUCTOR = 0.25    # a peak colour below this is never a metal ▸r/rgl-values

    TABLE_FILE = "rgl_materials.json"    # measured values shipped for every published material

    def refresh(self):
        self._names = None
        super().refresh()

    def needs_download(self, record) -> bool:
        return str(getattr(record, "uid", "")) not in self.table()    # an unknown one fetches its BSDF

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
        """Material names: the shipped table plus the live site when reachable; worker thread only."""
        if self._names is None:
            names = sorted(self.table().keys())
            try:
                html = get_text(self.SITE)
                live = set(re.findall(
                    r"/media/materials/([a-z0-9_]+)/", html
                ))
                names = sorted(set(names) | live)    # union, not replace
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
                    payload={"values": self._values_for(uid), "uid": uid},    # {} until imported if unknown
                )
            )
        return self.with_previews(out)

    def resolutions(self, record):
        return []

    def fetch(self, record, resolution, dest_dir, progress=None):
        uid = record.payload.get("uid") or record.uid    # dest_dir=None caches the BSDF locally
        entry = self.table().get(uid)
        if entry:
            values = self._values_for(uid)    # from the table, no download
            return {"values": values,
                    "note": self._note(entry.get("description", ""), values)}
        folder = dest_dir or os.path.join(hostos.cache_root(), "rgl")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            folder = dest_dir or tempfile.gettempdir()
        target = hostos.contained_join(    # uid is remote ▸r/matx-network-hardening
            folder, "%s_rgb.bsdf" % hostos.safe_filename(str(uid)))
        if os.path.exists(target) and not self._is_measurement(target):
            debug.event("online", "cached RGL measurement is not a "
                        "tensor_file - refetching", uid=uid, path=target)
            try:
                os.remove(target)
            except OSError:
                pass
        unread = "%s did not return a measurement (the download is not a tensor_file)" % uid
        fresh = not os.path.exists(target)
        if fresh:
            on_bytes = None    # reports a 0..1 fraction to progress
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
                raise ValueError(unread)
        try:
            values, note = self.values_from_bsdf(target, uid)
        except (struct.error, ValueError, KeyError, IndexError, TypeError,
                ZeroDivisionError) as exc:    # the magic with a body that will not parse
            try:
                os.remove(target)
            except OSError:
                pass
            if fresh or os.path.exists(target):    # one download a fetch, never a loop
                raise ValueError(unread) from exc
            debug.event("online", "cached RGL measurement does not parse - "
                        "refetching", uid=uid, path=target, error=str(exc))
            return self.fetch(record, resolution, dest_dir, progress)
        return {"values": values, "note": note, "files": [target]}

    def _values_for(self, uid: str) -> dict:
        """Shading values for one material from the shipped table, {} for an unknown one."""
        entry = self.table().get(uid)
        if not entry:
            return {}
        values = {
            "color": entry.get("color"),
            "roughness": entry.get("roughness"),
            "metalness": entry.get("metalness"),
        }
        if entry.get("specularColor"):    # a pearl film's colour at the mirror ▸r/rgl-values
            values["specularColor"] = entry["specularColor"]
        return values

    @classmethod
    def infer_metal(cls, uid: str, description: str = "",
                    color=None) -> bool:
        """Metal from name and description; a dark measured `color` overrules the words. ▸r/rgl-values"""
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
        if values.get("specularColor"):
            colour = ("Base colour %s = 0.75 x the colour it reflects at the mirror direction, "
                      "which is also its specular colour %s"
                      % (values.get("color"), values.get("specularColor")))
        else:
            colour = ("Base colour = mean reflectance per channel at normal incidence %s"
                      % values.get("color"))
        return (
            "%s\n\nMeasured by EPFL RGL (CC0). %s; specular "
            "roughness %s, the square root of the GGX alpha from the "
            "measured NDF half-width. "
            "Metalness %s was inferred from the material's name and "
            "description - the measurement itself does not state it."
            % (description, colour, values.get("roughness"),
               values.get("metalness"))
        )

    BSDF_MAGIC = b"tensor_file\0"    # every RGL measurement starts with this

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
        """(values, note) for one measured file, no network needed. ▸r/rgl-values"""
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
            colour.append(round(max(0.0, sum(chunk) / len(chunk)), 5))    # clamped at zero ▸r/rgl-values

        ndf, ndf_shape = bsdf_reader.values(data, fields["ndf"])    # GGX alpha from the NDF ▸r/rgl-values
        columns = ndf_shape[-1]
        alphas = []
        for start in range(0, len(ndf), columns):    # a profile per direction; isotropic repeats one
            profile = ndf[start:start + columns]
            half = max(profile) / 2.0 if profile else 0.0
            index = next(
                (i for i, v in enumerate(profile) if v <= half), columns - 1
            )
            theta = (index / max(columns - 1, 1)) ** 2 * (math.pi / 2)    # the file's grid is u squared
            alphas.append(min(1.0, math.tan(theta) / 0.6436) if theta < math.pi / 2 else 1.0)
        alpha = math.sqrt(max(alphas) * min(alphas))    # an anisotropic lobe as the one of equal peak
        theta_half = math.atan(alpha * 0.6436)
        roughness = round(max(0.001, min(1.0, math.sqrt(alpha))), 5)    # Standard Surface squares it

        mirror = [max(0.0, sum(rgb[c * plane + row * width] for row in range(height)) / height)
                  for c in range(channels)]    # each channel down column s.x = 0, the mirror
        tint = [round(m / max(max(mirror), 1e-9), 5) for m in mirror]
        painted = uid.startswith("satin_") and min(tint) < 0.8    # a pearl film's colour, there only
        metal = cls.infer_metal(uid, description, colour)
        values = {
            "color": [round(0.75 * t, 5) for t in tint] if painted else colour,
            "roughness": roughness,
            "metalness": 1.0 if metal else 0.0,
        }
        if painted:
            values["specularColor"] = tint
            base = ("Base colour %s = 0.75 x the colour it reflects at the mirror direction, "
                    "which is also its specular colour; its mean reflectance at normal "
                    "incidence is %s" % (values["color"], colour))
        else:
            base = "Base colour = mean reflectance per channel at normal incidence %s" % colour
        note = (
            "%s\n\nMeasured by EPFL RGL (CC0). %s; specular "
            "roughness %.4f = the square root of GGX alpha %.4f, from the "
            "measured NDF half-width (%.1f degrees). Metalness %s was "
            "inferred from the material's name and description - the "
            "measurement itself does not state it."
            % (description, base, roughness, alpha, math.degrees(theta_half),
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
    """A seekable, read-only, block-cached file over `get_range(start, end) -> bytes`."""

    def __init__(self, size: int, get_range, notify=None):
        self.size = int(size)
        self._get = get_range
        self._blocks = {}
        self._pos = 0
        self.notify = notify    # notify(blocks_held, blocks_total) after every fetched block

    @property
    def notify(self):
        """The per-block progress callback; it runs only on the thread that installed it."""
        return self._notify

    @notify.setter
    def notify(self, callback) -> None:
        self._notify = callback
        self._notify_thread = threading.get_ident()    # preview workers read this same cached file

    def copy(self, notify=None) -> "RangedFile":
        """Its own reader over the same bytes: the blocks fetched so far, its own position and progress."""
        twin = RangedFile(self.size, self._get, notify=notify)
        twin._blocks = dict(self._blocks)
        return twin

    def seed_tail(self, tail: bytes) -> None:
        """Hold the bytes already read off the end - every block, when the tail is the file."""
        if len(tail) == self.size:
            for n in range(0, self.size, RANGED_BLOCK):
                self._blocks[n // RANGED_BLOCK] = tail[n:n + RANGED_BLOCK]
            return
        last = (self.size - 1) // RANGED_BLOCK
        self._blocks[last] = tail[-(self.size - last * RANGED_BLOCK):]

    def prefetch(self, start: int, end: int, on_bytes=None) -> None:
        """The blocks under start..end in ONE request; on_bytes streams it so a UI can pump."""
        first, last = start // RANGED_BLOCK, min(end, self.size - 1) // RANGED_BLOCK
        missing = [i for i in range(first, last + 1) if i not in self._blocks]
        if not missing:
            return
        lo = missing[0] * RANGED_BLOCK
        hi = min(self.size, (missing[-1] + 1) * RANGED_BLOCK) - 1
        data = self._get(lo, hi) if on_bytes is None else self._get(lo, hi, on_bytes)
        for n in range(0, len(data), RANGED_BLOCK):
            self._blocks[(lo + n) // RANGED_BLOCK] = data[n:n + RANGED_BLOCK]

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
            notify = self._notify
            if notify is not None and (
                    threading.get_ident() == self._notify_thread):
                notify(len(self._blocks), self._total_blocks())
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


END_OF_ARCHIVE = b"PK\x05\x06"


def remote_size(url: str) -> int:
    """A ranged object's whole size, off the Content-Range of its first byte."""
    with _request(url, {"Range": "bytes=0-0"}) as resp:
        found = re.search(r"/(\d+)\s*$", str(resp.headers.get("Content-Range") or ""))
    if not found:
        raise ValueError("no size in the answer for " + url)
    return int(found.group(1))


def open_remote_zip(parts):
    """(ZipFile, RangedFile) over an archive published in parts [(url, size)]. ▸r/simready-release"""
    starts, total = [], 0
    for _url, size in parts:
        starts.append(total)
        total += int(size)
    get_range = spanned_reader(parts)
    tail = get_range(max(0, total - RANGED_BLOCK), total - 1)    # explicit: a suffix range 501s
    remote = RangedFile(total, get_range)
    remote.seed_tail(tail)
    at = tail.rfind(END_OF_ARCHIVE)
    if at < 0 or len(tail) - at < 22:
        raise zipfile.BadZipFile("no end-of-archive record in the last block")
    disk, cd_disk, _here, _all, _size, cd_offset = struct.unpack(
        "<HHHHII", tail[at + 4:at + 20])
    last = len(parts) - 1
    if 0xFFFF in (disk, cd_disk) or cd_offset == 0xFFFFFFFF:
        if last:
            raise zipfile.BadZipFile("a split ZIP64 archive")
    elif (disk, cd_disk) != (last, last):
        raise zipfile.BadZipFile("its directory is not in its last part")
    else:
        remote.prefetch(starts[last] + cd_offset, total - 1)    # the whole directory, one request
    bundle = zipfile.ZipFile(remote)
    for info in bundle.infolist():    # zipfile counts every entry from the last part
        info.header_offset += starts[info.volume] - starts[last]
    if last:
        end = starts[last] + cd_offset
        for info in sorted(bundle.infolist(), key=lambda i: i.header_offset, reverse=True):
            if hasattr(info, "_end_offset"):    # zipfile's overlap guard, re-aimed ▸r/simready-release
                info._end_offset = end
            end = info.header_offset
    return bundle, remote


def member_share(before: int, size: int, read: int, span: int) -> float:
    """Member bytes done once `read` of a `span` fetching a `size` member is in - never past it."""
    return before + size * min(1.0, read / span) if span else before


def read_member(bundle, remote, name: str, on_bytes=None) -> bytes:
    """One member, its header and data fetched in one streamed request; zipfile checks its CRC."""
    info = bundle.getinfo(name)
    start = info.header_offset
    remote.prefetch(start, start + 30 + len(info.filename.encode()) + 1024
                    + info.compress_size, on_bytes)    # 1024: room for the local extra field
    return bundle.read(info)


class AmazeSource(MatxSource):
    """The Amaze store: every entry of every `.amazepkg` one tile, its folder the category."""

    name = "Amaze"
    licence = ""
    kind = "amazepkg"
    TREE_URL = ("https://api.github.com/repos/Timour/AmazePackages/"
                "git/trees/main?recursive=1")
    RAW_BASE = "https://raw.githubusercontent.com/Timour/AmazePackages/main/"

    def __init__(self):
        self._lock = threading.Lock()    # the reader caches are shared with worker threads
        self.refresh()    # declares every cache; add new ones there

    PACKAGES_ROOT = "packages"    # categories live UNDER this folder, so the repo root stays free for infrastructure

    @classmethod
    def _tree_rows(cls, nodes) -> list:
        """(category, filename, url, size) for each `packages/<category>/<file>.amazepkg` blob."""
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
        return [(folder, name, url) for folder, name, url, _s in rows]    # an override may skip _sizes

    def _open_package(self, url: str):
        """A zipfile over ranged reads of the hosted package, cached until Refresh - one per url."""
        with self._lock:
            bundles, remotes = self._bundles, self._remotes
            bundle = bundles.get(url)
        if bundle is None:    # the network runs outside the lock; the first to finish is kept
            checked = _checked_url(url)
            known = getattr(self, "_sizes", {}).get(url)
            if known and known <= RANGED_BLOCK:    # known small: one plain fetch
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
                    with _request(checked) as response:    # 416: the whole package is its tail ▸r/github-ranged-store
                        tail = response.read()
                    size = len(tail)

            remote = RangedFile(size, ranged_reader(checked))
            remote.seed_tail(tail)
            bundle = zipfile.ZipFile(remote)
            with self._lock:
                if url not in bundles:
                    bundles[url], remotes[url] = bundle, remote
                bundle = bundles[url]
        return bundle

    def import_reader(self, url: str, notify=None):
        """A reader of the caller's own over one package, so no worker's block download can hold it."""
        shared = self._open_package(url)
        with self._lock:
            remote = (self._remotes.get(url)
                      if self._bundles.get(url) is shared else None)
        if remote is None:
            return shared    # nothing ranged behind it to copy
        return zipfile.ZipFile(remote.copy(notify=notify))

    def _manifest(self, url: str) -> dict:
        if url not in self._manifests:
            from amaze.core import packages
            self._manifests[url] = packages.manifest_from(    # refuses a newer format, as a local read does
                self._open_package(url), url)
        return self._manifests[url]

    def refresh(self):
        with self._lock:    # one swap, so no opener pairs a new cache with an old one
            self._paths = None
            self._manifests = {}
            self._bundles = {}
            self._remotes = {}    # url -> the RangedFile under each bundle, which import_reader copies
        self._sizes = {}    # url -> byte size off the tree listing

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


class SimReadySource(MatxSource):
    """NVIDIA's SimReady materials: a release zip per category, each .usda a tile. ▸r/simready-release"""

    name = "SimReady"
    licence = "MIT-0 (MIT No Attribution)"    # quoted from the release's own LICENSE.md
    RELEASE = ("https://api.github.com/repos/NVIDIA-Omniverse/"
               "PhysicalAI-SimReady-Materials/releases/latest")
    HOME = "https://github.com/NVIDIA-Omniverse/PhysicalAI-SimReady-Materials"
    PREVIEWS = ("https://github.com/Timour/AmazePackages/releases/download/"
                "simready-previews/simready-previews.zip")    # Amaze's renders ▸r/simready-release
    BASE_CLASS = "open_pbr_uber_base_class.usda"
    MATERIAL = re.compile(r"Materials/([^/]+)/([^/]+)\.usda")
    PART = re.compile(r"(.+)\.(zip|z\d\d)")

    def __init__(self):
        self.refresh()

    def refresh(self):
        self._names = {}    # archive parts ((url, size), ...) -> [(folder, name)], kept on success
        super().refresh()

    def remember(self, records) -> None:
        """An archive whose parts are unchanged lists what it listed last time. ▸r/simready-release"""
        names = {}
        for record in records:
            payload = record.payload if isinstance(record.payload, dict) else {}
            parts = tuple(tuple(part) for part in payload.get("parts") or ())
            folder, _, name = str(record.uid).partition("/")
            if parts and name:
                names.setdefault(parts, []).append((folder, name))
        self._names.update(names)

    def page_url(self, record) -> str:
        return self.HOME    # no per-material page

    def resolutions(self, record):
        return ["original"]    # one texture set per material

    @classmethod
    def _archives(cls, release) -> dict:
        """category -> its parts [(url, size)]: `.z01`... first, the `.zip` last."""
        found = {}
        for asset in release.get("assets") or ():
            part = cls.PART.fullmatch(str(asset.get("name") or ""))
            if part:
                found.setdefault(part.group(1), []).append(
                    (part.group(2) == "zip", part.group(2),
                     str(asset.get("browser_download_url") or ""),
                     int(asset.get("size") or 0)))
        return {category: [(url, size) for _last, _n, url, size in sorted(parts)]
                for category, parts in found.items()}

    def _release_materials(self) -> list:
        """(category, name, parts) for every material of the latest release."""
        rows, failed = [], []
        for category, parts in sorted(self._archives(get_json(self.RELEASE)).items()):
            key = tuple(parts)    # url AND size: a re-uploaded part keeps its url
            names = self._names.get(key)
            if names is None:
                try:
                    bundle, _remote = open_remote_zip(parts)
                except Exception as exc:                      # noqa: BLE001
                    debug.event("online", "SimReady archive unreadable",
                                category=category, error=str(exc))
                    failed.append(category)
                    continue
                names = [m.groups() for m in map(self.MATERIAL.fullmatch,
                                                 bundle.namelist()) if m]
                self._names[key] = names
            rows.extend((folder, name, parts) for folder, name in names)
        if failed:    # a short list must not replace a whole one in the catalogue cache
            raise RuntimeError("could not read the SimReady %s archive%s"
                               % (", ".join(failed), "" if len(failed) == 1 else "s"))
        return rows

    def list_materials(self, search="", offset=0, limit=60):
        out = []
        for folder, name, parts in self._release_materials():
            title = name.replace("_", " ")
            if search and search.lower() not in title.lower():
                continue
            out.append(MatxRecord(
                source=self.name, uid="%s/%s" % (folder, name), title=title,
                author="NVIDIA", category=self._cat(folder), licence=self.licence,
                kind="package",
                payload={"parts": [list(part) for part in parts],
                         "member": "Materials/%s/%s.usda" % (folder, name)}))
        return self.with_previews(out)[offset:offset + limit]

    @staticmethod
    def _extract(bundle, remote, name: str, dest_dir: str, on_bytes=None) -> str:
        target = hostos.contained_join(dest_dir, *name.split("/"))    # member names come from the network, `/`-separated whatever the OS
        try:
            data = read_member(bundle, remote, name, on_bytes)
        except KeyError:
            raise RuntimeError("%s is not in the SimReady archive" % name) from None
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
        return target

    def fetch(self, record, resolution, dest_dir, progress=None):
        from amaze.core import matx_usd
        parts = [tuple(part) for part in record.payload.get("parts") or ()]
        member = str(record.payload.get("member") or "")
        if not parts or not self.MATERIAL.fullmatch(member):
            raise RuntimeError("no archive is known for " + record.title)
        bundle, remote = open_remote_zip(parts)
        usda = self._extract(bundle, remote, member, dest_dir)
        self._extract(bundle, remote, self.BASE_CLASS, dest_dir)    # its relative path stays NVIDIA's
        spec = matx_usd.material_spec(usda)
        folder, held = posixpath.dirname(member), set(bundle.namelist())
        textures, unsafe = [], []
        for ref in matx_usd.texture_files(spec):
            name = posixpath.normpath(posixpath.join(folder, ref.replace("\\", "/")))
            try:
                hostos.contained_join(dest_dir, name)
            except hostos.PathEscape:
                unsafe.append(ref)
                continue
            if name in held:    # a texture missing from the archive is skipped here
                textures.append(name)
        report_unsafe("texture", unsafe)
        total = sum(bundle.getinfo(name).compress_size for name in textures) or 1
        done = 0
        for name in textures:
            size = bundle.getinfo(name).compress_size

            def on_bytes(read, span, before=done, size=size):
                if progress:
                    progress(min(1.0, member_share(before, size, read, span) / total))
            self._extract(bundle, remote, name, dest_dir, on_bytes)
            done += size
        if spec["unread"]:
            debug.event("online", "SimReady inputs not translated",
                        material=record.title, inputs=spec["unread"])
            debug.note(
                "left %d input%s of %s at the default value: %s. The material "
                "was built, but may not look exactly like the original."
                % (len(spec["unread"]), "" if len(spec["unread"]) == 1 else "s",
                   record.title, "; ".join(spec["unread"])))
        if not record.tags:
            record.tags = spec["labels"]    # the material's own labels land on the library asset
        mtlx = matx_usd.write_mtlx(spec, os.path.splitext(usda)[0] + ".mtlx")
        if progress:
            progress(1.0)
        return {"mtlx": mtlx}


SOURCES = (AmazeSource, GPUOpenSource, PolyHavenSource,    # menu order, Amaze first
           SimReadySource, PhysicallyBasedSource, RGLSource)


def all_sources():
    return [cls() for cls in SOURCES]
