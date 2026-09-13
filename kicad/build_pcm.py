#!/usr/bin/env python3
"""Build the PCM archive and the metadata that describes it.

KiCad expects metadata.json at the archive root, plugin code under plugins/,
and a 64x64 resources/icon.png. The gate package travels inside plugins/ so the
installed plugin can import it — verified against published packages, which
ship nested subdirectories there despite the documentation's "no
subdirectories" wording.

The download_* fields are computed here rather than maintained by hand, because
three numbers describing an artifact will drift from it otherwise. They are
written only into the submission copy: the spec forbids them inside the
archive, and copying one file to both places is the easy way to break that.
"""
import hashlib
import json
import os
import zipfile


# The zip format's own epoch. Pinning every entry to it is what makes the
# archive byte-reproducible: writestr() otherwise stamps metadata.json with the
# build time and write() copies each source file's mtime, so one unchanged tree
# produced a different sha256 on every build. That matters because the sha256
# in the submission describes one exact artifact — an unnoticed rebuild between
# hashing and uploading silently invalidates it, and nobody can check the
# published package by building it themselves.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _add(zf, arcname, data, mode=0o644):
    """Write one entry at the pinned timestamp."""
    info = zipfile.ZipInfo(arcname, date_time=ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    zf.writestr(info, data)


def _files(root):
    """Every shippable file under root. Bytecode is build output, not source."""
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(names):
            if name.endswith(".pyc"):
                continue
            yield os.path.join(base, name)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def build(repo_root, out_dir):
    """Write the archive into out_dir; return (archive_path, submission_meta)."""
    kicad = os.path.join(repo_root, "kicad")
    with open(os.path.join(kicad, "metadata.json")) as handle:
        metadata = json.load(handle)

    version = metadata["versions"][0]["version"]
    archive = os.path.join(out_dir, f"prefab-gate-{version}-pcm.zip")

    install_size = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        _add(zf, "metadata.json", json.dumps(metadata, indent=4))

        for source_root in (os.path.join(kicad, "plugin"),
                            os.path.join(repo_root, "scripts")):
            for path in _files(source_root):
                arcname = "plugins/" + os.path.relpath(
                    path, source_root).replace(os.sep, "/")
                with open(path, "rb") as handle:
                    payload = handle.read()
                _add(zf, arcname, payload)
                install_size += len(payload)

        icon = os.path.join(kicad, "icon.png")
        with open(icon, "rb") as handle:
            payload = handle.read()
        _add(zf, "resources/icon.png", payload)
        install_size += len(payload)

    submission = json.loads(json.dumps(metadata))
    submission["versions"][0].update({
        "download_sha256": _sha256(archive),
        "download_size": os.path.getsize(archive),
        "install_size": install_size,
    })
    return archive, submission


if __name__ == "__main__":
    root = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    out = os.path.join(root, "dist")
    os.makedirs(out, exist_ok=True)
    archive_path, meta = build(root, out)
    submission_path = os.path.join(out, "metadata.submission.json")
    with open(submission_path, "w") as handle:
        json.dump(meta, handle, indent=4)
    print(f"archive:    {archive_path} "
          f"({meta['versions'][0]['download_size']} bytes)")
    print(f"submission: {submission_path}")
    print("Set download_url to the release asset URL before submitting.")
