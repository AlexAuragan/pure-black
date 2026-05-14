from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from loguru import logger

SUBSTITUTIONS: dict[str, str] = {
    "code-url-handler": "visual-studio-code",
    "Code": "visual-studio-code",
    "gnome-tweaks": "org.gnome.tweaks",
    "pavucontrol-qt": "pavucontrol",
    "wps": "wps-office2019-kprometheus",
    "wpsoffice": "wps-office2019-kprometheus",
    "footclient": "foot",
    "zen": "zen-browser",
    "brave-browser": "brave-desktop",
}

REGEX_SUBSTITUTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^steam_app_(\d+)$"), r"steam_icon_\1"),
    (re.compile(r"Minecraft.*"), "minecraft"),
    (re.compile(r".*polkit.*"), "system-lock-screen"),
    (re.compile(r"gcr\.prompter"), "system-lock-screen"),
]


@dataclass(frozen=True)
class DesktopEntry:
    name: str
    icon: str
    exec: str
    startup_wm_class: str | None
    filename: str  # foo.desktop


def _xdg_data_dirs() -> list[Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    return [data_home] + [Path(p) for p in data_dirs if p]


def _desktop_entry_dirs() -> list[Path]:
    return [d / "applications" for d in _xdg_data_dirs()]


def _icon_dirs() -> list[Path]:
    out: list[Path] = []
    for d in _xdg_data_dirs():
        out.append(d / "icons")
    out.append(Path.home() / ".icons")
    out.append(Path("/usr/share/pixmaps"))
    out.append(Path("/var/lib/flatpak/exports/share/icons"))
    out.append(Path.home() / ".local/share/flatpak/exports/share/icons")

    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


_desktop_entries_cache: list[DesktopEntry] | None = None


def _read_desktop_entries() -> list[DesktopEntry]:
    global _desktop_entries_cache
    if _desktop_entries_cache is not None:
        return _desktop_entries_cache

    entries: list[DesktopEntry] = []
    for d in _desktop_entry_dirs():
        if not d.exists():
            continue
        for f in d.glob("*.desktop"):
            cp = configparser.ConfigParser(interpolation=None)
            try:
                cp.read(f, encoding="utf-8")
            except Exception:
                continue
            if "Desktop Entry" not in cp:
                continue
            de = cp["Desktop Entry"]
            if de.get("NoDisplay", "").lower() == "true":
                continue

            name = (de.get("Name") or "").strip()
            icon = (de.get("Icon") or "").strip()
            exec_ = (de.get("Exec") or "").strip()
            if not name:
                continue

            entries.append(
                DesktopEntry(
                    name=name,
                    icon=icon,
                    exec=exec_,
                    startup_wm_class=(de.get("StartupWMClass") or None),
                    filename=f.name,
                )
            )
    _desktop_entries_cache = entries
    return entries


def _resolve_icon_path(icon_name_or_path: str) -> str | None:
    if not icon_name_or_path:
        return None

    p = Path(icon_name_or_path)
    if p.is_file():
        return str(p)

    icon = icon_name_or_path
    exts = [".svg", ".png", ".xpm"]

    for d in _icon_dirs():
        if not d.exists():
            continue

        # direct in dir (also covers /usr/share/pixmaps)
        for ext in exts:
            cand = d / f"{icon}{ext}"
            if cand.is_file():
                return str(cand)

        # themes
        if d.is_dir():
            for theme in d.iterdir():
                if not theme.is_dir():
                    continue
                for ext in exts:
                    cand = theme / "scalable" / "apps" / f"{icon}{ext}"
                    if cand.is_file():
                        return str(cand)
                for size in (16, 22, 24, 32, 48, 64, 96, 128, 256):
                    for ext in exts:
                        cand = theme / f"{size}x{size}" / "apps" / f"{icon}{ext}"
                        if cand.is_file():
                            return str(cand)

    return None


def _apply_substitutions(s: str) -> str:
    if s in SUBSTITUTIONS:
        return SUBSTITUTIONS[s]
    low = s.lower()
    if low in SUBSTITUTIONS:
        return SUBSTITUTIONS[low]
    for rx, repl in REGEX_SUBSTITUTIONS:
        replaced = rx.sub(repl, s)
        if replaced != s:
            return replaced
    return s


def _kebab_normalize(s: str) -> str:
    return re.sub(r"\s+", "-", s.strip().lower())


def _tokens(s: str) -> set[str]:
    # useful for exec/name matching
    parts = re.split(r"[^A-Za-z0-9._+-]+", s.lower())
    return {p for p in parts if p}


def _score(a: str, b: str) -> float:
    return SequenceMatcher(a=a.lower(), b=b.lower()).ratio()


def find_desktop_entry_for_window_class(window_class: str) -> DesktopEntry | None:
    """
    Desktop-first matching:
    1) StartupWMClass exact (case-insensitive)
    2) desktop filename contains class (kebab/low)
    3) Exec contains class tokens
    4) Name contains class tokens
    5) optional fuzzy with threshold (guarded)
    """
    s = window_class.strip()
    if not s:
        return None

    s2 = _apply_substitutions(s)
    low = s2.lower()
    kebab = _kebab_normalize(s2)
    toks = _tokens(s2) | _tokens(kebab) | _tokens(low)

    entries = _read_desktop_entries()

    # 1) StartupWMClass exact
    for e in entries:
        if e.startup_wm_class and e.startup_wm_class.lower() == low:
            return e

    # 2) desktop filename heuristic
    # e.g. "pycharm.desktop" matching "jetbrains-pycharm"
    for e in entries:
        fn = e.filename.lower()
        if low in fn or kebab in fn:
            return e

    # 3) Exec token containment
    best: DesktopEntry | None = None
    best_hits = 0
    for e in entries:
        exec_toks = _tokens(e.exec)
        hits = len(toks & exec_toks)
        if hits > best_hits:
            best_hits = hits
            best = e
    if best and best_hits >= 2:
        return best

    # 4) Name token containment
    best = None
    best_hits = 0
    for e in entries:
        name_toks = _tokens(e.name)
        hits = len(toks & name_toks)
        if hits > best_hits:
            best_hits = hits
            best = e
    if best and best_hits >= 1:
        return best

    # 5) Guarded fuzzy (optional, last resort)
    # This is where your RetroArch mismatch came from: no threshold.
    FUZZY_THRESHOLD = 0.55
    best = None
    best_sc = 0.0
    for e in entries:
        # Prefer matching against StartupWMClass, filename, exec, and name
        candidates = [
            e.startup_wm_class or "",
            e.filename[:-8],  # strip ".desktop"
            e.exec,
            e.name,
            e.icon,
        ]
        sc = max(_score(s2, c) for c in candidates if c)
        if sc > best_sc:
            best_sc = sc
            best = e
    if best and best_sc >= FUZZY_THRESHOLD:
        return best

    return None


def guess_icon_path_from_window_class(window_class: str | None) -> str | None:
    if not window_class:
        return None

    # First: try direct icon-name resolution with the same guesses (fast)
    s = _apply_substitutions(window_class.strip())
    for cand in (
        s,
        s.lower(),
        _kebab_normalize(s),
        s.split(".")[-1],
        s.split(".")[-1].lower(),
    ):
        p = _resolve_icon_path(cand)
        if p:
            return p

    # Then: desktop-first (what you asked for)
    entry = find_desktop_entry_for_window_class(window_class)
    if entry:
        p = _resolve_icon_path(entry.icon)
        if p:
            return p
        logger.warning(f"[Icon] Couldn't find an icon for {entry}")
    else:
        logger.warning(f"[Icon] No descktop entry for {window_class!r}")
    return None


def guess_icon_name_from_window_class(window_class: str | None) -> str | None:
    p = guess_icon_path_from_window_class(window_class)
    if not p:
        return None
    return Path(p).stem
