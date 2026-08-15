"""Online MaterialX material sources - one adapter per library.

Every source is reached with plain stdlib HTTP + JSON, so Amaze keeps
ZERO third-party dependencies and this module is testable outside
Houdini (it imports no `hou`).

Two KINDS of source, which the importer treats differently:

* **package** - ships a .mtlx document plus texture maps. Downloaded into
  <library>/matX/<name>/ and turned into a real material by TRANSLATING
  the .mtlx into clean VOP nodes (core/matx_translate, on Houdini's
  MaterialX Python API).
* **values**  - ships measured shader parameters only (no textures, no
  download). Becomes a "tier A preset" material: create an
  mtlxstandard_surface, set the values, done.

Each source's categories are its own, capitalised and unsuffixed - the
source is chosen from View > Online Materials > <source>, so the category
alone identifies the group within it (see _cat()).

Verified live 2026-07-20 against each API.
"""

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

import hou

import amaze
from amaze.core import debug
from amaze.helpers import hostos

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
    """Selection rule: exact match, else the NEXT HIGHEST available, else
    the highest available below. A preference is a floor you'd like, never
    a hard failure. Returns None only if nothing is available at all."""
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


#: Built once - assembling an SSL context parses the whole CA bundle.
_SSL_CONTEXT = None


def _ssl_context():
    """A context that actually VERIFIES under Houdini.

    Houdini's bundled Python has no system CA chain at all - measured on
    22.0.390: ssl.create_default_context().get_ca_certs() is empty and
    get_default_verify_paths().cafile is None, so EVERY https request
    fails verification with "unable to get local issuer certificate".

    That is why this module used to retry with CERT_NONE. The trouble is
    what triggered the retry: ssl.SSLCertVerificationError is a SUBCLASS
    of ssl.SSLError, so certificate-verification failure - the precise
    signal of an interception - was exactly what turned verification
    off. And since the default context fails here ALWAYS, that was not a
    rare fallback: it was the normal path for every catalogue fetch,
    every preview and every download, silently.

    Houdini ships certifi (verified: site-packages/certifi/cacert.pem),
    and a context built on it verifies these hosts correctly - measured
    200 OK against api.polyhaven.com. So point at that instead and keep
    verification ON. What rides these connections is zip archives
    extracted into the user's library and .mtlx documents translated
    into shader graphs; they are worth verifying."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        try:
            import certifi

            _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
        except Exception as exc:
            # No certifi: fall back to the system store. On a host that
            # HAS one this verifies fine; on one that doesn't, requests
            # now fail loudly instead of succeeding unverified.
            debug.note("no certifi - using the system CA store", error=str(exc))
            _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


#: The only schemes a catalogue may send us to. Every URL below comes
#: out of a remote JSON document - PolyHaven's `thumbnail_url` and
#: `include[].url`, GPUOpen's `file_url`, the updater's
#: `browser_download_url` - and urlopen's DEFAULT opener installs a
#: FileHandler, so `file:///Users/<you>/.ssh/id_rsa` was a fetch this
#: code would perform and copy into the preview cache. The redirect
#: handler is the other half: it follows http, https and ftp whatever
#: the original scheme was, and the GPUOpen preview endpoint is a
#: documented 302, so redirects are the normal path here rather than
#: an edge case.
ALLOWED_SCHEMES = ("https",)


def _checked_url(url: str) -> str:
    """`url` when it is one we may fetch, else "" - the answer given
    once, so the first request and every redirect are held to it."""
    scheme = urllib.parse.urlparse(str(url or "")).scheme.lower()
    if scheme in ALLOWED_SCHEMES:
        return str(url)
    debug.event("online", "refused a URL the catalogue supplied",
                scheme=scheme or "(none)", url=str(url)[:120])
    return ""


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect may not downgrade the scheme. Verification is only
    worth what the last hop kept."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _checked_url(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _request(url: str):
    if not _checked_url(url):
        raise urllib.error.URLError(
            "refused a URL that is not https")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # An opener rather than urlopen, for the redirect handler alone
        # - the verified context is the same one either way. The scheme
        # check above and inside that handler is what keeps a hop off
        # `file://` and off plain http, so the default FileHandler is
        # unreachable rather than removed.
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_ssl_context()),
            _HttpsOnlyRedirects())
        return opener.open(req, timeout=TIMEOUT)
    except urllib.error.URLError as exc:
        # NO UNVERIFIED RETRY. There used to be one here, and it was
        # keyed on ssl.SSLError - which research.md #289 names exactly:
        #
        #   "ssl.SSLCertVerificationError is a SUBCLASS of ssl.SSLError.
        #    So `except ssl.SSLError: <relax verification>` is triggered
        #    by certificate-verification failure - precisely the signal
        #    of an interception. Never key a downgrade off the parent
        #    class."
        #
        # A MITM, a corporate TLS proxy or a captive portal is what
        # trips this branch, and the old answer was to re-fetch the same
        # URL with verification off. What rides that channel is not
        # cosmetic: GPUOpen zips extracted into the library, PolyHaven
        # .mtlx documents translated into shader graphs, RGL .bsdf
        # measurements. certifi (above) is what makes verification work
        # on a host with no usable system store; if it still fails, the
        # honest answer is that the channel is not trustworthy.
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
    """A URL as decoded text - for sources whose catalogue is served as
    HTML rather than an API."""
    with _request(url) as response:
        return response.read().decode("utf-8", "replace")


def get_json(url: str):
    with _request(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def repair_mtlx_references(mtlx_path: str, dest_dir: str) -> list:
    """Make a downloaded .mtlx point at the files that were actually
    fetched, and report what had to be changed.

    PolyHaven's API is internally inconsistent: the include manifest for
    aerial_mud_1 lists `textures/aerial_mud_1_rough_2k.jpg`, while the
    .mtlx document it ships references `..._rough_2k.exr`. We download
    exactly what the manifest says, so the material ends up pointing at a
    file that was never fetched - and a missing texture reads as BLACK
    with no error Houdini would surface.

    Same map, same resolution, different container, so the fix is to
    repoint the reference at the file we have rather than guess a second
    download URL."""
    repairs = []
    try:
        with open(mtlx_path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return repairs

    # Every file-ish value in the document.
    # The extension must START with a letter: a bare numeric value like
    # value="0.01" (a displacement scale) otherwise reads as a file
    # called "0" with extension "01", and gets reported as a missing
    # texture.
    referenced = set(
        re.findall(r'value="([^"]+\.[A-Za-z][A-Za-z0-9]{1,3})"', text)
    )
    if not referenced:
        return repairs

    # What we actually have, indexed by stem.
    on_disk = {}
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
            # `repairs` already lists every entry as fixed_to: <path>,
            # and matx_import logs "mtlx references repaired" on that
            # basis - so swallowing the write failure produced a
            # material whose textures all render BLACK while the log
            # said the repair succeeded. A read-only library or a full
            # disk is enough. Report it as unrepaired, which is what it
            # is, and say why.
            debug.event("online", "mtlx repair could not be written",
                        path=mtlx_path, error=str(exc))
            # The CAUSE only. Every entry is marked unrepaired just
            # below, so matx_import's caller reports the consequence -
            # with the count and the material's name, which this line
            # does not have. Both are notes, so saying "render black"
            # here printed the same bad news to the user twice for one
            # import.
            debug.note(
                "the texture paths inside the downloaded material "
                "could not be updated (%s)." % exc, path=mtlx_path)
            for entry in repairs:
                entry["fixed_to"] = None
                entry["error"] = str(exc)
    return repairs


def download(url: str, dest_path: str, on_bytes=None) -> str:
    """Stream a URL to disk. Returns dest_path.

    on_bytes(read, total) is called per 64KB chunk when given, so a caller
    on the main thread can drive a progress bar (total is 0 if the server
    sent no Content-Length)."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    # Promote on success: an interrupted transfer must not leave a
    # truncated file at the final path, which cache layers read as a
    # finished download forever. scratch_beside gives the unique name
    # (a fixed `.part` was one shared buffer between concurrent
    # fetches), the fsync, and the Windows retry.
    with hostos.scratch_beside(dest_path) as tmp_path:
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
        # The scratch dance is NOT enough on its own, which is the trap
        # this check exists for: CPython's HTTPResponse.readinto
        # deliberately does not raise on a short body - it closes the
        # connection and returns 0 - so a transfer cut off half way
        # exits the loop NORMALLY and the promote lands the fragment
        # as a finished download. Measured against a server advertising
        # 100000 bytes and sending 1000: the loop returned cleanly and
        # the 1000-byte file was promoted.
        #
        # Nothing downstream catches it. A truncated .bsdf still passes
        # RGL's 12-byte "tensor_file" magic check, lands in the cache,
        # and is never re-fetched - that material is dead for good. A
        # truncated PolyHaven texture lands in the library and renders
        # wrong with no diagnostic. All four hosts send Content-Length,
        # so one check here covers every source and every preview.
        if total and read != total:
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
        # Sources disagree on the shape of "author": GPUOpen sends a
        # LIST, PolyHaven a dict of names, PhysicallyBased a citation
        # string. Normalise once here so nothing downstream has to care
        # (a list reaching the tooltip raised TypeError on every repaint
        # of the online grid).
        self.author = _as_text(author)
        self.category = category      # capitalised, unsuffixed (see _cat)
        self.tags = tags or []
        self.preview_url = preview_url
        self.licence = licence
        self.kind = kind              # "package" | "values"
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
        """A link back to where this material came from, for crediting the
        creators. Subclasses return the exact material page where the URL
        scheme is known, else the library's home page."""
        return ""

    def list_materials(self, search="", offset=0, limit=60) -> list:
        raise NotImplementedError

    def resolutions(self, record) -> list:
        return []

    def fetch(self, record, resolution, dest_dir, progress=None) -> dict:
        """Package sources: download+extract, return {"mtlx": path}.
        Value sources: return {"values": {...}}.

        progress(frac) is called with a 0..1 fraction for THIS material's
        whole download when given, so the caller can show a progress bar."""
        raise NotImplementedError

    def _cat(self, name):
        """Normalise a source's category to a clean, Capitalised name.
        Sources disagree on the type: a string (GPUOpen, after UUID
        lookup), a list (PolyHaven, PhysicallyBased), or absent - and on
        case (PolyHaven's are lowercase). No "-<Source>" suffix any more:
        the source is picked from the View > Online Materials submenu, so
        it's redundant on every category."""
        if isinstance(name, (list, tuple)):
            name = name[0] if name else None
        name = (str(name).strip() if name else "") or "Uncategorized"
        return " ".join(w[:1].upper() + w[1:] for w in name.split())
    def refresh(self):
        """Drop whatever this source cached, so the next listing is
        rebuilt. Sources that ship a table also mark themselves as
        wanting the LIVE catalogue for that one rebuild - Refresh is
        the user asking us to go and look."""
        return None

    def needs_download(self, record) -> bool:
        """True when importing this record will fetch bytes. Package
        sources always do; a values source only when its shipped table
        does not already know the material."""
        return getattr(record, "kind", "") != "values"



