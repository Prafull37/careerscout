#!/usr/bin/env python3
"""
Build sharded slug lists for the ATS prober.

Downloads the same public datasets used by cmd/probe_ats buildSlugs()
(S&P 500, Fortune 500, Majestic Million), cleans them into company slugs,
dedupes, and writes N shard files: shards/slugs_shard_<i>.json

Usage:
  python3 scripts/build_slug_shards.py --shards 10 --per-shard 20000 --out-dir shards
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request

SOURCES = [
    # (url, kind)
    ("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv", "sp500"),
    ("https://raw.githubusercontent.com/namelist/fortune500/master/fortune500.csv", "fortune500"),
    ("https://downloads.majestic.com/majestic_million.csv", "majestic"),
]

SKIP_EXACT = {
    "google", "facebook", "youtube", "youtu", "instagram", "twitter", "linkedin",
    "tiktok", "whatsapp", "snapchat", "pinterest", "reddit", "netflix", "spotify",
    "apple", "microsoft", "amazon", "adobe", "mozilla", "apache",
    "www", "mail", "api", "app", "apps", "play", "maps", "docs", "drive",
    "support", "help", "blog", "shop", "store", "news", "forum", "static",
    "cdn", "media", "images", "player", "plus", "go", "goo", "bit", "my",
    "the", "web", "site", "online",
    "amazonaws", "cloudfront", "akamai", "fastly", "cloudflare",
    "googletagmanager", "doubleclick", "googleapis", "gstatic", "fbcdn",
    "jsdelivr", "unpkg", "cdnjs", "nginx",
    "policies", "europa", "mailinabox", "vimeo",
    "xn", "free", "best", "top", "wikipedia", "wordpress", "blogspot",
    "tumblr", "github", "yahoo", "itunes", "gravatar",
    "jobvite", "breezyhr", "personio", "smartrecruiters",
}

SUFFIXES = [" inc", " corp", " ltd", " llc", " co", " group", " holdings",
            " company", " limited"]
RE_SPACES = re.compile(r"[\s_]+")
RE_SPEC = re.compile(r"[^a-z0-9\-]")
RE_VALID = re.compile(r"^[a-z][a-z0-9\-]{1,62}$")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "careerscout-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", errors="replace")


def clean_slug(name: str) -> str:
    name = name.lower().strip()
    for suf in SUFFIXES:
        while True:
            trimmed = name
            for variant in (suf, suf + ".", suf + ","):
                if name.endswith(variant):
                    name = name[: -len(variant)].rstrip()
            if name == trimmed:
                break
    name = RE_SPACES.sub("-", name)
    name = RE_SPEC.sub("", name)
    return name.strip("-")


def is_valid(slug: str) -> bool:
    if slug in SKIP_EXACT:
        return False
    if slug.isdigit():
        return False
    return bool(RE_VALID.match(slug))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=10)
    ap.add_argument("--per-shard", type=int, default=20000)
    ap.add_argument("--out-dir", default="shards")
    args = ap.parse_args()

    slugs: dict[str, int] = {}
    counts: dict[str, int] = {}

    for url, kind in SOURCES:
        print(f"fetching {kind}: {url}", file=sys.stderr)
        try:
            body = fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: failed to fetch {url}: {e}", file=sys.stderr)
            continue
        n0 = len(slugs)
        reader = csv.reader(io.StringIO(body))
        for i, row in enumerate(reader):
            line = ",".join(row)
            if len(line.strip()) < 4:
                continue
            if kind == "majestic":
                if i == 0:
                    continue
                if len(row) > 3:
                    domain, tld = row[2].strip(), row[3].strip()
                    if tld.endswith(("gov", "edu", "mil")):
                        continue
                    slug = domain.split(".")[0].lower()
                    if is_valid(slug):
                        slugs.setdefault(slug, len(slugs))
            else:
                for field in row:
                    slug = clean_slug(field)
                    if is_valid(slug):
                        slugs.setdefault(slug, len(slugs))
                    if "-" in slug:
                        v1 = slug.replace("-", "")
                        if is_valid(v1):
                            slugs.setdefault(v1, len(slugs))
        counts[kind] = len(slugs) - n0
        print(f"{kind}: +{counts[kind]} new slugs", file=sys.stderr)

    ordered = sorted(slugs.keys())
    print(f"total unique slugs: {len(ordered)}", file=sys.stderr)

    os.makedirs(args.out_dir, exist_ok=True)
    per = args.per_shard
    shard_count = 0
    for i in range(0, len(ordered), per):
        chunk = ordered[i : i + per]
        path = os.path.join(args.out_dir, f"slugs_shard_{shard_count}.json")
        with open(path, "w") as f:
            json.dump(chunk, f)
        print(f"wrote {path} ({len(chunk)} slugs)", file=sys.stderr)
        shard_count += 1
    print(f"DONE {shard_count}")


if __name__ == "__main__":
    main()
