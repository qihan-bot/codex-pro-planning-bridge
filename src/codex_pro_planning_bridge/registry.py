"""Versioned, local-only repository registry for the v0.4 control plane.

The registry is deliberately smaller than the future MCP surface.  It is a
per-user allowlist used by local CLI commands; it never accepts arbitrary
repository paths from a future MCP caller and it never writes inside a
registered repository.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import re
import sys
import threading
from typing import Any, Iterator, List, Mapping

from .repository import atomic_write_text, is_ignored_path, run_git


REGISTRY_SCHEMA_VERSION = 1
REGISTRY_ENV_VAR = "CPB_REGISTRY_PATH"
REGISTRY_DIRECTORY_NAME = "codex-pro-planning-bridge"
REGISTRY_FILENAME = "repositories.json"
REGISTRY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
RESERVED_REPOSITORY_IDS = frozenset(
    {"all", "default", "none", "system", "root", "home", "latest"}
)

_REGISTRATION_FIELDS = frozenset(
    {
        "display_name",
        "canonical_path",
        "enabled",
        "read",
        "created_at",
        "updated_at",
        "notes",
    }
)
_DANGEROUS_DIRECTORY_NAMES = frozenset(
    {
        ".aws",
        ".azure",
        ".gnupg",
        ".kube",
        ".ssh",
        "credential",
        "credentials",
        "keychain",
        "password-store",
        "passwords",
        "private-keys",
        "secrets",
        "tokens",
    }
)
MAX_SCAN_FILES = 1_000
MAX_SCAN_DIRECTORIES = 1_000
MAX_SCAN_DEPTH = 32


class RegistryError(ValueError):
    """A safe, user-facing registry error with a stable category."""

    def __init__(self, message: str, *, code: str = "registry_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScanLimits:
    """Hard limits for a bounded, non-executing repository preview."""

    max_files: int = MAX_SCAN_FILES
    max_directories: int = MAX_SCAN_DIRECTORIES
    max_depth: int = MAX_SCAN_DEPTH

    def __post_init__(self) -> None:
        if self.max_files < 1 or self.max_directories < 1 or self.max_depth < 0:
            raise ValueError("scan limits must be positive, with max_depth >= 0")


@dataclass(frozen=True)
class ScanSummary:
    """Observed scan facts; counts are not complete when ``scan_truncated`` is true."""

    redacted_count: int = 0
    omitted_count: int = 0
    symlink_escapes: int = 0
    visited_files: int = 0
    visited_directories: int = 0
    unreadable_directories: int = 0
    scan_truncated: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RegistryError(f"registry field {field!r} must be an ISO-8601 timestamp", code="corrupt")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RegistryError(
            f"registry field {field!r} contains an invalid timestamp",
            code="corrupt",
        ) from error
    if parsed.tzinfo is None:
        raise RegistryError(
            f"registry field {field!r} must include a timezone",
            code="corrupt",
        )
    return value


def normalize_repository_id(repository_id: str) -> str:
    """Canonicalize and validate a repository ID before persistence."""

    if not isinstance(repository_id, str):
        raise RegistryError("repository ID must be a string", code="invalid_id")
    normalized = repository_id.strip().casefold()
    if not REGISTRY_ID_PATTERN.fullmatch(normalized):
        raise RegistryError(
            "repository ID must be 1-64 lowercase letters, digits, '.', '_' or '-' "
            "and must start with a letter or digit",
            code="invalid_id",
        )
    if normalized in RESERVED_REPOSITORY_IDS:
        raise RegistryError(
            f"repository ID is reserved: {normalized}",
            code="invalid_id",
        )
    return normalized


def validate_repository_id(repository_id: str) -> str:
    """Validate and return the lowercase canonical repository ID."""

    return normalize_repository_id(repository_id)


def default_registry_path() -> Path:
    """Return the documented per-user registry path for the current platform."""

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / REGISTRY_DIRECTORY_NAME / REGISTRY_FILENAME


def registry_path_from_environment(value: str | Path | None = None) -> Path:
    """Resolve the local CLI/test override without exposing it as MCP input."""

    selected = value if value is not None else os.environ.get(REGISTRY_ENV_VAR)
    if selected is None:
        selected = default_registry_path()
    return Path(selected).expanduser().resolve(strict=False)


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _is_link_or_junction(path: Path) -> bool:
    """Detect symbolic links and Windows junctions across supported Python versions."""

    if os.path.islink(path):
        return True
    junction_checker = getattr(path, "is_junction", None)
    if callable(junction_checker):
        try:
            if junction_checker():
                return True
        except OSError:
            return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    # FILE_ATTRIBUTE_REPARSE_POINT. Python 3.10 does not expose Path.is_junction.
    return bool(attributes & 0x400)


def _safe_chmod(path: Path, mode: int = 0o600) -> None:
    if sys.platform != "win32":
        try:
            path.chmod(mode)
        except OSError:
            pass


@dataclass(frozen=True)
class RepositoryRegistration:
    """One allowlisted repository entry."""

    repository_id: str
    display_name: str
    canonical_path: Path
    enabled: bool = True
    read: bool = True
    created_at: str = ""
    updated_at: str = ""
    notes: str | None = None

    def __post_init__(self) -> None:
        normalized_id = validate_repository_id(self.repository_id)
        if normalized_id != self.repository_id:
            object.__setattr__(self, "repository_id", normalized_id)
        if not self.display_name.strip() or len(self.display_name) > 200:
            raise RegistryError("display name must contain 1-200 characters", code="invalid_entry")
        if not self.canonical_path.is_absolute():
            raise RegistryError("canonical repository path must be absolute", code="invalid_entry")
        if not isinstance(self.enabled, bool) or not isinstance(self.read, bool):
            raise RegistryError("enabled and read must be booleans", code="invalid_entry")
        if self.notes is not None and len(self.notes) > 2_000:
            raise RegistryError("repository notes cannot exceed 2000 characters", code="invalid_entry")
        if self.created_at:
            _validate_timestamp(self.created_at, "created_at")
        if self.updated_at:
            _validate_timestamp(self.updated_at, "updated_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "display_name": self.display_name,
            "canonical_path": str(self.canonical_path),
            "enabled": self.enabled,
            "read": self.read,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, repository_id: str, payload: object) -> "RepositoryRegistration":
        normalized_id = validate_repository_id(repository_id)
        if normalized_id != repository_id:
            raise RegistryError(
                f"repository entry {repository_id!r} is not a canonical lowercase ID",
                code="corrupt",
            )
        if not isinstance(payload, dict):
            raise RegistryError(
                f"repository entry {repository_id!r} must be an object",
                code="corrupt",
            )
        if set(payload) != _REGISTRATION_FIELDS:
            raise RegistryError(
                f"repository entry {repository_id!r} has an unsupported schema",
                code="corrupt",
            )
        canonical_value = payload["canonical_path"]
        if not isinstance(canonical_value, str) or not canonical_value:
            raise RegistryError(
                f"repository entry {repository_id!r} has an invalid canonical path",
                code="corrupt",
            )
        canonical_path = Path(canonical_value).expanduser()
        if not canonical_path.is_absolute():
            raise RegistryError(
                f"repository entry {repository_id!r} must store an absolute path",
                code="corrupt",
            )
        display_name = payload["display_name"]
        enabled = payload["enabled"]
        readable = payload["read"]
        created_at = payload["created_at"]
        updated_at = payload["updated_at"]
        notes = payload["notes"]
        if not isinstance(display_name, str):
            raise RegistryError(f"repository entry {repository_id!r} has an invalid display name", code="corrupt")
        if not isinstance(enabled, bool) or not isinstance(readable, bool):
            raise RegistryError(f"repository entry {repository_id!r} has invalid access flags", code="corrupt")
        if not isinstance(created_at, str) or not isinstance(updated_at, str):
            raise RegistryError(f"repository entry {repository_id!r} has invalid timestamps", code="corrupt")
        if notes is not None and not isinstance(notes, str):
            raise RegistryError(f"repository entry {repository_id!r} has invalid notes", code="corrupt")
        _validate_timestamp(created_at, "created_at")
        _validate_timestamp(updated_at, "updated_at")
        return cls(
            repository_id=repository_id,
            display_name=display_name,
            canonical_path=canonical_path,
            enabled=enabled,
            read=readable,
            created_at=created_at,
            updated_at=updated_at,
            notes=notes,
        )


@dataclass(frozen=True)
class RepositoryPreview:
    """Non-mutating result used by the CLI before confirmation."""

    canonical_path: Path
    is_git: bool
    git_root: Path | None
    redacted_count: int = 0
    symlink_escapes: int = 0
    warnings: tuple[str, ...] = ()
    omitted_count: int = 0
    visited_files: int = 0
    visited_directories: int = 0
    unreadable_directories: int = 0
    scan_truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_path": str(self.canonical_path),
            "is_git": self.is_git,
            "git_root": str(self.git_root) if self.git_root else None,
            "redacted_count": self.redacted_count,
            "symlink_escapes": self.symlink_escapes,
            "omitted_count": self.omitted_count,
            "visited_files": self.visited_files,
            "visited_directories": self.visited_directories,
            "unreadable_directories": self.unreadable_directories,
            "scan_truncated": self.scan_truncated,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class RepositoryHealth:
    """Bounded, local health information for ``cpb repo doctor``."""

    repository_id: str
    available: bool
    canonical_path: Path | None
    root_identity_ok: bool
    is_git: bool
    git_root: Path | None = None
    head: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    redacted_count: int = 0
    omitted_count: int = 0
    symlink_escapes: int = 0
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()
    visited_files: int = 0
    visited_directories: int = 0
    unreadable_directories: int = 0
    scan_truncated: bool = False

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        return {
            "repository_id": self.repository_id,
            "ok": self.ok,
            "available": self.available,
            "canonical_path": str(self.canonical_path) if self.canonical_path else None,
            "root_identity_ok": self.root_identity_ok,
            "is_git": self.is_git,
            "git_root": str(self.git_root) if self.git_root else None,
            "head": self.head,
            "branch": self.branch,
            "dirty": self.dirty,
            "redacted_count": self.redacted_count,
            "omitted_count": self.omitted_count,
            "symlink_escapes": self.symlink_escapes,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "error_codes": list(self.error_codes),
            "visited_files": self.visited_files,
            "visited_directories": self.visited_directories,
            "unreadable_directories": self.unreadable_directories,
            "scan_truncated": self.scan_truncated,
        }


_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path: Path) -> threading.RLock:
    key = str(path).casefold() if sys.platform == "win32" else str(path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Hold an inter-process lock using only the Python standard library."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RegistryError("registry lock path must not be a symlink", code="unsafe_storage")
    with path.open("a+b") as handle:
        _safe_chmod(path)
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        locker: Any
        if sys.platform == "win32":
            locker = importlib.import_module("msvcrt")
            locker.locking(handle.fileno(), locker.LK_LOCK, 1)
        else:
            locker = importlib.import_module("fcntl")
            locker.flock(handle.fileno(), locker.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                locker.locking(handle.fileno(), locker.LK_UNLCK, 1)
            else:
                locker.flock(handle.fileno(), locker.LOCK_UN)


class RepositoryRegistry:
    """Read and atomically persist the per-user repository allowlist."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        scan_limits: ScanLimits | None = None,
    ) -> None:
        self.path = registry_path_from_environment(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.scan_limits = scan_limits or ScanLimits()

    def _ensure_storage_is_safe(self) -> None:
        if self.path.is_symlink():
            raise RegistryError("registry file must not be a symlink", code="unsafe_storage")
        if self.lock_path.is_symlink():
            raise RegistryError("registry lock path must not be a symlink", code="unsafe_storage")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_storage_is_safe()
        with _thread_lock_for(self.lock_path):
            with _file_lock(self.lock_path):
                self._ensure_storage_is_safe()
                yield

    def _load_unlocked(self) -> dict[str, RepositoryRegistration]:
        self._ensure_storage_is_safe()
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RegistryError(
                "repository registry is corrupt; the existing file was preserved",
                code="corrupt",
            ) from error
        if not isinstance(payload, dict):
            raise RegistryError(
                "repository registry root must be an object; the existing file was preserved",
                code="corrupt",
            )
        if set(payload) != {"schema_version", "updated_at", "repositories"}:
            raise RegistryError(
                "repository registry has an unsupported schema; the existing file was preserved",
                code="corrupt",
            )
        schema_version = payload["schema_version"]
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise RegistryError("repository registry schema_version is invalid", code="corrupt")
        if schema_version != REGISTRY_SCHEMA_VERSION:
            raise RegistryError(
                f"unsupported repository registry schema version: {schema_version}",
                code="unsupported_schema",
            )
        _validate_timestamp(payload["updated_at"], "updated_at")
        repositories = payload["repositories"]
        if not isinstance(repositories, dict):
            raise RegistryError("repository registry repositories must be an object", code="corrupt")
        result: dict[str, RepositoryRegistration] = {}
        for repository_id in sorted(repositories):
            if not isinstance(repository_id, str):
                raise RegistryError("repository registry contains a non-string ID", code="corrupt")
            result[repository_id] = RepositoryRegistration.from_dict(
                repository_id,
                repositories[repository_id],
            )
        return result

    def _write_unlocked(self, repositories: Mapping[str, RepositoryRegistration]) -> None:
        self._ensure_storage_is_safe()
        payload: dict[str, object] = {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "updated_at": _utc_now(),
            "repositories": {
                repository_id: repositories[repository_id].to_dict()
                for repository_id in sorted(repositories)
            },
        }
        content = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        atomic_write_text(self.path, content)
        _safe_chmod(self.path)

    def list(self) -> List[RepositoryRegistration]:
        return list(self._load_unlocked().values())

    def list_repositories(self) -> List[RepositoryRegistration]:
        return self.list()

    def get(self, repository_id: str) -> RepositoryRegistration:
        repository_id = validate_repository_id(repository_id)
        repositories = self._load_unlocked()
        try:
            return repositories[repository_id]
        except KeyError as error:
            raise RegistryError(
                f"repository is not registered: {repository_id}",
                code="not_found",
            ) from error

    def show(self, repository_id: str) -> RepositoryRegistration:
        return self.get(repository_id)

    def _canonicalize_registration_path(self, value: str | Path) -> Path:
        try:
            candidate = Path(value).expanduser()
        except (TypeError, ValueError) as error:
            raise RegistryError("repository path is invalid", code="invalid_path") from error
        try:
            canonical = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise RegistryError(
                "repository path must be an existing directory",
                code="invalid_path",
            ) from error
        if not canonical.is_dir():
            raise RegistryError("repository path must be a directory", code="invalid_path")
        self._validate_canonical_path_policy(canonical)
        return canonical

    def _validate_canonical_path_policy(self, canonical: Path) -> None:
        if canonical == Path(canonical.anchor):
            raise RegistryError("filesystem roots cannot be registered", code="unsafe_path")
        try:
            home = Path.home().resolve(strict=True)
        except OSError:
            home = Path.home().resolve(strict=False)
        if canonical == home:
            raise RegistryError("the user home directory cannot be registered", code="unsafe_path")
        config_dir = self.path.parent.resolve(strict=False)
        if canonical == config_dir:
            raise RegistryError("the bridge configuration directory cannot be registered", code="unsafe_path")
        parts = {part.casefold() for part in canonical.parts}
        dangerous = {name.casefold() for name in _DANGEROUS_DIRECTORY_NAMES}
        if parts.intersection(dangerous):
            raise RegistryError(
                "credential and secret directories cannot be registered",
                code="unsafe_path",
            )
        canonical_parts = [part.casefold() for part in canonical.parts]
        if any(
            first == ".config" and second == "gcloud"
            for first, second in zip(canonical_parts, canonical_parts[1:])
        ):
            raise RegistryError(
                "credential and secret directories cannot be registered",
                code="unsafe_path",
            )
        if canonical.name.casefold() in {".env", ".git-credentials"}:
            raise RegistryError("secret paths cannot be registered", code="unsafe_path")

    def _git_details(self, canonical: Path) -> tuple[bool, Path | None]:
        output = run_git(canonical, ("rev-parse", "--show-toplevel"))
        if not output:
            return False, None
        try:
            git_root = Path(output).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return False, None
        if not _is_within(git_root, canonical):
            raise RegistryError(
                "Git reported a repository root outside the registered path",
                code="unsafe_path",
            )
        return True, git_root

    def _prepare_path(
        self,
        value: str | Path,
        *,
        allow_non_git: bool,
        scan: bool,
    ) -> RepositoryPreview:
        canonical = self._canonicalize_registration_path(value)
        is_git, git_root = self._git_details(canonical)
        if is_git and git_root != canonical:
            raise RegistryError(
                "a Git subdirectory cannot be registered; register the Git root instead",
                code="git_subdirectory",
            )
        warnings: list[str] = []
        if not is_git:
            if not allow_non_git:
                raise RegistryError(
                    "path is not a Git repository; pass --allow-non-git to register it",
                    code="non_git",
                )
            warnings.append("registered path is not a Git repository")
        summary = self._scan_path(canonical) if scan else ScanSummary()
        if summary.redacted_count:
            warnings.append(
                f"{summary.redacted_count} sensitive or excluded paths were observed and redacted"
            )
        if summary.symlink_escapes:
            warnings.append(
                f"{summary.symlink_escapes} child symlink or junctions escape the registered root"
            )
        if summary.scan_truncated:
            warnings.append("repository scan reached its safety budget; counts are incomplete")
        if summary.unreadable_directories:
            warnings.append(f"{summary.unreadable_directories} directories could not be read")
        return RepositoryPreview(
            canonical_path=canonical,
            is_git=is_git,
            git_root=git_root,
            redacted_count=summary.redacted_count,
            symlink_escapes=summary.symlink_escapes,
            warnings=tuple(warnings),
            omitted_count=summary.omitted_count,
            visited_files=summary.visited_files,
            visited_directories=summary.visited_directories,
            unreadable_directories=summary.unreadable_directories,
            scan_truncated=summary.scan_truncated,
        )

    def preview(self, value: str | Path, *, allow_non_git: bool = False) -> RepositoryPreview:
        """Validate a path without changing registry or repository files."""

        return self._prepare_path(value, allow_non_git=allow_non_git, scan=True)

    def add(
        self,
        repository_id: str,
        path: str | Path,
        *,
        display_name: str | None = None,
        allow_non_git: bool = False,
        notes: str | None = None,
    ) -> RepositoryRegistration:
        repository_id = validate_repository_id(repository_id)
        # Validate before acquiring the registry lock. The filesystem scan is
        # intentionally never performed while the registry is locked.
        self._prepare_path(path, allow_non_git=allow_non_git, scan=False)
        with self._locked():
            repositories = self._load_unlocked()
            if repository_id in repositories:
                raise RegistryError(
                    f"repository ID is already registered: {repository_id}",
                    code="duplicate_id",
                )
            preview = self._prepare_path(path, allow_non_git=allow_non_git, scan=False)
            now = _utc_now()
            name = display_name if display_name is not None else preview.canonical_path.name
            if not name:
                name = repository_id
            registration = RepositoryRegistration(
                repository_id=repository_id,
                display_name=name,
                canonical_path=preview.canonical_path,
                created_at=now,
                updated_at=now,
                notes=notes,
            )
            repositories[repository_id] = registration
            self._write_unlocked(repositories)
            return registration

    def remove(self, repository_id: str) -> RepositoryRegistration:
        repository_id = validate_repository_id(repository_id)
        with self._locked():
            repositories = self._load_unlocked()
            try:
                removed = repositories.pop(repository_id)
            except KeyError as error:
                raise RegistryError(
                    f"repository is not registered: {repository_id}",
                    code="not_found",
                ) from error
            self._write_unlocked(repositories)
            return removed

    def authorized(self, repository_id: str) -> RepositoryRegistration:
        """Backward-compatible alias for the complete authorization check."""

        return self.resolve_authorized(repository_id)

    def resolve_authorized(self, repository_id: str) -> RepositoryRegistration:
        """Return a registration only after validating its live filesystem identity.

        ``get`` intentionally remains a metadata-only operation.  Callers that
        will read from a repository must use this method so disabled/read-only
        flags, existence, directory identity, path policy, and Git-root
        boundaries are checked at the point of use.
        """

        registration = self.get(repository_id)
        if not registration.enabled:
            raise RegistryError(f"repository is disabled: {repository_id}", code="disabled")
        if not registration.read:
            raise RegistryError(
                f"repository read access is disabled: {repository_id}",
                code="read_denied",
            )
        stored_path = registration.canonical_path
        try:
            current_path = stored_path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise RegistryError(
                f"registered repository is missing: {repository_id}",
                code="missing",
            ) from error
        if not current_path.is_dir():
            raise RegistryError(
                f"registered repository is not a directory: {repository_id}",
                code="not_directory",
            )
        if current_path != stored_path:
            raise RegistryError(
                f"registered repository root identity changed: {repository_id}",
                code="redirected",
            )
        self._validate_canonical_path_policy(current_path)
        is_git, git_root = self._git_details(current_path)
        if is_git and git_root != current_path:
            raise RegistryError(
                "a Git subdirectory cannot be used as an authorized repository root",
                code="git_subdirectory",
            )
        return registration

    def doctor(self, repository_id: str) -> RepositoryHealth:
        registration = self.get(repository_id)
        stored_path = registration.canonical_path
        issues: list[str] = []
        warnings: list[str] = []
        error_codes: list[str] = []
        try:
            current_path = stored_path.resolve(strict=True)
        except (OSError, RuntimeError):
            current_path = None
        root_identity_ok = current_path == stored_path if current_path is not None else False
        available = current_path is not None and current_path.is_dir() and root_identity_ok
        if not available:
            if current_path is None:
                issues.append("registered path is missing")
                error_codes.append("missing")
            elif not current_path.is_dir():
                issues.append("registered path is not a directory")
                error_codes.append("not_directory")
            else:
                issues.append("registered path root identity changed")
                error_codes.append("redirected")
        if not registration.enabled:
            warnings.append("repository is disabled")
        if not registration.read:
            warnings.append("repository read access is disabled")

        is_git = False
        git_root: Path | None = None
        head: str | None = None
        branch: str | None = None
        dirty: bool | None = None
        redacted_count = 0
        omitted_count = 0
        symlink_escapes = 0
        visited_files = 0
        visited_directories = 0
        unreadable_directories = 0
        scan_truncated = False
        path_policy_ok = True
        if available and current_path is not None:
            try:
                self._validate_canonical_path_policy(current_path)
            except RegistryError as error:
                issues.append(str(error))
                error_codes.append(error.code)
                path_policy_ok = False
                available = False
        if available and current_path is not None and path_policy_ok:
            is_git, git_root = self._git_details(current_path)
            if is_git and git_root != current_path:
                issues.append("registered path is a Git subdirectory, not the Git root")
                error_codes.append("git_subdirectory")
            if is_git:
                head = run_git(current_path, ("rev-parse", "HEAD"))
                branch = run_git(current_path, ("symbolic-ref", "--short", "-q", "HEAD")) or None
                status = run_git(current_path, ("status", "--porcelain", "--untracked-files=all"))
                dirty = bool(status)
            else:
                warnings.append("registered path is not a Git repository")
            summary = self._scan_path(current_path)
            redacted_count = summary.redacted_count
            omitted_count = summary.omitted_count
            symlink_escapes = summary.symlink_escapes
            visited_files = summary.visited_files
            visited_directories = summary.visited_directories
            unreadable_directories = summary.unreadable_directories
            scan_truncated = summary.scan_truncated
            if symlink_escapes:
                issues.append(f"{symlink_escapes} child symlink or junction escapes the registered root")
                error_codes.append("symlink_escape")
            if scan_truncated:
                warnings.append("repository scan reached its safety budget; counts are incomplete")
            if unreadable_directories:
                warnings.append(f"{unreadable_directories} directories could not be read")
        return RepositoryHealth(
            repository_id=repository_id,
            available=available,
            canonical_path=stored_path,
            root_identity_ok=root_identity_ok,
            is_git=is_git,
            git_root=git_root,
            head=head,
            branch=branch,
            dirty=dirty,
            redacted_count=redacted_count,
            omitted_count=omitted_count,
            symlink_escapes=symlink_escapes,
            issues=tuple(issues),
            warnings=tuple(warnings),
            error_codes=tuple(dict.fromkeys(error_codes)),
            visited_files=visited_files,
            visited_directories=visited_directories,
            unreadable_directories=unreadable_directories,
            scan_truncated=scan_truncated,
        )

    def _scan_path(self, root: Path) -> ScanSummary:
        """Collect bounded, observed filesystem facts without following links."""

        redacted = 0
        symlink_escapes = 0
        visited_files = 0
        visited_directories = 0
        unreadable_directories = 0
        scan_truncated = False
        seen_files: set[tuple[int, int] | str] = set()
        seen_directories: set[tuple[int, int] | str] = set()
        pending: list[tuple[Path, int]] = [(root, 0)]

        while pending:
            current, depth = pending.pop()
            if visited_directories >= self.scan_limits.max_directories:
                scan_truncated = True
                break
            directory_identity = self._path_identity(current)
            if directory_identity is not None and directory_identity in seen_directories:
                continue
            if directory_identity is not None:
                seen_directories.add(directory_identity)
            visited_directories += 1
            try:
                with os.scandir(current) as iterator:
                    entries = sorted(list(iterator), key=lambda entry: entry.name.casefold())
            except (OSError, PermissionError):
                unreadable_directories += 1
                continue

            for entry in entries:
                child = Path(entry.path)
                relative = child.relative_to(root).as_posix()
                try:
                    entry_is_directory = entry.is_dir(follow_symlinks=False)
                except OSError:
                    unreadable_directories += 1
                    continue
                ignored_value: str | Path = Path(relative) / "marker" if entry_is_directory else relative
                if is_ignored_path(ignored_value):
                    redacted += 1
                    continue
                if _is_link_or_junction(child):
                    try:
                        resolved = child.resolve(strict=False)
                    except (OSError, RuntimeError):
                        symlink_escapes += 1
                        continue
                    if not _is_within(root, resolved):
                        symlink_escapes += 1
                    continue
                if entry_is_directory:
                    if depth >= self.scan_limits.max_depth:
                        scan_truncated = True
                        continue
                    if visited_directories + len(pending) >= self.scan_limits.max_directories:
                        scan_truncated = True
                        break
                    pending.append((child, depth + 1))
                    continue
                if visited_files >= self.scan_limits.max_files:
                    scan_truncated = True
                    break
                file_identity = self._path_identity(child)
                if file_identity is not None and file_identity in seen_files:
                    continue
                if file_identity is not None:
                    seen_files.add(file_identity)
                visited_files += 1
            if visited_files >= self.scan_limits.max_files:
                scan_truncated = True
                break

        return ScanSummary(
            redacted_count=redacted,
            omitted_count=0,
            symlink_escapes=symlink_escapes,
            visited_files=visited_files,
            visited_directories=visited_directories,
            unreadable_directories=unreadable_directories,
            scan_truncated=scan_truncated,
        )

    @staticmethod
    def _path_identity(path: Path) -> tuple[int, int] | str | None:
        try:
            stat_result = path.stat()
        except OSError:
            return None
        identity = (stat_result.st_dev, stat_result.st_ino)
        if identity != (0, 0):
            return identity
        return str(path).casefold() if sys.platform == "win32" else str(path)
