"""Is there a newer Amaze, and can this one become it? Asked only when the user asks - nothing here is fetched at launch and nothing polls. ▸p/updater-shape ▸r/tls-http"""

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request

from amaze import branding
from amaze.core import debug

RELEASES_URL = "https://api.github.com/repos/Timour/Amaze/releases/latest"    # unauthenticated, rate-limited per IP; no timeout or user-agent constants belong beside it ▸p/updater-shape

UP_TO_DATE = "up-to-date"    # the verdicts `check` can answer with
NEWER = "newer"
NO_RELEASE = "no-release"
UNREACHABLE = "unreachable"


class Update:
    """One verdict, with everything a caller needs to act or explain."""

    def __init__(self, verdict, version="", url="", sentence="",
                 digest="", size=0):
        self.verdict = verdict
        self.version = version
        self.url = url
        self.sentence = sentence
        self.digest = digest    # `sha256:<hex>` when an UPLOADED asset was chosen; "" for the generated zipball, which GitHub publishes no digest for ▸r/release-digest
        self.size = size        # the asset's declared byte count, 0 when unknown

    def __bool__(self):
        return self.verdict == NEWER


def parts(version: str):
    """A version as comparable integers; unreadable pieces sort last."""
    cleaned = str(version or "").strip().lstrip("vV")
    out = []
    for piece in cleaned.split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    """Strictly newer, comparing on equal length so 1.0 < 1.0.1."""
    left, right = parts(candidate), parts(current)
    width = max(len(left), len(right))
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    return left > right


def _open(url):
    """THE package's single `urlopen`, not a second one - a private door here would be unblocked in the suite. ▸p/updater-shape"""
    from amaze.core import matx_sources
    return matx_sources._request(url)


def check(current: str = "") -> Update:
    """Ask the release feed what the newest published version is."""
    current = current or branding.APP_VERSION
    try:
        with _open(RELEASES_URL) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:    # NOT an error: the repo is public and simply has no tagged release yet
            return Update(NO_RELEASE, sentence=(
                "No release has been published yet, so there is nothing "
                "to update to. You are running %s." % current))
        return Update(UNREACHABLE, sentence=_unreachable_sentence(exc))
    except Exception as exc:                                  # noqa: BLE001
        return Update(UNREACHABLE, sentence=_unreachable_sentence(exc))

    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        return Update(NO_RELEASE, sentence=(
            "The newest release did not say which version it is, so it "
            "cannot be compared with the %s you are running." % current))
    url, digest, size = "", "", 0    # an uploaded zip if there is one - it is the only kind carrying a digest - else the archive GitHub generates ▸r/release-digest
    for asset in payload.get("assets") or []:
        if str(asset.get("name") or "").endswith(".zip"):
            url = str(asset.get("browser_download_url") or "")
            digest = str(asset.get("digest") or "")
            size = int(asset.get("size") or 0)
            break
    url = url or str(payload.get("zipball_url") or "")
    if not is_newer(tag, current):
        return Update(UP_TO_DATE, version=tag, sentence=(
            "You are running %s, which is the newest release." % current))
    return Update(NEWER, version=tag, url=url, digest=digest, size=size,
                  sentence=(
        "Amaze %s is available. You are running %s." % (tag, current)))


def _unreachable_sentence(exc) -> str:
    debug.event("updater", "release feed unreachable", error=str(exc))
    return ("The release list could not be reached, so it is not known "
            "whether a newer Amaze exists. Check the connection and try "
            "again; nothing has been changed.")


MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024    # what a release may weigh on the wire, and below once unpacked - the tracked tree is ~41MB, so both are headroom, not a budget ▸r/release-digest
MAX_UNPACKED_BYTES = 512 * 1024 * 1024


def _verify_digest(path: str, digest: str) -> None:
    """Refuse `path` unless it hashes to `digest` (`sha256:<hex>`) - an absent or unknown algorithm REFUSES rather than passing. ▸r/release-digest"""
    algorithm, _, expected = str(digest or "").partition(":")
    if not expected:
        raise OSError(
            "the release did not say what the download should hash to, so "
            "it cannot be verified. Nothing has been changed.")
    try:
        hasher = hashlib.new(algorithm)
    except (ValueError, TypeError):
        raise OSError(
            "the release names a checksum this Amaze cannot compute (%s). "
            "Nothing has been changed." % algorithm)
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    actual = hasher.hexdigest()
    if actual != expected.strip().lower():
        raise OSError(
            "the download does not match the checksum the release "
            "published, so it is not the file that was released. Nothing "
            "has been changed.")


