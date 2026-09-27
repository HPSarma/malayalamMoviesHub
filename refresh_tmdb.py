#!/usr/bin/env python3
"""Refresh and extend data.js from TMDB (+ optional OMDb for IMDb ratings).

Stdlib only. Usage:
    TMDB_API_KEY=xxx [OMDB_API_KEY=yyy] python3 scripts/refresh_tmdb.py [--min-votes 25] [--pages 15] [--dry-run]

- Discovers Malayalam-language films released 2015-01-01 onward on TMDB.
- Existing rows keep their curated cast/genres; only the rating is updated.
- New films are appended with top-billed actors/actresses and director.
- Rating = IMDb rating via OMDb when OMDB_API_KEY is set, else TMDB vote_average.
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data.js"
TMDB = "https://api.themoviedb.org/3"
GENRE_MAP = {
    "Science Fiction": "Sci-Fi", "Adventure": "Action", "Music": "Drama", "History": "Drama",
    "War": "Action", "Animation": "Family", "Documentary": "Drama", "TV Movie": "Drama", "Western": "Action",
}


def get(url, params):
    q = urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{url}?{q}", timeout=20) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - retry on any transient error
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))


def norm(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def load_rows():
    rows = []
    for line in DATA.read_text().splitlines():
        s = line.strip()
        if s.startswith('["'):
            rows.append(json.loads(s.rstrip(",")))
    return rows


def write_rows(rows):
    rows.sort(key=lambda r: (r[1], -r[2], r[0]))
    out = [
        "// Malayalam films, 2015 onward.",
        "// Row: [title, year, rating, genres, actors, actresses, director]",
        '// Multi-value fields are "|" separated. Ratings are approximate IMDb user',
        "// ratings (snapshot) — run scripts/refresh_tmdb.py to refresh / extend.",
        "window.MOVIE_ROWS = [",
    ]
    year = None
    for r in rows:
        if r[1] != year:
            if year is not None:
                out.append("")
            year = r[1]
            out.append(f"  // {year}")
        out.append("  " + json.dumps(r, ensure_ascii=False) + ",")
    out.append("];")
    DATA.write_text("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-votes", type=int, default=25, help="TMDB vote_count floor for new films")
    ap.add_argument("--pages", type=int, default=15)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("TMDB_API_KEY")
    if not key:
        sys.exit("Set TMDB_API_KEY (free at https://www.themoviedb.org/settings/api)")
    omdb = os.environ.get("OMDB_API_KEY")

    rows = load_rows()
    index = {(norm(r[0]), r[1]): r for r in rows}
    added = updated = 0

    for page in range(1, args.pages + 1):
        res = get(f"{TMDB}/discover/movie", {
            "api_key": key, "with_original_language": "ml", "primary_release_date.gte": "2015-01-01",
            "sort_by": "vote_count.desc", "vote_count.gte": args.min_votes, "page": page,
        })
        for m in res.get("results", []):
            if not m.get("release_date"):
                continue
            year = int(m["release_date"][:4])
            d = get(f"{TMDB}/movie/{m['id']}", {"api_key": key, "append_to_response": "credits,external_ids"})
            rating = round(d.get("vote_average") or 0, 1)
            imdb_id = (d.get("external_ids") or {}).get("imdb_id")
            if omdb and imdb_id:
                o = get("https://www.omdbapi.com/", {"apikey": omdb, "i": imdb_id})
                if o.get("imdbRating", "N/A") != "N/A":
                    rating = float(o["imdbRating"])
            if not rating:
                continue

            existing = index.get((norm(d["title"]), year)) or index.get((norm(d.get("original_title", "")), year))
            if existing:
                if existing[2] != rating:
                    existing[2] = rating
                    updated += 1
                continue

            cast = sorted(d["credits"]["cast"], key=lambda c: c["order"])[:10]
            actors = [c["name"] for c in cast if c.get("gender") == 2][:3]
            actresses = [c["name"] for c in cast if c.get("gender") == 1][:2]
            director = next((c["name"] for c in d["credits"]["crew"] if c["job"] == "Director"), "")
            genres = []
            for g in d.get("genres", []):
                name = GENRE_MAP.get(g["name"], g["name"])
                if name not in genres:
                    genres.append(name)
            row = [d["title"], year, rating, "|".join(genres[:2]) or "Drama",
                   "|".join(actors), "|".join(actresses), director]
            rows.append(row)
            index[(norm(row[0]), year)] = row
            added += 1
            print(f"+ {row[0]} ({year}) {rating}")
        if page >= res.get("total_pages", 0):
            break

    print(f"\n{added} added, {updated} ratings updated, {len(rows)} total")
    if not args.dry_run:
        write_rows(rows)
        print(f"Wrote {DATA}")


if __name__ == "__main__":
    main()
