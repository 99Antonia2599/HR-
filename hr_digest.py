"""
HR News Digest – Standalone Version (ohne KI)
==============================================
Scrapt deutsche HR-Nachrichtenquellen und erstellt
eine gefilterte, thematisch sortierte Zusammenfassung.

Nutzung:
    pip install feedparser
    python hr_digest.py
"""

import feedparser
import re
from datetime import datetime, timedelta, timezone
from time import mktime
from collections import defaultdict

# ── Konfiguration ──────────────────────────────────────────

FEEDS = [
    ("Haufe Personal",        "https://www.haufe.de/personal/rss_366_488.xml"),
    ("Personalwirtschaft",    "https://www.personalwirtschaft.de/rss/feed.xml"),
    ("HR Journal",            "https://www.hrjournal.de/feed/"),
    ("FAZ Beruf & Chance",    "https://www.faz.net/rss/aktuell/beruf-chance/"),
    ("Handelsblatt Karriere", "https://www.handelsblatt.com/contentexport/feed/karriere"),
]

# Themen-Kategorien mit zugehörigen Keywords
CATEGORIES = {
    "⚖️ Arbeitsrecht & Regulierung": [
        "arbeitsrecht", "kündigungsschutz", "kündigung", "tarifvertrag",
        "betriebsrat", "arbeitszeitgesetz", "befristung", "gesetz",
        "regulierung", "richtlinie", "compliance", "datenschutz",
    ],
    "🔍 Recruiting & Arbeitsmarkt": [
        "recruiting", "fachkräftemangel", "bewerbung", "arbeitsmarkt",
        "stellenanzeige", "employer branding", "talent", "einstellung",
    ],
    "📈 Personalentwicklung & Weiterbildung": [
        "weiterbildung", "personalentwicklung", "onboarding", "training",
        "qualifizierung", "kompetenz", "skill", "fortbildung", "coaching",
    ],
    "💰 Vergütung & Benefits": [
        "gehalt", "gehaltserhöhung", "vergütung", "mindestlohn", "bonus",
        "lohnabrechnung", "payroll", "sozialversicherung", "benefit",
        "betriebsrente", "lohn",
    ],
    "🏠 New Work & Arbeitskultur": [
        "homeoffice", "remote work", "hybrides arbeiten", "new work",
        "work-life-balance", "unternehmenskultur", "führung", "leadership",
        "change management", "agil", "diversity", "inklusion",
    ],
    "❤️ Gesundheit & Wellbeing": [
        "mental health", "gesundheit", "bgm", "burnout", "stress",
        "betriebliche gesundheit", "wellbeing", "prävention",
    ],
    "🤖 Digitalisierung im HR": [
        "hr-software", "digitalisierung", "ki ", "künstliche intelligenz",
        "automatisierung", "hr-tech", "people analytics", "digital",
    ],
}

# Alle Keywords als flache Liste (für den Grundfilter)
ALL_KEYWORDS = []
for kws in CATEGORIES.values():
    ALL_KEYWORDS.extend(kws)
ALL_KEYWORDS += ["personal", "hr", "human resources", "mitarbeiter",
                  "personalplanung", "fluktuation", "elternzeit"]

MAX_AGE_DAYS = 7

# ── Hilfsfunktionen ────────────────────────────────────────

def clean_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()

def parse_date(entry):
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime.fromtimestamp(mktime(val), tz=timezone.utc)
            except (ValueError, OverflowError):
                continue
    return None

def matches_any(text, keywords):
    t = text.lower()
    return any(k in t for k in keywords)

def categorize(title, summary):
    """Ordnet einen Artikel der passendsten Kategorie zu."""
    text = f"{title} {summary}".lower()
    best = "📌 Sonstiges"
    best_score = 0
    for cat, keywords in CATEGORIES.items():
        score = sum(1 for k in keywords if k in text)
        if score > best_score:
            best_score = score
            best = cat
    return best

# ── Scraping ───────────────────────────────────────────────

def scrape():
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    articles = []
    seen = set()

    for name, url in FEEDS:
        print(f"📡 {name} ...")
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"   ⚠️  Fehler: {e}")
            continue

        count = 0
        for entry in feed.entries:
            link = getattr(entry, "link", "")
            if not link or link in seen:
                continue

            pub = parse_date(entry)
            if pub and pub < cutoff:
                continue

            title = getattr(entry, "title", "")
            summary = clean_html(getattr(entry, "summary", ""))

            if not matches_any(f"{title} {summary}", ALL_KEYWORDS):
                continue

            seen.add(link)
            category = categorize(title, summary)
            articles.append({
                "title": title,
                "source": name,
                "url": link,
                "summary": summary[:300],
                "date": pub or datetime.now(timezone.utc),
                "category": category,
            })
            count += 1

        print(f"   ✅ {count} Artikel")

    articles.sort(key=lambda a: a["date"], reverse=True)
    print(f"\n📊 Total: {len(articles)} relevante Artikel")
    return articles

# ── Digest erstellen ───────────────────────────────────────

def build_digest(articles):
    today = datetime.now()
    kw = today.isocalendar()[1]

    lines = []
    lines.append(f"# 📰 HR News Digest – KW {kw}")
    lines.append(f"*Erstellt am {today.strftime('%d.%m.%Y')} "
                 f"| {len(articles)} Artikel aus {len(FEEDS)} Quellen*\n")

    if not articles:
        lines.append("Keine relevanten HR-News diese Woche gefunden.")
        return "\n".join(lines)

    # Nach Kategorie gruppieren
    grouped = defaultdict(list)
    for a in articles:
        grouped[a["category"]].append(a)

    # Top-Themen
    lines.append("## 🔑 Top-Themen dieser Woche\n")
    shown = 0
    for a in articles:
        if shown >= 5:
            break
        lines.append(f"- **{a['title']}** ({a['source']})")
        shown += 1
    lines.append("")

    # Kategorien
    lines.append("---\n")
    for cat in list(CATEGORIES.keys()) + ["📌 Sonstiges"]:
        if cat not in grouped:
            continue
        items = grouped[cat]
        lines.append(f"## {cat}")
        lines.append(f"*{len(items)} Artikel*\n")
        for a in items:
            date_str = a["date"].strftime("%d.%m.")
            lines.append(f"### [{a['title']}]({a['url']})")
            lines.append(f"*{a['source']} – {date_str}*\n")
            if a["summary"]:
                lines.append(f"> {a['summary']}\n")
        lines.append("")

    return "\n".join(lines)

# ── Main ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 HR News Digest\n")

    articles = scrape()
    digest = build_digest(articles)

    # Datei speichern
    today = datetime.now()
    kw = today.isocalendar()[1]
    filename = f"hr-digest-{today.strftime('%Y-%m-%d')}-kw{kw}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(digest)

    print(f"\n✅ Gespeichert: {filename}")
    print("\nVorschau:\n")
    print(digest[:1500])
    if len(digest) > 1500:
        print(f"\n... ({len(digest)} Zeichen total, siehe Datei)")
