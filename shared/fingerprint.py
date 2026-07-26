"""Content fingerprints for cache-correct identity checks.

Deliberately dependency-free (stdlib only) so every skill can carry its own copy without
importing anything from a sibling skill.

These digests are compared ACROSS skills — video-cut writes edited_source.mp4.meta.json,
video-recap and video-assemble read it — so the copies must agree byte for byte. That is
why this file is generated from one source rather than maintained seven times.
"""
import hashlib
import os

_FILE_FINGERPRINT_MEMO = {}


def _file_identity(path):
    """(device, inode, size, mtime_ns) — changes whenever the bytes could have changed."""
    st = os.stat(os.fspath(path))
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def file_fingerprint(path, chunk_size=1024 * 1024):
    """Return a full-content fingerprint for cache-correct identity checks.

    The digest covers CONTENT only — never the path or mtime — so a copied video or
    artifact is still recognised as the same asset, while any byte change invalidates
    the cache even if timestamps, size, head, or tail bytes are misleading.

    Identity metadata is used ONLY to memoize within a single process. One understanding
    run fingerprints the same source video 8-10 times and the whole extracted frame set
    2-3 times; on a 40-minute video at fps=1 that is gigabytes of redundant reads before
    any real work starts. A file rewritten in place gets a new (size, mtime_ns) and is
    re-hashed, so the memo can never serve a stale digest.
    """
    key = _file_identity(path)
    memoized = _FILE_FINGERPRINT_MEMO.get(key)
    if memoized is not None:
        return memoized
    h = hashlib.sha256()
    with open(os.fspath(path), "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    digest = h.hexdigest()
    _FILE_FINGERPRINT_MEMO[key] = digest
    return digest


def stable_json_dumps(value):
    """Serialize deterministically for non-secret cache fingerprints."""
    import json

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def value_fingerprint(value):
    """Return a stable fingerprint for JSON-serializable non-secret values."""
    return hashlib.md5(stable_json_dumps(value).encode("utf-8")).hexdigest()
