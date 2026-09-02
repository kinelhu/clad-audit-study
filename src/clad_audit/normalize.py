"""Stage 2 — normalize.

Parse the cached efetch XML into one row per study: identifiers, year/era, journal, pubtypes,
abstract, and the metadata-only fields the codebook's reporting-habit sensitivity needs
(senior author, senior affiliation, country, multicenter/registry flag). Dedup by PMID.

    uv run python -m clad_audit.normalize

Writes data/corpus.csv (+ .parquet). Full-text acquisition and outcome-role tagging are later stages.
"""

from __future__ import annotations

import re

import pandas as pd
from lxml import etree

from .config import (
    CONSENSUS_YEAR,
    CORPUS_CSV,
    CORPUS_PARQUET,
    EXCLUDE_PUBTYPES,
    RAW_DIR,
    REGISTRY_KEYWORDS,
    registry_named,
)

# Country detection over free-text affiliation strings. Coarse by design (grouping var, not
# a parsed institution). Order matters: check multi-word / disambiguating names first.
_COUNTRIES = [
    ("United States", ["usa", "u.s.a", "united states", "u.s.", " ny ", " ca ", " tx ", " ma "]),
    ("United Kingdom", ["united kingdom", "u.k.", " uk ", "england", "scotland", "wales", "london"]),
    ("Canada", ["canada"]),
    ("France", ["france", "french"]),
    ("Germany", ["germany", "deutschland"]),
    ("Italy", ["italy", "italia"]),
    ("Spain", ["spain", "españa", "espana"]),
    ("Netherlands", ["netherlands", "the netherlands"]),
    ("Belgium", ["belgium", "leuven"]),
    ("Austria", ["austria", "vienna", "wien"]),
    ("Switzerland", ["switzerland"]),
    ("Sweden", ["sweden"]),
    ("Denmark", ["denmark"]),
    ("Norway", ["norway"]),
    ("Australia", ["australia"]),
    ("Japan", ["japan"]),
    ("China", ["china", "p.r. china", "prc"]),
    ("South Korea", ["korea"]),
    ("Brazil", ["brazil", "brasil"]),
    ("Israel", ["israel"]),
    ("Poland", ["poland"]),
    ("Turkey", ["turkey", "türkiye"]),
    ("India", ["india"]),
]

_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _txt(node) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def _first_year(article) -> int | None:
    for path in (
        ".//Article/Journal/JournalIssue/PubDate/Year",
        ".//Article/ArticleDate/Year",
        ".//PubmedData/History/PubMedPubDate[@PubStatus='pubmed']/Year",
    ):
        el = article.find(path)
        if el is not None and el.text and el.text.isdigit():
            return int(el.text)
    # MedlineDate fallback ("2019 Jan-Feb")
    md = article.find(".//Article/Journal/JournalIssue/PubDate/MedlineDate")
    if md is not None and md.text:
        m = _YEAR_RE.search(md.text)
        if m:
            return int(m.group(0))
    return None


def _country(aff: str) -> str:
    low = f" {aff.lower()} "
    for name, needles in _COUNTRIES:
        if any(n in low for n in needles):
            return name
    return ""


def _authors(article) -> tuple[str, str, list[str]]:
    """Return (senior_author, senior_affiliation, all_affiliations)."""
    authors = article.findall(".//Article/AuthorList/Author")
    affils: list[str] = []
    for a in authors:
        for af in a.findall(".//AffiliationInfo/Affiliation"):
            if af.text:
                affils.append(af.text.strip())
    senior_name, senior_aff = "", ""
    if authors:
        last = authors[-1]
        ln = _txt(last.find("LastName"))
        ini = _txt(last.find("Initials"))
        senior_name = f"{ln} {ini}".strip()
        af = last.find(".//AffiliationInfo/Affiliation")
        senior_aff = af.text.strip() if af is not None and af.text else ""
    return senior_name, senior_aff, affils