class GPUOpenSource(MatxSource):
    """AMD GPUOpen MaterialX Library - 454 materials, MIT Public Domain.
    Ships true MaterialX packages (.mtlx + textures) in resolution
    variants labelled like "1k 8b"."""

    name = "GPUOpen"
    licence = "MIT Public Domain"
    #: AMD's host. "matlib" here is THEIR name, not ours - a blind
    #: matlib->amaze rename on 2026-07-27 rewrote it to a hostname that
    #: does not resolve, and every GPUOpen import failed with "no
    #: downloadable package" because the catalogue fetch died silently.
    #: Third-party URLs are not ours to rename.
    API = "https://api.matlib.gpuopen.com/api"

    def page_url(self, record) -> str:
        # The GPUOpen material-library site (no confirmed per-material
        # permalink scheme, so link the library home).
        return "https://matlib.gpuopen.com/"

    def __init__(self):
        self._categories = None

    def _category_map(self):
        if self._categories is not None:
            return self._categories
        # Built LOCALLY and only published on success. Assigning
        # self._categories = {} before the try cached the FAILURE for
        # the whole session: one unreachable /categories/ with a healthy
        # /materials/ put all 454 materials in "Uncategorized" - the
        # sidebar collapses to one entry and looks exactly like AMD
        # publishing no categories. Nothing retried it, because {} is
        # no longer None, and this source does not override refresh().
        cats = {}
        try:
            data = get_json(self.API + "/categories/?limit=100")
            for c in data.get("results", []):
                cats[c.get("id")] = c.get("title")
        except Exception as exc:                            # noqa: BLE001
            debug.event("online", "category lookup failed",
                        source=self.name, url=self.API, error=str(exc))
            # "Uncategorized", US, matching every other place the word
            # reaches the screen (library.py's Clean Up summary, the
            # Colors sidebar) - and matching the label this sentence
            # QUOTES, which _cat above now writes the same way. The
            # online sidebar was the one UK spelling in the product.
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
                        # Verified endpoint - "/thumbnail/" 404s; the
                        # render record's own thumbnail_url is
                        # "/renders/<id>/download_thumbnail/" (302 ->
                        # the image, which urllib follows).
                        "%s/renders/%s/download_thumbnail/"
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
                # Say WHY. Swallowing this made an unreachable host and
                # a material that genuinely has no package produce the
                # identical message ("no downloadable package"), which
                # is how a corrupted API hostname went unnoticed: the
                # catalogue still browsed from the shipped table.
                failures.append(str(exc))
                continue
            label = p.get("label") or ""
            if _res_rank(label) > 0:
                found.append((label.split()[0], pid, p.get("file_url")))
        if not found and failures:
            debug.event("online", "package lookup failed",
                        source=self.name, title=record.title,
                        errors=failures[:3])
            # One sentence shape for both unreachable-host notes in this
            # file (the PolyHaven one below is the same). The site's NAME
            # rather than its API URL, and the HTTP text in the data:
            # what the user needs is why the download sizes came up empty
            # and whether trying again is worth it.
            debug.note(
                "could not reach %s, so no download sizes are listed "
                "for %s. Try again in a moment."
                % (self.name, record.title), errors=failures[:3])
        return found

    def _resolved_packages(self, record):
        """This record's packages, looked up once - ON SUCCESS ONLY.

        Both callers had their own copy of this and both cached on
        key-PRESENCE, so a failed lookup stuck: _packages swallows
        every per-package error and returns [], an empty list is a
        present key, and every later import of that material then
        reported '"X" has no downloadable package' instantly, with no
        request made and nothing short of a full Refresh to clear it -
        while the message blamed the material rather than the network.

        _category_map eighty lines above documents this exact trap and
        fixes it for itself: "Built LOCALLY and only published on
        success. Assigning self._categories = {} before the try cached
        the FAILURE for the whole session ... Nothing retried it,
        because {} is no longer None." Same rule here now, and in one
        place rather than two.
        """
        cached = record.payload.get("_resolved")
        if cached:
            return cached
        # NOT setdefault: its default argument evaluates eagerly,
        # which ran the resolution on every call - no cache at all.
        found = self._packages(record)
        if found:
            record.payload["_resolved"] = found
        return found

    def resolutions(self, record):
        # Each resolution exists twice (8-bit and 16-bit variants), so
        # dedupe - the UI offers resolutions, not bit depths.
        pkgs = self._resolved_packages(record)
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

        download(chosen, zip_path, on_bytes=on_bytes)
        # IN A FINALLY. The archive was removed on the success path
        # only, so a BadZipFile - which is what a captive portal's HTML
        # body with a correct Content-Length produces, past the
        # truncation guard - left _package.zip in the package folder.
        # matx_import._producer_for then reads a non-empty destination
        # as "already downloaded", finds no .mtlx in it, and refuses
        # every later import of that material with "already on disk but
        # holds no .mtlx" - including long after the network is fine.
        try:
            with zipfile.ZipFile(zip_path) as zf:
                # Member paths come from the network: extractall()
                # honours "../" and absolute paths, so a malicious or
                # malformed zip writes outside the library. PolyHaven's
                # branch has always checked this; this one did not.
                safe = []
                skipped = []
                for member in zf.namelist():
                    # contained_join, not normpath: it resolves
                    # REALPATHS, so a symlink planted under
                    # matX/<package>/ cannot be used as the hop out -
                    # which a normpath comparison cannot see. Two
                    # hand-rolled copies of this check had already
                    # drifted from each other (one accepted target ==
                    # root, the other did not).
                    try:
                        hostos.contained_join(dest_dir, member)
                    except hostos.PathEscape:
                        skipped.append(member)
                    else:
                        safe.append(member)
                if skipped:
                    # AGGREGATED: one archive can carry many bad paths,
                    # and a dialog per path is a fault of its own. The
                    # names go to the log; the count is what the user
                    # needs.
                    debug.event("online", "skipped archive paths outside "
                                "the library", count=len(skipped),
                                members=skipped[:20])
                    debug.alert(
                        "%d file(s) in this download tried to write "
                        "outside your library folder, so Amaze skipped "
                        "them.\n\n"
                        "Nothing outside your library was touched. The "
                        "rest of the material was downloaded "
                        "normally.\n\n"
                        "This usually means the package is malformed. If "
                        "the material looks wrong, delete it and download "
                        "it again."
                        % len(skipped),
                        key="online-unsafe-archive-paths")
                zf.extractall(dest_dir, members=safe)
        finally:
            hostos.discard_scratch(zip_path)
        if progress:
            progress(1.0)
        return {"mtlx": _find_mtlx(dest_dir)}


