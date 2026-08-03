"""Regression tests for vault path safety and scheduler cron handling."""
from __future__ import annotations

import pytest

from app.scheduler import build_trigger
from app.services.vault import _safe_dir, _safe_path, list_vault_files


# ---------------------------------------------------------------------------
# Path traversal — the old prefix check let `vault-evil` through
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "../secrets.md",
        "../../etc/passwd",
        "../vault-evil/x.md",       # sibling directory sharing the vault prefix
        "00-Inbox/../../outside.md",
    ],
)
def test_safe_path_blocks_escapes(path):
    with pytest.raises(ValueError):
        _safe_path(path)


def test_safe_path_blocks_absolute_paths():
    with pytest.raises(ValueError):
        _safe_path("C:/Windows/System32/drivers/etc/hosts")


def test_safe_path_allows_normal_vault_paths():
    assert _safe_path("00-Inbox/brief-2026-06-01.md").name == "brief-2026-06-01.md"


def test_safe_dir_defaults_to_the_vault_root():
    assert _safe_dir("").name == "vault"


def test_list_vault_files_rejects_traversal():
    with pytest.raises(ValueError):
        list_vault_files("../")


def test_list_vault_files_lists_a_real_folder():
    files = list_vault_files("00-Inbox")
    assert files
    assert all(f["path"].startswith("00-Inbox/") for f in files)


# ---------------------------------------------------------------------------
# Cron validation — a bad expression used to leave the app with no scheduler
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expr", ["0 6 * * *", "0 7 * * 1-5", "*/15 * * * *"])
def test_valid_cron_builds_a_trigger(expr):
    assert build_trigger(expr) is not None


@pytest.mark.parametrize("expr", ["", "0 6 * *", "0 6 * * * *", "not a cron", "99 99 * * *"])
def test_invalid_cron_raises_value_error(expr):
    with pytest.raises(ValueError):
        build_trigger(expr)
