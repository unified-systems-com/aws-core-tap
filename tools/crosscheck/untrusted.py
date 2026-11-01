"""Reading files from, and printing text taken from, a tree we did not write.

A checkout we analyse is untrusted: it may hold a symlink that points at a file elsewhere on the machine, and any text
in it ends up in a report. Two rules, both standard library:

* **Containment.** Every file read goes through :func:`read_bytes` or :func:`files_in`, which refuse a symlink, a
  symlinked directory and any path that resolves outside the root, so a hostile tree cannot make a reader open some
  other file.
* **Safe text.** :func:`md_safe` makes a string safe to place in Markdown or on a terminal: no control characters, no
  line breaks, nothing that starts a heading, link, image, table or raw HTML.
"""

from __future__ import annotations

import re
from pathlib import Path


class UntrustedTreeError(ValueError):
    """The tree holds something a reader must not follow."""


_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f  ]")
_MD = str.maketrans({"`": "'", "<": "‹", ">": "›", "[": "(", "]": ")", "|": "/", "\\": "/", "*": "·", "_": "-", "#": "♯", "!": "ǃ"})


def md_safe(value: object, limit: int = 300) -> str:
    """``value`` as one line of text that cannot start Markdown structure or HTML, and cannot move a terminal."""
    text = _CTRL.sub("?", str(value))
    text = " ".join(text.split())  # line breaks, tabs and runs of spaces become single spaces
    text = text.translate(_MD)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def resolve_root(root: Path) -> Path:
    """The real path of the tree to analyse; the operator chose it, so the root itself may be reached through a link."""
    real = Path(root).resolve()
    if not real.is_dir():
        raise UntrustedTreeError(f"{root} is not a directory")
    return real


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def check_dir(root: Path, directory: Path) -> Path:
    """``directory`` (under ``root``) if it is a real directory inside the tree; otherwise refuse."""
    if directory.is_symlink() or not directory.is_dir() or not _inside(root, directory):
        raise UntrustedTreeError(f"refusing {md_safe(directory.name)}: not a plain directory inside the tree")
    return directory


def files_in(root: Path, directory: Path, pattern: str) -> list[Path]:
    """Sorted plain files matching ``pattern`` directly inside ``directory``; any symlink or escaping path is refused."""
    root = resolve_root(root)
    check_dir(root, directory)
    out = []
    for path in sorted(directory.glob(pattern)):
        if path.is_symlink() or not path.is_file() or not _inside(root, path):
            raise UntrustedTreeError(f"refusing {md_safe(path.name)}: a symlink or a path outside the tree")
        out.append(path)
    return out


def read_bytes(root: Path, path: Path) -> bytes:
    """The bytes of ``path``, only if it is a plain file inside ``root``."""
    root = resolve_root(root)
    if path.is_symlink() or not path.is_file() or not _inside(root, path):
        raise UntrustedTreeError(f"refusing {md_safe(path.name)}: a symlink or a path outside the tree")
    return path.read_bytes()
