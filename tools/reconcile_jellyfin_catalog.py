#!/usr/bin/env python3
"""Reconcile Jellyfin paths and selected metadata after media renames.

Run only while Jellyfin is stopped. The default mode is a rollback-only dry run;
pass --apply to commit. Assertions deliberately abort on an unexpected catalog.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import uuid
from pathlib import Path


EPISODE = "MediaBrowser.Controller.Entities.TV.Episode"
SEASON = "MediaBrowser.Controller.Entities.TV.Season"
SERIES = "MediaBrowser.Controller.Entities.TV.Series"
MOVIE = "MediaBrowser.Controller.Entities.Movies.Movie"


def one(db: sqlite3.Connection, sql: str, params: tuple = ()) -> sqlite3.Row:
    rows = db.execute(sql, params).fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"expected one row, found {len(rows)}: {sql} {params}")
    return rows[0]


def set_provider(db: sqlite3.Connection, item_id: str, provider: str, value: str) -> None:
    db.execute(
        "DELETE FROM BaseItemProviders WHERE ItemId=? AND ProviderId=?",
        (item_id, provider),
    )
    db.execute(
        "INSERT INTO BaseItemProviders(ItemId, ProviderId, ProviderValue) VALUES(?,?,?)",
        (item_id, provider, value),
    )


def clone_item(
    db: sqlite3.Connection,
    template_id: str,
    new_id: str,
    changes: dict[str, object],
) -> None:
    columns = [row[1] for row in db.execute("PRAGMA table_info(BaseItems)")]
    template = one(db, "SELECT * FROM BaseItems WHERE Id=?", (template_id,))
    values = dict(zip(columns, template))
    values.update(changes)
    values["Id"] = new_id
    placeholders = ",".join("?" for _ in columns)
    db.execute(
        f"INSERT INTO BaseItems ({','.join(columns)}) VALUES ({placeholders})",
        tuple(values[column] for column in columns),
    )


def delete_item(db: sqlite3.Connection, item_id: str) -> None:
    tables = [
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if row[0] != "BaseItems"
    ]
    for table in tables:
        columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
        if "ItemId" in columns:
            db.execute(f'DELETE FROM "{table}" WHERE ItemId=?', (item_id,))
    db.execute("DELETE FROM BaseItems WHERE Id=?", (item_id,))


def replace_prefix(db: sqlite3.Connection, old: str, new: str, expected: int) -> int:
    count = one(
        db,
        "SELECT COUNT(*) FROM BaseItems WHERE Path=? OR Path LIKE ?",
        (old, old + "/%"),
    )[0]
    if count != expected:
        raise RuntimeError(f"{old}: expected {expected} items, found {count}")
    cursor = db.execute(
        "UPDATE BaseItems SET Path=? || substr(Path, ?) WHERE Path=? OR Path LIKE ?",
        (new, len(old) + 1, old, old + "/%"),
    )
    return cursor.rowcount


def canonical_episode_paths(
    db: sqlite3.Connection,
    prefix: str,
    filename_prefix: str,
    season: int,
    expected: int,
    fixed_extension: str | None = None,
) -> int:
    rows = db.execute(
        "SELECT Id,Path,IndexNumber,Name FROM BaseItems WHERE Type=? AND Path LIKE ? ORDER BY Path",
        (EPISODE, prefix + "%"),
    ).fetchall()
    if len(rows) != expected:
        raise RuntimeError(f"{prefix}: expected {expected} indexed episodes, found {len(rows)}")
    numbered_rows = []
    for item_id, old_path, catalog_number, catalog_name in rows:
        match = re.search(
            r"(?:S\d{2}E|Episódio\s*)(\d{1,3})",
            old_path + " " + catalog_name,
            re.IGNORECASE,
        )
        if not match:
            match = re.search(
                rf"(?:^|[._ -])0?{season}[._ -](\d{{1,3}})(?:[._ -]|$)",
                Path(old_path).name,
                re.IGNORECASE,
            )
        episode = catalog_number or (int(match.group(1)) if match else None)
        if episode is None:
            raise RuntimeError(f"could not determine episode number for {old_path}")
        numbered_rows.append((item_id, old_path, episode))
    if len({episode for _, _, episode in numbered_rows}) != expected:
        raise RuntimeError(f"{prefix}: episode numbers are incomplete or duplicated")
    for item_id, old_path, episode in numbered_rows:
        extension = fixed_extension or Path(old_path).suffix.lower()
        new_path = f"{prefix}{filename_prefix} - S{season:02d}E{episode:02d}{extension}"
        db.execute(
            "UPDATE BaseItems SET Path=?,IndexNumber=?,ParentIndexNumber=? WHERE Id=?",
            (new_path, episode, season, item_id),
        )
    return len(rows)


def fix_movie(
    db: sqlite3.Connection,
    item_id: str,
    name: str,
    original_title: str,
    year: int,
    path: str,
    tmdb: str,
    imdb: str | None = None,
) -> None:
    row = one(db, "SELECT Type FROM BaseItems WHERE Id=?", (item_id,))
    if row[0] != MOVIE:
        raise RuntimeError(f"{item_id} is not a movie")
    db.execute("DELETE FROM BaseItemProviders WHERE ItemId=?", (item_id,))
    db.execute(
        """UPDATE BaseItems
           SET Name=?, OriginalTitle=?, CleanName=?, SortName=?, ProductionYear=?, Path=?,
               PreferredMetadataLanguage='pt', PreferredMetadataCountryCode='BR', IsLocked=0
           WHERE Id=?""",
        (name, original_title, name.lower(), name, year, path, item_id),
    )
    set_provider(db, item_id, "Tmdb", tmdb)
    if imdb:
        set_provider(db, item_id, "Imdb", imdb)


def reconcile(db: sqlite3.Connection) -> dict[str, int]:
    changes: dict[str, int] = {}

    # Series whose folders were disambiguated with year/provider IDs.
    changes["fma_2003_tree"] = replace_prefix(
        db,
        "/media-drive/animes/Fullmetal Alchemist Clássico",
        "/media-drive/animes/Fullmetal Alchemist (2003) [tvdbid-75579]",
        52,
    )
    fma = one(db, "SELECT Id FROM BaseItems WHERE Path=?", (
        "/media-drive/animes/Fullmetal Alchemist (2003) [tvdbid-75579]",
    ))[0]
    db.execute(
        "UPDATE BaseItems SET Name='Fullmetal Alchemist', OriginalTitle='鋼の錬金術師', ProductionYear=2003, CleanName='fullmetal alchemist', SortName='Fullmetal Alchemist', PreferredMetadataLanguage='pt', PreferredMetadataCountryCode='BR' WHERE Id=?",
        (fma,),
    )
    set_provider(db, fma, "Tvdb", "75579")

    fma_season_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "archeion-stream:fma-2003:season-01")).upper()
    if not db.execute("SELECT 1 FROM BaseItems WHERE Id=?", (fma_season_id,)).fetchone():
        clone_item(
            db,
            "EDED392D-BA44-056C-897E-8DCA42EF4613",
            fma_season_id,
            {
                "Name": "Temporada 1",
                "OriginalTitle": "Season 1",
                "CleanName": "temporada 1",
                "SortName": "Temporada 1",
                "Path": "/media-drive/animes/Fullmetal Alchemist (2003) [tvdbid-75579]/Season 01",
                "ParentId": fma,
                "SeriesId": fma,
                "SeasonId": None,
                "SeriesName": "Fullmetal Alchemist",
                "ProductionYear": 2003,
                "PresentationUniqueKey": fma_season_id.replace("-", "").lower(),
                "Data": "{}",
            },
        )
        template_ancestors = db.execute(
            "SELECT ParentItemId FROM AncestorIds WHERE ItemId=?",
            ("EDED392D-BA44-056C-897E-8DCA42EF4613",),
        ).fetchall()
        db.executemany(
            "INSERT INTO AncestorIds(ItemId,ParentItemId) VALUES(?,?)",
            [(fma_season_id, row[0]) for row in template_ancestors],
        )
    fma_episodes = db.execute(
        "SELECT Id,IndexNumber,Name FROM BaseItems WHERE Type=? AND SeriesId=? ORDER BY Path",
        (EPISODE, fma),
    ).fetchall()
    if len(fma_episodes) != 51:
        raise RuntimeError(f"Fullmetal Alchemist 2003: expected 51 episodes, found {len(fma_episodes)}")
    numbered_episodes = []
    for item_id, catalog_number, catalog_name in fma_episodes:
        match = re.search(r"(?:Episódio|S01E)\s*(\d{1,2})", catalog_name, re.IGNORECASE)
        episode = catalog_number or (int(match.group(1)) if match else None)
        if episode is None:
            raise RuntimeError(f"could not determine Fullmetal episode number for {item_id}")
        numbered_episodes.append((item_id, episode))
    if sorted(episode for _, episode in numbered_episodes) != list(range(1, 52)):
        raise RuntimeError("Fullmetal Alchemist 2003 episode numbers are incomplete or duplicated")
    for item_id, episode in numbered_episodes:
        db.execute(
            "UPDATE BaseItems SET Path=?, ParentId=?, SeasonId=?, SeriesName='Fullmetal Alchemist', ProductionYear=2003, IndexNumber=?, ParentIndexNumber=1 WHERE Id=?",
            (
                f"/media-drive/animes/Fullmetal Alchemist (2003) [tvdbid-75579]/Season 01/Fullmetal Alchemist (2003) - S01E{episode:02d}.mp4",
                fma_season_id,
                fma_season_id,
                episode,
                item_id,
            ),
        )
    changes["fma_2003_episodes"] = len(fma_episodes)

    changes["jujutsu_episodes"] = canonical_episode_paths(
        db,
        "/media-drive/animes/Jujutsu Kaisen/Season 01/",
        "Jujutsu Kaisen",
        1,
        24,
        ".mkv",
    )
    changes["regular_show_s03"] = canonical_episode_paths(
        db,
        "/media-drive/series/Apenas um Show/Season 03/",
        "Apenas um Show",
        3,
        19,
    )

    changes["lupin_tree"] = replace_prefix(
        db,
        "/media-drive/series/Lupin III série animada",
        "/media-drive/series/Lupin III (1971) [tvdbid-71863]",
        5,
    )
    lupin = one(db, "SELECT Id FROM BaseItems WHERE Path=?", (
        "/media-drive/series/Lupin III (1971) [tvdbid-71863]",
    ))[0]
    db.execute(
        "UPDATE BaseItems SET Name='Lupin III', OriginalTitle='ルパン三世', ProductionYear=1971, CleanName='lupin iii', SortName='Lupin III' WHERE Id=?",
        (lupin,),
    )
    set_provider(db, lupin, "Tvdb", "71863")
    canonical_episode_paths(
        db,
        "/media-drive/series/Lupin III (1971) [tvdbid-71863]/Season 01/",
        "Lupin III (1971)",
        1,
        3,
        ".mp4",
    )

    changes["hunter_2011_tree"] = replace_prefix(
        db,
        "/media-drive/animes/Hunter X Hunter (2011)",
        "/media-drive/animes/Hunter x Hunter (2011) [tvdbid-252322]",
        62,
    )
    hunter_2011 = one(db, "SELECT Id FROM BaseItems WHERE Path=?", (
        "/media-drive/animes/Hunter x Hunter (2011) [tvdbid-252322]",
    ))[0]
    db.execute(
        "UPDATE BaseItems SET Name='Hunter x Hunter (2011)', OriginalTitle='HUNTER×HUNTER', ProductionYear=2011, CleanName='hunter x hunter 2011', SortName='Hunter x Hunter (2011)' WHERE Id=?",
        (hunter_2011,),
    )
    set_provider(db, hunter_2011, "Tvdb", "252322")

    changes["hunter_1999_tree"] = replace_prefix(
        db,
        "/media-drive/animes/HunterXHunter",
        "/media-drive/animes/Hunter x Hunter (1999) [tvdbid-79076]",
        94,
    )
    hunter_1999 = one(db, "SELECT Id FROM BaseItems WHERE Path=?", (
        "/media-drive/animes/Hunter x Hunter (1999) [tvdbid-79076]",
    ))[0]
    db.execute(
        "UPDATE BaseItems SET Name='Hunter x Hunter (1999)', OriginalTitle='HUNTER×HUNTER', ProductionYear=1999, CleanName='hunter x hunter 1999', SortName='Hunter x Hunter (1999)' WHERE Id=?",
        (hunter_1999,),
    )
    set_provider(db, hunter_1999, "Tvdb", "79076")

    fight_club = "49417928-E6E4-A699-604E-69BA7D03A5A7"
    shamballa = "19EF750F-64E1-8875-A3D8-112881DDA429"
    nausicaa = "8128D538-4E66-F572-4A33-47B8CB882D7F"
    sacred_star = "F19419D4-E929-E44C-981E-66BCCD707114"
    fix_movie(
        db, fight_club, "Clube da Luta", "Fight Club", 1999,
        "/media-drive/filmes/Clube da Luta (1999) [tmdbid-550]/Clube da Luta (1999) [tmdbid-550].mkv",
        "550", "tt0137523",
    )
    fix_movie(
        db, shamballa, "Fullmetal Alchemist: O Conquistador de Shamballa",
        "Fullmetal Alchemist the Movie: Conqueror of Shamballa", 2005,
        "/media-drive/filmes/Fullmetal Alchemist - O Conquistador de Shamballa (2005) [tmdbid-14003]/Fullmetal Alchemist - O Conquistador de Shamballa (2005) [tmdbid-14003].mkv",
        "14003",
    )
    fix_movie(
        db, sacred_star, "Fullmetal Alchemist: A Estrela Sagrada de Milos",
        "Fullmetal Alchemist: The Sacred Star of Milos", 2011,
        "/media-drive/filmes/Fullmetal Alchemist - The Sacred Star of Milos (2011) [tmdbid-80518]/Fullmetal Alchemist - The Sacred Star of Milos (2011) [tmdbid-80518].mkv",
        "80518",
    )
    fix_movie(
        db, nausicaa, "Nausicaä do Vale do Vento", "風の谷のナウシカ", 1984,
        "/media-drive/filmes/Nausicaä do Vale do Vento (1984) [tmdbid-81]/Nausicaä do Vale do Vento (1984) [tmdbid-81].mp4",
        "81", "tt0087544",
    )
    changes["movies_fixed"] = 4

    # Remove catalog entries for files deliberately moved outside all libraries.
    quarantined = db.execute(
        "SELECT Id FROM BaseItems WHERE Path LIKE '%/1XBET.COM_promo_SHREK_dinheiro_livre.mp4' OR Path LIKE '%/Como.Treinar.o.Seu.Dragão.2025.1080p.WEB-DL.DUAL.5.1.mkv'"
    ).fetchall()
    if len(quarantined) != 2:
        raise RuntimeError(f"expected 2 quarantined catalog entries, found {len(quarantined)}")
    for (item_id,) in quarantined:
        delete_item(db, item_id)
    changes["quarantined_entries_removed"] = len(quarantined)

    # Create the manual box set loaded from collection.xml, including both films.
    boxset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "archeion-stream:fullmetal-alchemist:boxset")).upper()
    if not db.execute("SELECT 1 FROM BaseItems WHERE Id=?", (boxset_id,)).fetchone():
        template_id = "CF9E8C62-C353-4256-F964-BE60CB0CC802"
        data = json.dumps(
            {
                "LinkedChildren": [
                    {"Path": "/media-drive/filmes/Fullmetal Alchemist - O Conquistador de Shamballa (2005) [tmdbid-14003]/Fullmetal Alchemist - O Conquistador de Shamballa (2005) [tmdbid-14003].mkv", "ItemId": shamballa.replace("-", "").lower()},
                    {"Path": "/media-drive/filmes/Fullmetal Alchemist - The Sacred Star of Milos (2011) [tmdbid-80518]/Fullmetal Alchemist - The Sacred Star of Milos (2011) [tmdbid-80518].mkv", "ItemId": sacred_star.replace("-", "").lower()},
                ],
                "RemoteTrailers": [],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        clone_item(
            db,
            template_id,
            boxset_id,
            {
                "Name": "Fullmetal Alchemist: Coleção",
                "OriginalTitle": "Fullmetal Alchemist Collection",
                "CleanName": "fullmetal alchemist colecao",
                "SortName": "Fullmetal Alchemist: Coleção",
                "Path": "%AppDataPath%/collections/Fullmetal Alchemist [boxset]",
                "ProductionYear": 2005,
                "PresentationUniqueKey": boxset_id.replace("-", "").lower(),
                "Data": data,
            },
        )
        for (parent_id,) in db.execute(
            "SELECT ParentItemId FROM AncestorIds WHERE ItemId=?", (template_id,)
        ):
            db.execute(
                "INSERT INTO AncestorIds(ItemId,ParentItemId) VALUES(?,?)",
                (boxset_id, parent_id),
            )
    changes["fullmetal_collection"] = 1

    # Remove the obsolete Lupin path embedded in the Ghibli manual collection.
    ghibli_id = "157E4389-3CBC-D9F3-3E25-97CEB5A4A2AE"
    data_row = one(db, "SELECT Data FROM BaseItems WHERE Id=?", (ghibli_id,))
    data = json.loads(data_row[0] or "{}")
    for child in data.get("LinkedChildren", []):
        if "Lupin III" in child.get("Path", ""):
            child["Path"] = "/media-drive/series/Lupin III (1971) [tvdbid-71863]"
            child["ItemId"] = lupin.replace("-", "").lower()
    db.execute(
        "UPDATE BaseItems SET Data=? WHERE Id=?",
        (json.dumps(data, ensure_ascii=False, separators=(",", ":")), ghibli_id),
    )
    changes["ghibli_collection_reference"] = 1

    integrity = one(db, "PRAGMA integrity_check")[0]
    if integrity != "ok":
        raise RuntimeError(f"integrity check failed: {integrity}")
    return changes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.database.is_file():
        raise SystemExit(f"database not found: {args.database}")
    db = sqlite3.connect(args.database)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("BEGIN IMMEDIATE")
    try:
        changes = reconcile(db)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    mode = "applied" if args.apply else "dry-run rolled back"
    print(mode)
    for name, count in changes.items():
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()
