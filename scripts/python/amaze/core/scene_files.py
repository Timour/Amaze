"""Houdini scene files by name: which extensions make a file a scene. ▸archive/scene_files.py"""

from amaze.helpers import hostos

HIP_EXTENSIONS = (".hiplc", ".hipnc", ".hip")  # one file type: never split across sections or filters


def matched_extension(name: str) -> str:
    """The HIP_EXTENSIONS entry the filename ends with, or ''."""
    return hostos.matched_extension(name, HIP_EXTENSIONS)
