"""Checking the store for newer add-ons and installing them; the Add-On tab calls both."""

from amaze import messages
from amaze.core import addons, packages, updater
from amaze.helpers import hostver


def check(betas: bool) -> tuple:
    """What the store has newer than what is installed, as (name, version, url), and the sentence."""
    try:
        store = addons.store_versions(betas)
    except (OSError, ValueError) as exc:
        return [], messages.ADDONS_STORE_UNREACHABLE % exc
    root = updater.install_root()
    have = {m["name"]: m["version"] for _f, m in (addons.installed_all(root) if root else [])}
    found = [(name, version, url) for name, (version, url) in sorted(store.items())
             if addons.wanted(have.get(name), version)]
    return found, (messages.ADDONS_AVAILABLE % ", ".join("%s %s" % f[:2] for f in found)
                   if found else messages.ADDONS_UP_TO_DATE)


def install(found, root: str) -> str:
    """Install what `check` found into the Amaze at `root`; the sentence saying what happened."""
    done = []
    running = hostver.houdini_version()
    try:
        for name, version, url in found:
            addons.fetch_and_install(url, root, running)
            done.append("%s %s" % (name, version))
    except (packages.PackageError, OSError) as exc:
        return str(exc)
    return messages.ADDONS_INSTALLED % ", ".join(done)