def download(url: str, into: str, digest: str = "", size: int = 0) -> str:
    """Stream a release to `into`, returning the file written - raises OSError with a finished sentence on any of short, empty, oversized, wrong-sized or wrong-hashed, and promotes nothing unless all pass. ▸r/release-digest ▸p/updater-shape"""
    from amaze.helpers import hostos

    os.makedirs(into, exist_ok=True)
    target = os.path.join(into, "amaze-update.zip")
    ceiling = min(size, MAX_DOWNLOAD_BYTES) if size else MAX_DOWNLOAD_BYTES
    read = 0
    with hostos.scratch_beside(target) as scratch:
        with _open(url) as response:
            declared = response.headers.get("Content-Length")
            with open(scratch, "wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
                    read += len(chunk)
                    if read > ceiling:
                        raise OSError(
                            "the download is larger than a release should "
                            "be (over %d bytes). Nothing has been changed."
                            % ceiling)
        if declared is not None and read != int(declared):
            raise OSError(
                "the download stopped early - %d bytes of %s. Nothing has "
                "been changed." % (read, declared))
        if not read:
            raise OSError(
                "the download was empty. Nothing has been changed.")
        if size and read != size:
            raise OSError(
                "the download is %d bytes but the release said %d, so it "
                "is not the file that was released. Nothing has been "
                "changed." % (read, size))
        if digest:
            _verify_digest(scratch, digest)
    return target


INSTALL_ENTRIES = ("scripts", "python_panels", "toolbar", "OPmenu.xml")    # what the INSTALL holds, so what a staged update must contain - stated again in `tools/sync-install.sh`, and `test_updater` fails when the two drift ▸p/updater-shape


def _archive_root(names) -> str:
    """The single top-level folder a zipball wraps everything in, or "" when the archive is flat - read from the members, since a hand-attached zip may be either. ▸p/updater-shape"""
    tops = {name.split("/", 1)[0] for name in names if name.strip("/")}
    return tops.pop() if len(tops) == 1 else ""


def stage_release(archive: str, into: str) -> str:
    """Extract `archive` and build the directory `apply_update` swaps in, returning the staged path - members are contained and the expanded size is capped before anything is written. ▸p/updater-shape ▸r/release-digest"""
    import zipfile

    from amaze.helpers import hostos

    if os.path.isdir(into):
        shutil.rmtree(into, ignore_errors=True)
    unpacked = into + ".unpacked"
    shutil.rmtree(unpacked, ignore_errors=True)
    os.makedirs(unpacked, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            for name in names:
                hostos.contained_join(unpacked, name)    # refused rather than skipped: a release that cannot be unpacked whole is not one to install half of
            expanded = sum(info.file_size for info in bundle.infolist())
            if expanded > MAX_UNPACKED_BYTES:    # the header's own claim, read BEFORE extracting - a few compressed MB can declare gigabytes ▸r/release-digest
                raise OSError(
                    "the release archive unpacks to more than a release "
                    "should (%d bytes). Nothing has been changed."
                    % expanded)
            bundle.extractall(unpacked)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise OSError(
            "the downloaded file is not a zip archive (%s). Nothing has "
            "been changed." % exc)
    except hostos.PathEscape as exc:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise OSError(
            "the release archive holds a file that would be written "
            "outside the update folder (%s). Nothing has been changed."
            % exc)

    root = os.path.join(unpacked, _archive_root(names))
    missing = [entry for entry in INSTALL_ENTRIES
               if not os.path.exists(os.path.join(root, entry))]
    if missing:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise OSError(
            "the release is missing %s, so it is not an Amaze install. "
            "Nothing has been changed." % ", ".join(missing))

    os.makedirs(into, exist_ok=True)
    for entry in INSTALL_ENTRIES:
        source = os.path.join(root, entry)
        target = os.path.join(into, entry)
        if os.path.isdir(source):
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    shutil.rmtree(unpacked, ignore_errors=True)
    debug.event("updater", "release staged", staged=into,
                entries=len(INSTALL_ENTRIES))
    return into


def fetch_and_stage(url: str, workspace: str,
                    digest: str = "", size: int = 0) -> str:
    """Download a release and stage it, in one call - `digest` and `size` are the feed's, carried on the `Update`, and skipping them leaves the download unverified. ▸r/release-digest"""
    archive = download(url, workspace, digest=digest, size=size)
    try:
        return stage_release(archive, os.path.join(workspace, "staged"))
    finally:    # the archive is a means, not a result - keeping it leaves a repo-sized zip in the cache after every update
        try:
            os.remove(archive)
        except OSError:
            pass


def apply_update(staged: str, install: str) -> str:
    """Put `staged` where `install` is, keeping the old one as `.backup` so a bad release is undone by moving it back - nothing takes effect until Houdini restarts, and the caller says so."""
    if not os.path.isdir(staged):
        raise OSError("the staged update is not there: %s" % staged)
    backup = install.rstrip("/\\") + ".backup"
    if os.path.exists(backup):
        shutil.rmtree(backup)
    os.rename(install, backup)    # same parent as the install, so this one never crosses a volume
    try:
        try:
            os.rename(staged, install)
        except OSError:
            shutil.move(staged, install)    # the cache and the install can be on DIFFERENT volumes, where rename raises EXDEV and only a copy crosses ▸r/cross-volume-move
    except OSError:
        shutil.rmtree(install, ignore_errors=True)    # a half-copied install is not one to leave in place
        os.rename(backup, install)    # PUT IT BACK - the window between the two renames is the only moment this is not whole
        raise
    debug.event("updater", "update applied", install=install, backup=backup)
    return backup
