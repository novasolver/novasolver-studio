"""Shared Codex MCP writer; validation is read-only unless apply=True.

Never prints existing configuration, which may contain credentials.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import tempfile
import uuid

from . import __version__

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

SERVER = 'novasolver-studio'
ARGS = [f'novasolver-studio=={__version__}', 'mcp']
TABLE = f'''[mcp_servers.novasolver-studio]
command = "uvx"
args = ["{ARGS[0]}", "mcp"]
startup_timeout_sec = 120
tool_timeout_sec = 120
'''


def copy_existing(source: Path, destination: Path, original: bytes) -> None:
    with os.fdopen(os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
        if os.name == 'nt':
            preserve_windows_acl(source, destination)  # Before writing any existing data.
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())


def preserve_windows_acl(source: Path, destination: Path) -> None:
    from ctypes import wintypes
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    get = api.GetFileSecurityW
    get.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get.restype = wintypes.BOOL
    size = wintypes.DWORD()
    get(str(source), 4, None, 0, ctypes.byref(size))
    if not size.value:
        raise OSError('Cannot read existing access rules.')
    descriptor = ctypes.create_string_buffer(size.value)
    if not get(str(source), 4, descriptor, size, ctypes.byref(size)):
        raise OSError('Cannot read existing access rules.')
    control = wintypes.WORD()
    revision = wintypes.DWORD()
    api.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    if not api.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
        raise OSError('Cannot read access-rule inheritance.')
    set_acl = api.SetFileSecurityW
    set_acl.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    set_acl.restype = wintypes.BOOL
    inheritance = 0x80000000 if control.value & 0x1000 else 0x20000000
    if not set_acl(str(destination), 4 | inheritance, descriptor):
        raise OSError('Cannot preserve access rules.')


def plan(original: bytes) -> bytes:
    text = original.decode('utf-8-sig')
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ValueError('Existing TOML is invalid; nothing changed.') from None
    servers = parsed.get('mcp_servers', {})
    if not isinstance(servers, dict):
        raise ValueError('Existing mcp_servers is not a table; nothing changed.')
    if SERVER in servers:
        existing = servers[SERVER]
        if (isinstance(existing, dict) and existing.get('command') == 'uvx'
                and existing.get('args') == ARGS and not existing.get('url')):
            return original  # Preserve approval settings and user customization.
        raise ValueError('A different Studio configuration already exists; nothing changed.')
    newline = '\r\n' if '\r\n' in text else '\n'
    addition = (newline if text.endswith(newline) else newline * 2) if text else ''
    updated = original + (addition + TABLE.replace('\n', newline)).encode('utf-8')
    tomllib.loads(updated.decode('utf-8-sig'))
    return updated


def configure(path: Path, apply: bool = False, expected: str | None = None) -> str:
    if path.is_symlink():
        raise ValueError('Symlink configuration is not supported; nothing changed.')
    if os.name == 'nt' and path.exists() and path.stat().st_file_attributes & 0x4000:
        raise ValueError('Encrypted configuration requires the native Codex setup command.')
    exists = path.exists()
    original = path.read_bytes() if exists else b''
    if expected is not None and expected != revision(exists, original):
        raise ValueError("Configuration changed since preview; nothing changed.")
    updated = plan(original)
    if updated == original:
        return 'Studio is already configured; no changes.'
    if not apply:
        return 'Dry run passed. One Studio MCP table would be added; no files changed.'
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + '.novasolver.lock')
    lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    temp_path = None
    try:
        current = path.read_bytes() if path.exists() else b''
        if path.is_symlink() or path.exists() != exists or current != original:
            raise ValueError('Configuration changed during preparation; nothing changed.')
        if exists:
            backup = path.with_name(path.name + '.novasolver-backup-' + uuid.uuid4().hex)
            copy_existing(path, backup, original)
        if exists and os.name == 'nt':
            temp_path = path.with_name(path.name + '.novasolver-' + uuid.uuid4().hex)
            copy_existing(path, temp_path, original)
            fd = os.open(temp_path, os.O_WRONLY | os.O_TRUNC)
        else:
            fd, name = tempfile.mkstemp(prefix=path.name + '.novasolver-', dir=path.parent)
            temp_path = Path(name)
            if exists:
                os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or path.exists() != exists or (path.read_bytes() if exists else b'') != original:
            raise ValueError('Configuration changed before replacement; update cancelled.')
        os.replace(temp_path, path)
        return 'Studio MCP configuration added. Keep the adjacent backup private: it may contain credentials.' if exists else 'Studio MCP configuration created.'
    finally:
        os.close(lock_fd)
        lock.unlink()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def revision(exists: bool, original: bytes) -> str:
    return hashlib.sha256(bytes([exists]) + original).hexdigest()


def preview(path: Path) -> dict:
    configure(path)  # Validate through the same path as the writer; no side effects.
    exists = path.exists()
    original = path.read_bytes() if exists else b""
    return {"path": str(path), "status": "configured" if plan(original) == original else "ready",
            "revision": revision(exists, original), "table": TABLE}