class PolyHavenSource(MatxSource):
    """Poly Haven textures - CC0. Serves a real .mtlx per resolution plus
    an explicit manifest of the textures it references, rather than a
    zip, so we fetch the document and each include."""

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
            # Say WHY - the same treatment _packages got, for the same
            # reason. Swallowing this made an unreachable host and a
            # material that genuinely ships no mtlx variant produce the
            # identical message ("has no downloadable package"), which
            # is exactly how a corrupted API hostname went unnoticed for
            # a day: browsing still worked off the shipped table.
            #
            # An empty list must mean only "the API says there are no
            # mtlx variants".
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
            # Explicit, because `next(iter({}.values()))` raises
            # StopIteration whose str() is EMPTY - the caller's
            # `Download failed: %s` then printed nothing after the
            # colon, the two-meanings-of-an-empty-message shape the
            # comments above were written to end.
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
        # The .mtlx doc plus each referenced texture - many small files, so
        # progress folds the current file's bytes into "file i of n".
        files = [(doc["url"], mtlx_path)]
        unsafe = []
        for rel, info in (doc.get("include") or {}).items():
            # The include manifest's relative paths come straight from
            # API JSON - refuse any entry that would escape dest_dir
            # (e.g. a "../" path) rather than writing outside the
            # library.
            # contained_join, like the archive case above - the second
            # hand-rolled copy of this check, and the two had already
            # drifted (that one accepted target == root, this one did
            # not). Realpath-based, so a symlink cannot be the hop out.
            try:
                target = hostos.contained_join(dest_dir, rel)
            except hostos.PathEscape:
                unsafe.append(rel)
                continue
            files.append((info["url"], target))
        if unsafe:
            # Same shape and the same key as the archive case above: to the
            # user it is one situation - "this download wanted to write
            # somewhere it should not" - so it must not interrupt twice.
            debug.event("online", "skipped include paths outside the "
                        "library", count=len(unsafe), paths=unsafe[:20])
            debug.alert(
                "%d file(s) in this download tried to write outside your "
                "library folder, so Amaze skipped them.\n\n"
                "Nothing outside your library was touched. The rest of the "
                "material was downloaded normally.\n\n"
                "This usually means the package is malformed. If the "
                "material looks wrong, delete it and download it again."
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
    """PhysicallyBased - MEASURED reference values, no textures at all.

    A different kind of source: these become "tier A preset" materials -
    an mtlxstandard_surface with physically accurate constants (real
    aluminium, real gold) to build on. Nothing is downloaded; the whole
    dataset is ~69 KB of JSON."""

    name = "PhysicallyBased"
    # CC0 1.0, stated by the project itself ("all data is released
    # under CC0 1.0 ... free to use, modify, and distribute its
    # content without any restrictions, even for commercial
    # purposes"). The vague "see source reference" this replaced was
    # stored verbatim on every imported material.
    licence = "CC0 1.0 - physicallybased.info (Anton Palmqvist)"
    kind = "values"
    API = "https://api.physicallybased.info"

    def page_url(self, record) -> str:
        return "https://physicallybased.info/"

    #: The dataset shipped with Amaze (res/physicallybased_materials.json,
    #: written by tests/harvest_online.py). Browsing reads THIS, so the
    #: grid fills instantly and offline; the live API is the fallback
    #: for an install without the table. A blocking fetch behind a click
    #: has no progress to show and simply stalls the grid.
    TABLE_FILE = "physicallybased_materials.json"

    def __init__(self):
        self._all = None

    def refresh(self):
        # Drop the cache; the next load (on the worker thread) goes to
        # the API. Never fetch HERE - refresh() runs on the UI thread.
        self._all = None

    def _usable(self, payload) -> bool:
        """Is a live response worth preferring over the shipped table?

        "Reachable" is not "correct": a captive portal, a proxy error
        page, or a schema change can all return valid JSON. Accepting
        it blindly replaced 86 measured materials with whatever came
        back - the browser then shows a handful of grey tiles and the
        catalogue is simply gone. So the response has to look like the
        dataset: a list whose entries carry a name and a colour, and
        not dramatically smaller than what ships.
        """
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
        # A real shrink happens (a material can be withdrawn); losing
        # most of the set means the response is not the dataset.
        return len(good) >= max(1, shipped // 2)

    def _table_path(self) -> str:
        return amaze.package_file("res", self.TABLE_FILE)

    def _load(self):
        """The dataset: LIVE when reachable, the shipped table when not.

        Materials added to physicallybased.info just appear, the way
        they do on the site. Only the catalogue WORKER calls this, so
        the request never touches the UI thread, and the shipped table
        keeps browsing (and the Generator) working offline.
        """
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
            # The table is keyed by name; the rest of this class expects
            # the API's list-of-dicts shape, name included.
            self._all = [
                dict(entry, name=name)
                for name, entry in sorted(table.items())
            ]
            debug.event("online", "PhysicallyBased table loaded",
                        materials=len(self._all))
        except (OSError, ValueError) as exc:
            debug.event("online", "PhysicallyBased table unreadable",
                        error=str(exc))
            # THROUGH _usable, not around it. This was the one path that
            # assigned a live response with no shape check at all, and it
            # is only reachable AFTER the API has already raised or been
            # refused in this same call - so a captive portal's login
            # page, a proxy error or a changed schema arrived here as the
            # catalogue. Worse than grey tiles: everything downstream
            # slices _all as a list, so a JSON object became a TypeError
            # several calls away from its cause.
            #
            # The re-fetch is kept, because the case that makes this
            # branch worth having is a TRANSIENT first failure with no
            # table to fall back on. With the table unreadable _usable's
            # size floor degrades to "at least one good entry" (shipped
            # reads as 0) while its shape checks still apply.
            live = get_json(self.API + "/materials")
            if not self._usable(live):
                # Not cached: self._all stays None, so a later refresh
                # tries again rather than serving a refusal for the
                # session. The catalogue worker turns this into "could
                # not reach 1 online source", which is what it is.
                raise ValueError(
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
                    # NOT m["reference"]: that field is the URL of the
                    # project's own Cycles render of the material, so
                    # it was showing up as the author ("by
                    # https://raw.githubusercontent.com/..."), and on
                    # every imported material's credit block. These are
                    # one person's compiled reference values.
                    author="Anton Palmqvist",
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
    """EPFL RGL - MEASURED materials, CC0.

    A values source like PhysicallyBased, except the numbers are not
    published as numbers: each material ships as a measured BSDF
    (a `tensor_file` container), and two shading values come straight
    out of it -

      * base colour = mean reflectance per channel at normal incidence
        (the rgb tensor at incident-angle index 0),
      * specular roughness = the GGX alpha implied by the measured
        NDF's half-width, alpha = tan(theta_half) / 0.6436.

    Metalness is the one inference: the measurement does not say metal
    or dielectric, so it is read from the material's own name and
    description and recorded in the import note. Everything else is
    left at the shader default rather than invented.

    Licensing: "Unless otherwise noted, all material data is licensed
    under the Creative Commons Zero (CC0) license" - no attribution
    required; the source and licence are stored on every import
    anyway."""

    name = "RGL"
    licence = "CC0 1.0 - EPFL Realistic Graphics Lab"
    kind = "values"
    SITE = "https://rgl.epfl.ch/materials"
    CDN = "https://d38rqfq1h7iukm.cloudfront.net/media/materials"

    #: Name/description words that mean "this is a conductor". A
    #: measured BSDF cannot state it, and getting it wrong is very
    #: visible, so the inference is keyword-based and reported.
    METAL_WORDS = (
        "metal", "metallic", "aluminium", "aluminum", "copper", "steel",
        "brass", "bronze", "chrome", "gold", "golden", "silver", "nickel",
        "iron", "titanium", "tin", "zinc", "foil",
    )

    #: Words that OVERRULE a metal match. A vinyl wrapping film is a
    #: dielectric no matter how metallic it looks (and how gold its
    #: colourway is named) - the whole TeckWrap "satin" range was
    #: classified metal, half of it because "tin" is a substring of
    #: "satin". Matching is word-boundary now, and these win outright.
    DIELECTRIC_WORDS = (
        "vinyl", "wrap", "wrapping", "fabric", "felt", "silk", "velvet",
        "wool", "cotton", "leather", "wood", "ceramic",
        # Paint is a dielectric binder with flakes suspended in it -
        # metalness 1 turns a light grey car paint into a grey mirror,
        # and a dark blue one into a near-black mirror. It also removes
        # a substrate trap: "flake paint ON TOP OF ALUMINIUM" matched
        # `aluminium` and came out metal, while its identically-built
        # sibling (no substrate named) came out dielectric.
        "paint", "primer", "lacquer", "varnish",
    )

    #: Reflectance floor for calling something a conductor, set well
    #: below the darkest measured metal (Silicon 0.426) and well above
    #: the dark "metallic" coatings that trip the keyword rule (0.09).
    DARKEST_CONDUCTOR = 0.25

    #: Values harvested once from every published measurement, shipped
    #: with Amaze (res/rgl_materials.json). Browsing shows each
    #: material's real colour immediately, and importing needs no
    #: download at all - the alternative was 62 multi-hundred-KB files
    #: fetched to fill a grid, which is neither fast nor polite.
    TABLE_FILE = "rgl_materials.json"

    def refresh(self):
        self._names = None

    def needs_download(self, record) -> bool:
        # An RGL material the table does not know still costs a
        # multi-hundred-KB BSDF download - that one DOES need the bar.
        return str(getattr(record, "uid", "")) not in self.table()

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
        """Material names: the shipped table UNIONED with the live site.

        New RGL publications simply appear, the way they do when you
        browse the site - nobody wants an "updates available" prompt
        for a catalogue. This costs the UI nothing: list_materials is
        only ever called from the catalogue WORKER thread (see
        core/matx_library._CatalogueWorker), and the browser paints
        from its disk cache first either way.

        A material the live list knows and the table does not still
        browses and imports - its measurement downloads on demand. If
        the site is unreachable the table alone is the answer, so
        offline browsing keeps working.
        """
        if self._names is None:
            names = sorted(self.table().keys())
            try:
                html = get_text(self.SITE)
                live = set(re.findall(
                    r"/media/materials/([a-z0-9_]+)/", html
                ))
                # UNION, not replace: the table's entries carry
                # measured values the scrape does not.
                names = sorted(set(names) | live)
                debug.event("online", "RGL catalogue",
                            table=len(self.table()), live=len(live),
                            new=len(live - set(self.table())),
                            total=len(names))
            except Exception as exc:               # noqa: BLE001
                # Offline, or the site moved: the shipped table is
                # a complete, usable catalogue on its own.
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
                    # Real measured values, so the tile shows the
                    # material's own colour rather than a placeholder
                    # grey. Unknown materials carry {} and fill in when
                    # imported.
                    payload={"values": self._values_for(uid), "uid": uid},
                )
            )
        return out

    def resolutions(self, record):
        return []

    def fetch(self, record, resolution, dest_dir, progress=None):
        """Download the material's measured BSDF and read its numbers.

        The measurement is a means, not an asset: it lands in the
        local cache (values sources are called with no destination
        directory) and is reused on the next import of the same
        material rather than re-downloaded."""
        uid = record.payload.get("uid") or record.uid
        entry = self.table().get(uid)
        if entry:
            # Already measured at harvest time - no download, no wait.
            values = {
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
            # NOT "." - values sources are called with dest_dir=None, so
            # that dropped multi-hundred-KB .bsdf files into whatever
            # directory Houdini happened to start in, and made the
            # os.path.exists reuse check below depend on the CWD.
            folder = dest_dir or tempfile.gettempdir()
        # THE THIRD download target, and it had no check at all: `uid`
        # comes from the remote catalogue, so `../x` wrote outside the
        # cache root. safe_filename is the recorded rule for a remote
        # name becoming a path (matx_import.py:234), and contained_join
        # is the other half.
        target = hostos.contained_join(
            folder, "%s_rgb.bsdf" % hostos.safe_filename(str(uid)))
        if os.path.exists(target) and not self._is_measurement(target):
            # A previously cached error page or truncated download would
            # otherwise poison this material permanently: the file
            # exists, so it is never fetched again.
            debug.event("online", "cached RGL measurement is not a "
                        "tensor_file - refetching", uid=uid, path=target)
            try:
                os.remove(target)
            except OSError:
                pass
        if not os.path.exists(target):
            # A 0..1 FRACTION, which is the contract fetch documents.
            # This reported a STRING, and the bar clamps with `frac <
            # 0.0` - a TypeError the moment a callback actually
            # arrived. It never did: the one caller that could pass a
            # progress callback into this branch was not passing one,
            # so the two bugs hid each other and the bar simply sat at
            # zero through a multi-hundred-KB download.
            on_bytes = None
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
        """Shading values for one material from the shipped table, in
        the shape the shader builder and the tile painter expect."""
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
        """Metal or dielectric, inferred from the material's name, its
        own measurement description, and - when known - what it
        actually reflects. The file itself never states it.

        The MEASUREMENT overrules the words: no bare conductor is dark.
        The darkest metal in the PhysicallyBased reference set reflects
        0.426 in its brightest channel (Silicon; then Titanium 0.441,
        Iron 0.530), so anything measuring below DARKEST_CONDUCTOR is a
        dark coating whose name happens to say "metallic" - ILM's
        m68-speeder reads 0.091, which as a conductor renders as an
        almost black mirror."""
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

    #: Every RGL measurement is a Mitsuba tensor_file; anything else
    #: is an error page or a truncated download.
    BSDF_MAGIC = b"tensor_file\0"

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
        """(values, note) for one measured file - the whole extraction,
        as a classmethod so it can be tested without the network."""
        from amaze.core import bsdf_reader

        data, _version, fields = bsdf_reader.read(path)
        description = ""
        if "description" in fields:
            raw, _shape = bsdf_reader.values(data, fields["description"])
            description = bytes(raw).decode("utf-8", "replace").strip()

        # Base colour: mean reflectance per channel at normal incidence.
        rgb, shape = bsdf_reader.values(data, fields["rgb"])
        _phi, _theta, channels, height, width = shape
        plane = height * width
        colour = []
        for channel in range(channels):
            start = channel * plane
            chunk = rgb[start:start + plane]
            # Clamped at zero: a few measurements carry a slightly
            # NEGATIVE channel (noise around black - green PVC's red
            # reads -0.0356), and a negative base_color is not a colour.
            colour.append(round(max(0.0, sum(chunk) / len(chunk)), 5))

        # Roughness: GGX alpha from the NDF's half-width. D falls to
        # half its peak at tan(theta) = alpha * sqrt(sqrt(2) - 1).
        ndf, ndf_shape = bsdf_reader.values(data, fields["ndf"])
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


#: Sources available to the browser, in menu order.
#: ambientCG is deliberately absent from v1: probing its API showed it
#: serves ONLY JPG/PNG texture zips, no .mtlx document (contrary to some
#: secondary sources claiming MaterialX support). Supporting it means
#: building a standard_surface from conventionally-named maps - a third
#: source KIND - which is a v2 feature, not a blocker.
SOURCES = (GPUOpenSource, PolyHavenSource, PhysicallyBasedSource,
           RGLSource)


def all_sources():
    return [cls() for cls in SOURCES]