def _is_multicenter(title: str, abstract: str, affils: list[str], countries: set[str]) -> bool:
    # Conservative: registry/collaborative keyword OR >1 country. Deliberately does NOT use
    # affiliation-string count (a single-center paper with many co-authors trips it → 50% false
    # positives). Under-flags domestic multicenter studies, acceptable for a sensitivity grouping.
    hay = f"{title} {abstract} {' '.join(affils)}".lower()
    if any(k in hay for k in REGISTRY_KEYWORDS):
        return True
    return len(countries) > 1


def _records():
    for path in sorted(RAW_DIR.glob("efetch_*.xml")):
        tree = etree.parse(str(path))
        for art in tree.findall(".//PubmedArticle"):
            pmid = _txt(art.find(".//MedlineCitation/PMID"))
            doi = ""
            for aid in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
                if aid.get("IdType") == "doi" and aid.text:
                    doi = aid.text.strip().lower()
                    break
            title = _txt(art.find(".//Article/ArticleTitle"))
            abstract = " ".join(
                _txt(a) for a in art.findall(".//Article/Abstract/AbstractText")
            ).strip()
            journal = _txt(art.find(".//Article/Journal/Title"))
            pubtypes = [
                _txt(p) for p in art.findall(".//Article/PublicationTypeList/PublicationType")
            ]
            # authoritative-ish design hint from metadata (RCT pubtype; named-registry regex)
            _hay = f"{title} {abstract}".lower()
            if "Randomized Controlled Trial" in pubtypes:
                design_meta = "rct"
            elif registry_named(_hay):
                design_meta = "registry"
            else:
                design_meta = ""
            year = _first_year(art)
            senior_name, senior_aff, affils = _authors(art)
            countries = {c for c in (_country(a) for a in affils) if c}
            senior_country = _country(senior_aff) or (sorted(countries)[0] if countries else "")

            yield {
                "pmid": pmid,
                "doi": doi,
                "year": year,
                "era": ("post" if year and year >= CONSENSUS_YEAR else "pre" if year else ""),
                "journal": journal,
                "pubtypes": "; ".join(pubtypes),
                "title": title,
                "abstract": abstract,
                "senior_author": senior_name,
                "senior_affiliation": senior_aff,
                "country": senior_country,
                "n_countries": len(countries),
                "is_multicenter_or_registry": _is_multicenter(title, abstract, affils, countries),
                "design_meta": design_meta,
                "group_key": f"{senior_name}|{senior_country}".lower() if senior_name else "",
            }


def main() -> None:
    rows = list(_records())
    df = pd.DataFrame(rows)
    before = len(df)
    # drop non-original pubtypes that slip through co-tagged as "Journal Article"
    pt_excl = df["pubtypes"].fillna("").apply(
        lambda s: any(x in EXCLUDE_PUBTYPES for x in (p.strip() for p in s.split(";")))
    )
    n_pt = int(pt_excl.sum())
    df = df[~pt_excl]
    df = df.drop_duplicates(subset="pmid").reset_index(drop=True)
    print(f"dropped {n_pt} non-original pubtypes (protocols/preprints/JoVE/errata/etc.)")
    CORPUS_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CORPUS_CSV, index=False)
    try:
        df.to_parquet(CORPUS_PARQUET, index=False)
    except Exception as e:  # noqa: BLE001 — parquet is optional (needs pyarrow)
        print(f"(parquet skipped: {e})")

    # --- quick landscape report ---
    print(f"parsed {before} records -> {len(df)} unique PMIDs")
    print(f"  with DOI:        {(df['doi'] != '').sum()} ({(df['doi'] != '').mean():.0%})")
    print(f"  year resolved:   {(df['year'].notna()).sum()}")
    print(f"  era split:       pre={((df['era'] == 'pre').sum())}  post={((df['era'] == 'post').sum())}")
    print(f"  multicenter/reg: {df['is_multicenter_or_registry'].sum()}")
    print(f"  country known:   {(df['country'] != '').sum()} ({(df['country'] != '').mean():.0%})")
    print("  top countries:")
    for c, n in df.loc[df['country'] != '', 'country'].value_counts().head(8).items():
        print(f"    {c:<16} {n}")
    print(f"\nwrote {CORPUS_CSV}")


if __name__ == "__main__":
    main()
