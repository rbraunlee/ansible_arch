"""Prepare only a selected Stow-managed root .bashrc for GNU Stow.

Runs as the configured user. Stow itself creates the link in the following task.
All paths are supplied explicitly so tests never touch a real home or /etc/skel.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import uuid


def regular(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    return info if stat.S_ISREG(info.st_mode) else False


def identical(left, right):
    # Compare bytes afresh, including after a backup is created. No cached
    # metadata-only equality and no file contents appear in Ansible output.
    with left.open("rb") as a, right.open("rb") as b:
        while True:
            a_chunk, b_chunk = a.read(65536), b.read(65536)
            if a_chunk != b_chunk:
                return False
            if not a_chunk:
                return True


def unchanged(path, previous):
    current = regular(path)
    return bool(current) and all(
        getattr(current, field) == getattr(previous, field)
        for field in ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                      "st_size", "st_mtime_ns", "st_ctime_ns")
    )


def ensure_private_directory(path):
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o777 != 0o700:
        raise ValueError(f"unsafe .bashrc backup directory: {path}")


def safe_copy(original, dest):
    # Exclusive creation prevents overwriting older backups (including symlinks).
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as output, original.open("rb") as source:
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        metadata = original.stat()
        if dest.stat().st_gid != metadata.st_gid:
            # The configured user may assign only their own groups. Refuse to
            # remove the original if its group cannot be preserved.
            os.chown(dest, -1, metadata.st_gid)
        shutil.copystat(original, dest, follow_symlinks=False)
        saved = dest.stat()
        if any(getattr(saved, field) != getattr(metadata, field)
               for field in ("st_uid", "st_gid", "st_mode", "st_mtime_ns")):
            raise ValueError(".bashrc backup metadata verification failed")
        if not identical(original, dest):
            raise ValueError(".bashrc backup verification failed")
    except Exception:
        dest.unlink()
        raise


def selected_source(home, skel, packages):
    if not home.is_absolute() or not skel.is_absolute() or not isinstance(packages, list):
        raise ValueError("absolute home/skel and a list of selected package paths required")
    if not stat.S_ISDIR(home.lstat().st_mode) or home.lstat().st_uid != os.geteuid():
        raise ValueError("home must be a real directory owned by the configured user")
    sources = []
    for name in packages:
        if not isinstance(name, str) or not Path(name).is_absolute():
            raise ValueError("selected package paths must be absolute")
        package = Path(name)
        if not stat.S_ISDIR(package.lstat().st_mode):
            raise ValueError(f"unsafe selected Stow package: {package}")
        source = package / ".bashrc"
        info = regular(source)
        if info is False:
            raise ValueError(f"unsupported .bashrc Stow source: {source}")
        if info:
            # The following Stow task passes this basename as a bare argv item;
            # a leading dash is parsed as an option, not a package to link.
            if package.name.startswith("-"):
                raise ValueError(f"unsupported option-like Stow package: {package}")
            sources.append(source)
    if len(sources) > 1:
        raise ValueError("ambiguous selected .bashrc Stow sources; refusing to change target")
    if not sources:
        return None

    source = sources[0]
    # Stow's local/global ignore files and cwd/home .stowrc options can prevent
    # linking .bashrc. Other selected packages can install a global config before
    # the bash package is processed. We cannot prove effective management in
    # these cases, so refuse even to remove a byte-identical Arch default.
    config_paths = {home / ".stowrc", Path.cwd() / ".stowrc",
                    home / ".stow-global-ignore", home / ".stow-local-ignore"}
    for name in packages:
        package = Path(name)
        for directory in (package, package.parent):
            config_paths.update(directory / filename for filename in
                                (".stow-local-ignore", ".stow-global-ignore", ".stowrc"))
    for config in sorted(config_paths):
        if os.path.lexists(config):
            raise ValueError(f"unsupported Stow ignore/options configuration: {config}")
    return source


def intended_link(target, source):
    return target.is_symlink() and target.resolve() == source.resolve()


def note_text(target, backup, source, status):
    return (f"Original: {target}\nBackup: {backup}\n"
            f"Planned replacement: GNU Stow link to {source}\n"
            f"Status: {status}\n"
            "To restore, first remove the Stow link if present, then copy the backup to the original path.\n")


PENDING = "replacement pending; check the current target to confirm."
VERIFIED = "Stow .bashrc link verified; replacement completed."


def prepare(home, skel, packages):
    source = selected_source(home, skel, packages)
    if source is None:
        return {"changed": False, "reason": "no selected package manages .bashrc"}

    target = home / ".bashrc"
    original = regular(target)
    if original is None:
        return {"changed": False, "reason": "target absent; Stow will link"}
    if original is False:
        if intended_link(target, source):
            return {"changed": False, "reason": "correct link already present"}
        raise ValueError(f"unsupported existing .bashrc (not intended Stow link): {target}")
    if original.st_uid != os.geteuid():
        raise ValueError(f"existing .bashrc is not owned by configured user: {target}")

    default = regular(skel)
    if default and identical(target, skel):
        # Recheck before removal; a changed file must never be discarded as default.
        if not unchanged(target, original) or not identical(target, skel):
            raise ValueError(".bashrc changed during default comparison")
        target.unlink()
        return {"changed": True, "reason": "untouched Arch default removed for Stow"}

    directory = home / ".bashrc-backups"
    ensure_private_directory(directory)
    token = uuid.uuid4().hex
    backup = directory / f"bashrc-{token}"
    note = directory / f"bashrc-{token}.note"
    safe_copy(target, backup)
    # Note deliberately describes intent, not a completed Stow operation: it stays
    # truthful if Stow or any later task fails and is never rewritten on reruns.
    text = note_text(target, backup, source, PENDING)
    with os.fdopen(os.open(note, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    if not unchanged(target, original) or not identical(target, backup):
        raise ValueError(f".bashrc changed while backing up; original retained at {target}")
    target.unlink()
    return {"changed": True, "backup": str(backup), "note": str(note),
            "reason": "custom .bashrc backed up; Stow replacement pending"}


def finalize(home, skel, packages):
    source = selected_source(home, skel, packages)
    if source is None:
        return {"changed": False, "reason": "no selected package manages .bashrc"}
    target = home / ".bashrc"
    if not intended_link(target, source):
        raise ValueError(f"Stow did not create the intended .bashrc link: {target}")
    directory = home / ".bashrc-backups"
    if not os.path.lexists(directory):
        return {"changed": False, "reason": "Stow link verified; no custom backup note"}
    ensure_private_directory(directory)
    pending = []
    for note in directory.glob("bashrc-*.note"):
        backup = note.with_suffix("")
        info = regular(note)
        original = regular(backup)
        if not info or info.st_uid != os.geteuid() or not original or original.st_uid != os.geteuid():
            raise ValueError(f"unsafe .bashrc recovery note or backup: {note}")
        content = note.read_text()
        if content == note_text(target, backup, source, PENDING):
            pending.append(note)
        elif content != note_text(target, backup, source, VERIFIED):
            raise ValueError(f"unrecognized .bashrc recovery note: {note}")
    if len(pending) > 1:
        raise ValueError("multiple pending .bashrc notes; refusing ambiguous finalization")
    if not pending:
        return {"changed": False, "reason": "Stow link and note already verified"}
    note = pending[0]
    backup = note.with_suffix("")
    # Replace the note atomically only after confirming the link; an interrupted
    # write leaves the old honest pending note and the backup intact.
    fd, temp = tempfile.mkstemp(prefix=".bashrc-note-", dir=directory)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(note_text(target, backup, source, VERIFIED))
            output.flush()
            os.fsync(output.fileno())
        if not intended_link(target, source):
            raise ValueError(".bashrc link changed before note finalization")
        os.replace(temp, note)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)
    return {"changed": True, "note": str(note), "reason": "Stow .bashrc link verified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--skel", required=True, type=Path)
    parser.add_argument("--packages-json", required=True)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    try:
        operation = finalize if args.finalize else prepare
        result = operation(args.home, args.skel, json.loads(args.packages_json))
    except (OSError, ValueError, TypeError) as exc:
        print(f".bashrc policy stopped: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
