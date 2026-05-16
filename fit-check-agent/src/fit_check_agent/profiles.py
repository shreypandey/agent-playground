from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".json", ".yaml", ".yml"}
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".heic"}


class ProfileError(ValueError):
    """Raised when a profile directory cannot be loaded safely."""


@dataclass(frozen=True)
class TextContext:
    relative_path: str
    text: str


@dataclass(frozen=True)
class ProfileBundle:
    name: str
    root: Path
    text_contexts: tuple[TextContext, ...]
    image_paths: tuple[Path, ...]


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _profiles_root(profiles_dir: Path) -> Path:
    return profiles_dir.expanduser().resolve()


def validate_profile_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ProfileError("profile_name must be a non-empty string")
    clean = name.strip()
    if clean in {".", ".."} or "/" in clean or "\\" in clean:
        raise ProfileError(f"invalid profile name: {clean}")
    if clean.startswith("."):
        raise ProfileError("hidden profile directories are not allowed")
    return clean


def discover_profiles(profiles_dir: Path) -> list[str]:
    root = _profiles_root(profiles_dir)
    if not root.exists():
        return []
    profiles = [
        child.name
        for child in root.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    ]
    return sorted(profiles, key=str.casefold)


def _profile_path(profiles_dir: Path, profile_name: object) -> Path:
    name = validate_profile_name(profile_name)
    root = _profiles_root(profiles_dir)
    profile_root = (root / name).resolve()
    try:
        profile_root.relative_to(root)
    except ValueError as exc:
        raise ProfileError(f"profile escapes profiles directory: {name}") from exc
    if profile_root.parent != root:
        raise ProfileError(f"profile must be a direct child directory: {name}")
    if not profile_root.is_dir():
        raise ProfileError(f"profile not found: {name}")
    return profile_root


def _read_text_context(path: Path, profile_root: Path) -> TextContext:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace").strip()
    relative_path = path.relative_to(profile_root).as_posix()
    return TextContext(relative_path=relative_path, text=text)


def load_profile_bundle(
    profiles_dir: Path,
    profile_name: object,
) -> ProfileBundle:
    profile_root = _profile_path(profiles_dir, profile_name)
    text_contexts: list[TextContext] = []
    image_paths: list[Path] = []

    for path in sorted(profile_root.rglob("*"), key=lambda item: item.as_posix()):
        rel = path.relative_to(profile_root)
        if _is_hidden(rel) or not path.is_file():
            continue

        suffix = path.suffix.lower()
        if suffix in SUPPORTED_TEXT_SUFFIXES:
            text_contexts.append(_read_text_context(path, profile_root))
        elif suffix in SUPPORTED_IMAGE_SUFFIXES:
            image_paths.append(path.resolve())

    return ProfileBundle(
        name=profile_root.name,
        root=profile_root,
        text_contexts=tuple(text_contexts),
        image_paths=tuple(image_paths),
    )
