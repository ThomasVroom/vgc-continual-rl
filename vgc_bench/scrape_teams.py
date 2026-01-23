"""
Team scraping module for VGC-Bench.

Scrapes competitive VGC team data from the VGCPastes Google Sheets database.
Downloads team compositions from in-person tournament results and saves them
as Pokepaste-format text files organized by regulation and event.
"""

import argparse
import csv
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests
from poke_env.teambuilder import Teambuilder
from src.teams import calc_team_similarity_score

SHEET_ID = "1axlwmzPA49rYkqXh7zHvAtSP-TKbM0ijGYBPRflLSWw"
SHEET_EDIT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
SHEET_GVIZ_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"


def slugify(text: str) -> str:
    """
    Convert text to a URL/filename-safe slug.

    Args:
        text: Input text to slugify.

    Returns:
        Lowercase ASCII string with non-alphanumeric chars replaced by underscores.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def normalize_event_name(event_name: str) -> str:
    """
    Normalize an event name by removing common suffixes.

    Args:
        event_name: Raw event name string.

    Returns:
        Cleaned event name with "Regional Championships" etc. removed.
    """
    name = event_name.strip()
    name = re.sub(r"\bregional\s+championships?\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\bregionals?\b", "", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip()


def placement_to_filename(placement: str) -> str:
    """
    Convert a tournament placement to a filename-friendly string.

    Args:
        placement: Raw placement string (e.g., "Champion", "Runner-up").

    Returns:
        Normalized filename (e.g., "1st", "2nd").
    """
    normalized = slugify(placement.strip())
    if normalized in {"champion", "winner"}:
        return "1st"
    if normalized in {"runner_up"}:
        return "2nd"
    return normalized or "unknown_placement"


def parse_event_date(date_str: str) -> datetime | None:
    """
    Parse a date string from various formats.

    Args:
        date_str: Date string in various formats (e.g., "15 Jan 2024").

    Returns:
        Parsed datetime object, or None if parsing fails.
    """
    date_str = date_str.strip().replace("Sept", "Sep")
    if not date_str:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y", "%d %b, %Y", "%d %B, %Y", "%b %Y", "%B %Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b", date_str)
    if m is not None:
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(m.group(1), fmt)
            except ValueError:
                pass


def event_dir_name(event_name: str, date_str: str) -> str:
    """
    Generate a directory name for an event.

    Args:
        event_name: Name of the tournament event.
        date_str: Date string for the event.

    Returns:
        Slugified directory name including year from event name, or date as fallback.
    """
    normalized_name = re.sub(r"\b\d{4}\b", "", normalize_event_name(event_name)).strip()
    base = (
        slugify(normalized_name) or slugify(normalize_event_name(event_name)) or "event"
    )
    # Prefer year from event name, fall back to date
    year_match = re.search(r"\b(20\d{2})\b", event_name)
    if year_match:
        return f"{base}_{year_match.group(1)}"
    dt = parse_event_date(date_str)
    if dt:
        return f"{base}_{dt.year}"
    return base


def event_key(event_name: str, date_str: str) -> str:
    """
    Generate a unique key for an event (used for deduplication).

    Args:
        event_name: Name of the tournament event.
        date_str: Date string for the event.

    Returns:
        Slugified key string including year from event name, or date as fallback.
    """
    normalized_name = re.sub(r"\b\d{4}\b", "", normalize_event_name(event_name)).strip()
    base = (
        slugify(normalized_name) or slugify(normalize_event_name(event_name)) or "event"
    )
    # Prefer year from event name, fall back to date
    year_match = re.search(r"\b(20\d{2})\b", event_name)
    if year_match:
        return f"{base}_{year_match.group(1)}"
    dt = parse_event_date(date_str)
    if dt:
        return f"{base}_{dt.year}"
    return base


def fetch_sheet_names(
    session: requests.Session, max_bytes: int = 2_000_000
) -> list[str]:
    """
    Fetch the list of sheet names from the VGCPastes spreadsheet.

    Args:
        session: Requests session for HTTP calls.
        max_bytes: Maximum bytes to download from the sheet HTML.

    Returns:
        List of unique sheet names in the spreadsheet.
    """
    headers = {"Range": f"bytes=0-{max_bytes}"}
    resp = session.get(SHEET_EDIT_URL, headers=headers, stream=True, timeout=30)
    resp.raise_for_status()
    chunks: list[bytes] = []
    read_bytes = 0
    for chunk in resp.iter_content(chunk_size=64 * 1024):
        if not chunk:
            break
        remaining = max_bytes - read_bytes
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        chunks.append(chunk)
        read_bytes += len(chunk)
        if read_bytes >= max_bytes:
            break
    html = b"".join(chunks).decode("utf-8", errors="ignore")
    names = re.findall(r"docs-sheet-tab-caption\">([^<]+)<", html)
    seen: set[str] = set()
    unique_names: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique_names.append(name)
    return unique_names


def featured_team_sheets_for_regulation(
    all_sheet_names: list[str], regulation: str
) -> list[str]:
    """
    Find sheet names containing featured teams for a specific regulation.

    Args:
        all_sheet_names: List of all sheet names in the spreadsheet.
        regulation: Regulation letter (e.g., "G").

    Returns:
        List of matching sheet names for featured teams.
    """
    reg = regulation.strip().lower()
    sheets = []
    for name in all_sheet_names:
        lname = name.lower()
        if "featured" not in lname:
            continue
        if "presentable" in lname:
            continue
        if f"reg {reg}" in lname or f"regulation {reg}" in lname:
            sheets.append(name)
    if not sheets:
        sheets = [f"Reg {regulation.upper()} Featured Teams"]
    return sheets


def fetch_sheet_csv_rows(session: requests.Session, sheet_name: str) -> list[list[str]]:
    """
    Fetch and parse a sheet's data as CSV rows.

    Args:
        session: Requests session for HTTP calls.
        sheet_name: Name of the sheet to fetch.

    Returns:
        List of rows, where each row is a list of cell values.
    """
    url = f"{SHEET_GVIZ_URL}?tqx=out:csv&sheet={quote_plus(sheet_name)}"
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    return list(csv.reader(resp.text.splitlines()))


def fetch_pokepaste_raw(session: requests.Session, pokepaste_url: str) -> str:
    """
    Fetch raw team text from a Pokepaste URL.

    Args:
        session: Requests session for HTTP calls.
        pokepaste_url: URL to a pokepast.es page.

    Returns:
        Normalized team text in Showdown format.
    """
    paste_id = pokepaste_url.rstrip("/").split("/")[-1]
    raw_url = f"https://pokepast.es/{paste_id}/raw"
    resp = session.get(raw_url, timeout=30)
    resp.raise_for_status()
    return normalize_team_text(resp.text)


def has_banned_move_or_ability(team_text: str) -> bool:
    """
    Check if a team contains abilities that would break log parsing.

    Args:
        team_text: Team text in Showdown format.

    Returns:
        True if team has Illusion or Commander ability.
    """
    if re.search(
        r"^\s*Ability:\s*Illusion\s*$", team_text, flags=re.IGNORECASE | re.MULTILINE
    ):
        return True
    if re.search(
        r"^\s*Ability:\s*Commander\s*$", team_text, flags=re.IGNORECASE | re.MULTILINE
    ):
        return True
    return False


def normalize_team_text(team_text: str) -> str:
    """
    Normalize team text formatting and fix known issues.

    Handles "As One" ability disambiguation for Calyrex forms and
    cleans up whitespace formatting.

    Args:
        team_text: Raw team text from Pokepaste.

    Returns:
        Normalized team text.
    """
    lines = [line.rstrip() for line in team_text.splitlines()]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    blocks: list[list[str]] = []
    block: list[str] = []
    for line in lines:
        if line == "":
            if block:
                blocks.append(block)
                block = []
            continue
        block.append(line)
    if block:
        blocks.append(block)
    normalized_blocks: list[str] = []
    for block in blocks:
        header = block[0]
        asone = (
            "As One (Glastrier)"
            if re.search(r"\bCalyrex-Ice\b", header, flags=re.IGNORECASE)
            else "As One (Spectrier)"
        )
        new_lines: list[str] = []
        for line in block:
            m = re.match(r"^(\s*Ability:\s*)(.*?)\s*$", line, flags=re.IGNORECASE)
            if m is not None:
                ability_value = m.group(2)
                ability_norm = re.sub(r"[^a-z0-9]", "", ability_value.lower())
                if ability_norm == "asone":
                    line = f"{m.group(1)}{asone}"
            new_lines.append(line)
        normalized_blocks.append("\n".join(new_lines))
    return "\n\n".join(normalized_blocks) + "\n"


def scrape_regulation(regulation: str) -> None:
    """
    Scrape all featured teams for a specific VGC regulation.

    Downloads teams from in-person events, filters duplicates and banned
    abilities, and saves them organized by event subdirectories.

    Args:
        regulation: Single letter regulation code (e.g., "G").
    """
    reg_dir = Path("data") / "teams" / f"reg{regulation.lower()}"
    reg_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    all_sheet_names = fetch_sheet_names(session)
    sheet_names = featured_team_sheets_for_regulation(all_sheet_names, regulation)
    seen_teams: list[str] = []
    saved = 0
    skipped_duplicates = 0
    skipped_banned = 0
    skipped_existing = 0
    event_subdirs: dict[str, Path] = {}
    for sheet_name in sheet_names:
        rows = fetch_sheet_csv_rows(session, sheet_name)
        header_row_idx = next(
            i
            for i, r in enumerate(rows)
            if r and r[0].strip() == "Team ID" and "Pokepaste" in r
        )
        header = rows[header_row_idx]
        category_idx = header.index("Category")
        evs_idx = header.index("EVs")
        pokepaste_idx = header.index("Pokepaste")
        event_idx = header.index("Tournament / Event")
        rank_idx = header.index("Rank")
        date_idx = header.index("Date") if "Date" in header else event_idx - 1
        for row in rows[header_row_idx + 1 :]:
            if len(row) <= max(
                category_idx, evs_idx, pokepaste_idx, event_idx, rank_idx, date_idx
            ):
                continue
            category = row[category_idx].strip().lower()
            if category != "in person event":
                continue
            if row[evs_idx].strip().lower() != "yes":
                continue
            pokepaste = row[pokepaste_idx].strip()
            if not pokepaste.startswith("https://pokepast.es/"):
                continue
            team_text = fetch_pokepaste_raw(session, pokepaste)
            if has_banned_move_or_ability(team_text):
                skipped_banned += 1
                continue
            try:
                Teambuilder.parse_showdown_team(team_text)
            except KeyError:
                continue
            if any(
                calc_team_similarity_score(team_text, prev) == 1.0
                for prev in seen_teams
            ):
                skipped_duplicates += 1
                continue
            seen_teams.append(team_text)
            event_name = row[event_idx].strip()
            event_lower = event_name.lower()
            allowed_events = ("regional", "euic", "laic", "naic", "worlds")
            if not any(kw in event_lower for kw in allowed_events):
                continue
            if "seniors" in event_lower or "juniors" in event_lower:
                continue
            if "&" in event_name:
                continue
            date_str = row[date_idx].strip()
            placement = row[rank_idx].strip()
            if "juniors" in placement or "seniors" in placement:
                continue
            key = event_key(event_name, date_str)
            if key not in event_subdirs:
                event_subdirs[key] = reg_dir / event_dir_name(event_name, date_str)
            event_subdir = event_subdirs[key]
            event_subdir.mkdir(parents=True, exist_ok=True)
            base_filename = placement_to_filename(placement)
            if not base_filename[0].isdigit():
                continue
            filename = f"{base_filename}.txt"
            out_path = event_subdir / filename
            if out_path.exists():
                skipped_existing += 1
                continue
            with open(out_path, "w") as f:
                f.write(team_text)
            saved += 1
    print(f"Saved {saved} teams to {reg_dir}")
    print(f"Skipped {skipped_existing} already existing files")
    print(f"Skipped {skipped_banned} teams with Illusion/Commander")
    print(f"Skipped {skipped_duplicates} duplicate teams")


def main():
    """Main entry point for the team scraping command-line tool."""
    parser = argparse.ArgumentParser(
        description="Scrape VGCPastes Featured Teams into data/teams/ subdirectories"
    )
    parser.add_argument(
        "--reg",
        "-r",
        type=str,
        required=True,
        help="Regulation letter to scrape (e.g. G for Regulation G)",
    )
    args = parser.parse_args()
    reg = args.reg.strip().upper()
    if len(reg) != 1 or not reg.isalpha():
        raise ValueError("--regulation must be a single letter like G")
    scrape_regulation(reg)


if __name__ == "__main__":
    if not os.path.exists("data"):
        os.mkdir("data")
    main()
