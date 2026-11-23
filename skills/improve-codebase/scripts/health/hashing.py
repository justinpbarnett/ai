import hashlib
import json
import os
import stat

FILE_CHUNK_BYTES = 1 << 20


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


def content_hash(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    hasher = hashlib.sha256()
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("not a regular file")
        while chunk := stream.read(FILE_CHUNK_BYTES):
            hasher.update(chunk)
    return hasher.hexdigest()
