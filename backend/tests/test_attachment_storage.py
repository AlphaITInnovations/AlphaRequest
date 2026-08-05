"""Datei-Ablage (attachment_storage) + Datei-Utils – ohne DB."""

import hashlib
import io

import pytest

from backend.services import attachment_storage as storage
from backend.utils.config import config
from backend.utils.files import safe_filename, human_size


def _use_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ATTACHMENTS_DIR", str(tmp_path))


def test_save_stream_returns_size_and_sha(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    data = b"hello world " * 1000
    rel, size, sha = storage.save_stream(io.BytesIO(data))
    assert size == len(data)
    assert sha == hashlib.sha256(data).hexdigest()
    p = storage.full_path(rel)
    assert p.is_file() and p.read_bytes() == data
    # geshardet: erste zwei Zeichen als Unterordner
    assert rel[2] == "/" and rel[:2] == rel.split("/")[1][:2]


def test_save_stream_too_large_cleans_up(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    with pytest.raises(storage.FileTooLarge):
        storage.save_stream(io.BytesIO(b"x" * 5000), max_bytes=1000)
    leftover = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert leftover == []   # keine partielle Datei


def test_full_path_rejects_traversal(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        storage.full_path("../secret")


def test_delete_removes_blob(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    rel, _, _ = storage.save_stream(io.BytesIO(b"abc"))
    assert storage.exists(rel)
    storage.delete(rel)
    assert not storage.exists(rel)


def test_safe_filename():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\\\temp\\\\report.pdf") == "report.pdf"
    assert safe_filename("   ") == "datei"
    assert safe_filename(None) == "datei"


def test_human_size():
    assert human_size(0) == "0 B"
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(5 * 1024 * 1024) == "5.0 MB"
