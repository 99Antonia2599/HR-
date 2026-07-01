"""
HR Intelligence Digest – Model AG
==================================
Scrapt definierte HR-/Arbeitsmarkt-Quellen (CH + DE + Global),
ordnet Artikel den fünf Model-Themen zu und generiert ein
gebrandetes HTML-Briefing (Format A = Kurzdigest, Format B = Vollreport).

Nutzung:
    pip install feedparser trafilatura
    python hr_digest.py              # → Format A (Default)
    python hr_digest.py --full       # → Format B
    python hr_digest.py --logo MODEL_Logo_Medium.jpg   # Logo einbetten

Für GitHub Actions: siehe .github/workflows/hr_digest.yml
"""

import feedparser
import trafilatura
import re
import sys
import os
import base64
import argparse
from datetime import datetime, timedelta, timezone
from time import mktime
from collections import defaultdict

# ── Konfiguration ──────────────────────────────────────────

# Quellen-Pool gemäss Projekt-Anweisungen (Section 6)
FEEDS = [
    # ── Schweiz ──
    ("SRF Wirtschaft",              "https://www.srf.ch/news/wirtschaft.rss"),
    ("KOF ETH Konjunktur",         "https://kof.ethz.ch/news-und-veranstaltungen/news.rss.xml"),
    ("Swissstaffing",              "https://www.swissstaffing.ch/feed/"),
    ("BFS Neues",                  "https://www.bfs.admin.ch/bfs/de/home/aktuell/neue-veroeffentlichungen.gnpdetail.rss.html"),

    # ── Deutschland ──
    ("Hans-Böckler-Stiftung",      "https://www.boeckler.de/de/boeckler-impuls-rss.xml"),
    ("IAB Forschung",              "https://www.iab-forum.de/feed/"),
    ("ifo Institut",               "https://www.ifo.de/feed/rss/ifo-news"),
    ("IW Köln",                    "https://www.iwkoeln.de/rss/presse.xml"),

    # ── HR-Fachmedien (DE/CH) ──
    ("Personalwirtschaft",         "https://www.personalwirtschaft.de/rss/feed.xml"),
    ("HRM Online",                 "https://www.hrm.de/feed/"),
    ("Haufe Personal",             "https://www.haufe.de/personal/rss_366_488.xml"),
    ("HR Journal",                 "https://www.hrjournal.de/feed/"),
    ("Persoblogger",               "https://persoblogger.de/feed/"),

    # ── HR-Tech / KI ──
    ("Personalwirtschaft (Tech)",  "https://www.personalwirtschaft.de/rss/feed.xml"),
]

# ── Die 5 Themen (Section 5) ──────────────────────────────

THEMES = {
    "01 · Lohn": {
        "label": "Lohnentwicklung",
        "label_full": "Lohnentwicklung",
        "keywords": [
            "lohn", "gehalt", "lohnentwicklung", "lohnerhöhung", "tarifvertrag",
            "tarifabschluss", "tarif", "reallohn", "nominallohn",
            "mindestlohn", "lohnindex", "teuerung", "inflation", "lik",
            "kaufkraft", "gesamtarbeitsvertrag", "gav", "igbce", "bavc",
            "chemietarif", "vergütung", "entgelt", "lohnrunde",
            "cost of living", "real wage", "teuerungsausgleich",
            "lohnverhandlung", "lohnkosten", "arbeitskostenindex",
        ],
    },
    "02 · Talent": {
        "label": "Talent Management & HR-Trends",
        "label_full": "Talent Management & HR-Trends",
        "keywords": [
            "talent", "engagement", "burnout", "retention", "fluktuation",
            "mitarbeiterbindung", "employee value proposition", "evp",
            "employer branding", "arbeitgebermarke", "mitarbeiterzufriedenheit",
            "wellbeing", "work-life", "new work", "arbeitskultur",
            "generationenwechsel", "gen z", "fachkräfte binden",
            "talent management", "talent trend", "onboarding",
            "mental health", "gesundheit", "bgm",
        ],
    },
    "03 · Rekrutierung": {
        "label": "Rekrutierung & Fachkräftemangel",
        "label_full": "Rekrutierung & Fachkräftemangel",
        "keywords": [
            "fachkräftemangel", "fachkräfte", "recruiting", "rekrutierung",
            "stellenmarkt", "engpass", "engpassberufe", "vakanz",
            "arbeitsmarkt", "arbeitslosenquote", "erwerbstätige",
            "arbeitskräfte", "demografischer wandel", "demografie",
            "zuwanderung", "personenfreizügigkeit", "grenzgänger",
            "active sourcing", "bewerbermangel", "arbeitsmigration",
            "kofa", "dihk", "adecco", "manpower", "stellenindex",
            "instandhalter", "maschinenführer", "elektroniker",
            "automatisierungstechniker", "schichtarbeit",
        ],
    },
    "04 · Führung": {
        "label": "Führungskräfteentwicklung",
        "label_full": "Führungskräfteentwicklung",
        "keywords": [
            "führung", "leadership", "führungskraft", "führungskräfte",
            "change management", "transformation", "managemententwicklung",
            "führungskultur", "schichtleiter", "werkleiter",
            "middle management", "agile führung", "remote leadership",
            "führungskompetenz", "coaching", "managementtraining",
            "organisationsentwicklung", "unternehmenskultur",
            "personalentwicklung", "weiterbildung", "fortbildung",
            "qualifizierung", "skill", "upskilling", "reskilling",
        ],
    },
    "05 · KI": {
        "label": "KI im Personalwesen",
        "label_full": "KI im Personalwesen (HR-Tech)",
        "keywords": [
            "künstliche intelligenz", " ki ", "ki-", "ai act",
            "eu ai act", "hr-tech", "hr-software", "people analytics",
            "automatisierung", "digitalisierung", "chatbot",
            "machine learning", "generative ki", "large language",
            "ki im hr", "ki-gestützt", "algorithmus", "ai governance",
            "hr-technologie", "predictive", "robotik", "rpa",
            "process automation", "ki-tool", "copilot",
        ],
    },
}

# Alle Keywords flach für Relevanzprüfung
ALL_KEYWORDS = []
for theme in THEMES.values():
    ALL_KEYWORDS.extend(theme["keywords"])
ALL_KEYWORDS += [
    "personal", "hr", "human resources", "mitarbeiter",
    "personalplanung", "arbeitgeber", "arbeitnehmer",
    "beschäftigung", "konjunktur", "arbeitsrecht",
]

MAX_AGE_DAYS = 14  # 14-Tage-Fenster gemäss Anweisungen
MAX_ARTICLES = 50

# Irrelevante Artikel filtern
BLACKLIST = [
    "amazon", "prime day", "angebot", "rabatt", "gutschein", "deal",
    "fritzbox", "router", "iphone", "ipad", "apple watch", "samsung",
    "playstation", "xbox", "nintendo", "netflix", "spotify",
    "rezept", "kochen", "reise", "urlaub", "hotel", "flug",
    "aktie", "bitcoin", "krypto", "etf", "depot", "börse",
    "streaming", "smart home", "gadget", "testbericht",
]


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


def is_blacklisted(title):
    t = title.lower()
    return any(b in t for b in BLACKLIST)


def is_relevant(title, summary, keywords):
    if is_blacklisted(title):
        return False
    title_lower = title.lower()
    if any(k in title_lower for k in keywords):
        return True
    text_lower = summary.lower()
    hits = sum(1 for k in keywords if k in text_lower)
    return hits >= 2


def classify_theme(text):
    """Ordnet Text dem besten der 5 Themen zu."""
    text_lower = text.lower()
    best_key = None
    best_score = 0
    for key, theme in THEMES.items():
        score = sum(1 for k in theme["keywords"] if k in text_lower)
        if score > best_score:
            best_score = score
            best_key = key
    return best_key if best_key and best_score > 0 else None


# ── Paywall-Erkennung ──────────────────────────────────────

PAYWALL_DOMAINS = {
    "faz.net", "handelsblatt.com", "spiegel.de", "zeit.de",
    "sueddeutsche.de", "welt.de", "wiwo.de", "manager-magazin.de",
    "nzz.ch", "tagesanzeiger.ch",
}

PAYWALL_SIGNALS = [
    "paywall", "premium-content", "plus-content", "abo-content",
    "regwall", "piano-offer", "subscribe", "registrieren sie sich",
    "lesen sie den vollständigen artikel", "jetzt freischalten",
    "exklusiv für abonnenten", "s+ artikel",
]


def is_paywall_domain(url):
    return any(d in url.lower() for d in PAYWALL_DOMAINS)


def looks_like_paywall(text):
    if not text:
        return True
    if len(text.split()) < 50:
        return True
    text_lower = text.lower()
    hits = sum(1 for s in PAYWALL_SIGNALS if s in text_lower)
    return hits >= 2


# ── Artikel-Text holen ─────────────────────────────────────

def extract_rss_fulltext(entry):
    texts = []
    for content in getattr(entry, "content", []):
        val = content.get("value", "")
        if val:
            texts.append(clean_html(val))
    summary = clean_html(getattr(entry, "summary", ""))
    if summary:
        texts.append(summary)
    desc = clean_html(getattr(entry, "description", ""))
    if desc and desc != summary:
        texts.append(desc)
    if not texts:
        return None
    best = max(texts, key=len)
    return best if len(best) > 80 else None


def fetch_article_text(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            deduplicate=True,
            favor_precision=False,
            include_links=False,
        )
        return text
    except Exception as e:
        print(f"      ⚠️  Text-Extraktion fehlgeschlagen: {e}")
        return None


def get_best_text(entry, url):
    rss_text = extract_rss_fulltext(entry)
    web_text = None
    source = "rss"

    if is_paywall_domain(url):
        print(f"      🔒 Paywall-Quelle erkannt, nutze RSS-Inhalt")
        web_text = fetch_article_text(url)
        if web_text and not looks_like_paywall(web_text):
            source = "web"
        elif rss_text and len(rss_text) > 100:
            source = "rss"
            web_text = None
        else:
            source = "partial"
    else:
        web_text = fetch_article_text(url)
        if web_text and len(web_text) > 100:
            source = "web"

    if source == "web" and web_text:
        return web_text, source
    elif rss_text and len(rss_text or "") > len(web_text or ""):
        return rss_text, "rss"
    elif web_text:
        return web_text, "partial"
    elif rss_text:
        return rss_text, "rss"
    else:
        return None, "none"


# ── Extraktive Zusammenfassung ─────────────────────────────

STOPWORDS = {
    "der", "die", "das", "und", "oder", "für", "von", "mit",
    "ist", "sind", "ein", "eine", "auf", "bei", "nach", "wie",
    "sich", "auch", "den", "dem", "des", "im", "in", "zu",
    "nicht", "als", "an", "es", "hat", "wird", "zum", "zur",
    "über", "aus", "vor", "noch", "nur", "mehr", "so", "aber",
    "was", "wenn", "man", "kann", "haben", "werden", "dass",
    "einem", "einer", "diese", "dieser", "dieses", "bis",
}


def split_sentences(text):
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÄÖÜ])', text)
    return [s.strip() for s in sentences if len(s.split()) >= 8]


def score_sentence(sentence, title_words):
    words = sentence.lower().split()
    score = 0.0
    for w in words:
        if w in title_words:
            score += 2.0
    sent_lower = sentence.lower()
    for kw in ALL_KEYWORDS:
        if kw in sent_lower:
            score += 1.5
    if re.search(r'\d+[,.]?\d*\s*(%|Prozent|Euro|Milliard|Million|Franken|CHF)', sentence):
        score += 2.0
    if len(words) > 40:
        score *= 0.7
    starters = [
        "demnach", "laut", "insgesamt", "erstmals", "künftig",
        "besonders", "entscheidend", "wichtig", "zentral",
        "das ergebnis", "die studie", "experten",
    ]
    for s in starters:
        if sent_lower.startswith(s):
            score += 1.0
            break
    return score


def summarize_text(text, title, num_sentences=3):
    if not text or len(text) < 100:
        return None
    sentences = split_sentences(text)
    if not sentences:
        return None
    title_words = {
        w.lower() for w in title.split()
        if w.lower() not in STOPWORDS and len(w) > 2
    }
    scored = []
    for i, sent in enumerate(sentences):
        score = score_sentence(sent, title_words)
        if i == 0:
            score += 3.0
        elif i == 1:
            score += 1.5
        elif i == 2:
            score += 0.5
        scored.append((score, i, sent))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:num_sentences]
    top.sort(key=lambda x: x[1])
    return " ".join(s[2] for s in top)


# ── RSS Scraping ───────────────────────────────────────────

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
            rss_summary = clean_html(getattr(entry, "summary", ""))
            if not is_relevant(title, rss_summary, ALL_KEYWORDS):
                continue
            seen.add(link)
            articles.append({
                "title": title,
                "source": name,
                "url": link,
                "rss_summary": rss_summary[:500],
                "date": pub or datetime.now(timezone.utc),
                "_entry": entry,
            })
            count += 1
        print(f"   ✅ {count} Artikel")

    articles.sort(key=lambda a: a["date"], reverse=True)
    if len(articles) > MAX_ARTICLES:
        print(f"\n✂️  Gekürzt auf {MAX_ARTICLES} Artikel")
        articles = articles[:MAX_ARTICLES]

    print(f"\n📊 {len(articles)} Artikel gefunden, hole jetzt Volltexte ...\n")

    for i, a in enumerate(articles):
        print(f"   📄 [{i+1}/{len(articles)}] {a['title'][:60]}...")
        full_text, text_source = get_best_text(a["_entry"], a["url"])
        a["full_text"] = full_text
        if full_text:
            summary = summarize_text(full_text, a["title"], num_sentences=4)
            a["summary"] = summary or a["rss_summary"]
            a["word_count"] = len(full_text.split())
            source_label = {"web": "Volltext", "rss": "RSS-Inhalt",
                            "partial": "Teiltext"}[text_source]
            print(f"      ✅ {a['word_count']} Wörter ({source_label})")
        else:
            a["summary"] = a["rss_summary"]
            a["word_count"] = 0
            print(f"      ℹ️  Kein Volltext, nutze RSS-Vorschau")

        del a["_entry"]
        a["theme"] = classify_theme(f"{a['title']} {a['summary']}")

    return articles


# ── Artikel nach Themen gruppieren ─────────────────────────

def group_by_theme(articles):
    """Gruppiert Artikel nach den 5 Themen. Gibt OrderedDict zurück."""
    grouped = defaultdict(list)
    for a in articles:
        if a.get("theme"):
            grouped[a["theme"]].append(a)
    # Feste Reihenfolge
    ordered = {}
    for key in THEMES:
        ordered[key] = grouped.get(key, [])
    return ordered


def pick_best_articles(theme_articles, n=3):
    """Wählt die n besten Artikel eines Themas (nach Wortanzahl/Datum)."""
    scored = []
    for a in theme_articles:
        s = a.get("word_count", 0) * 0.5
        if a.get("date"):
            age_hours = (datetime.now(timezone.utc) - a["date"]).total_seconds() / 3600
            s += max(0, 100 - age_hours)
        scored.append((s, a))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:n]]


# ── Logo einbetten ─────────────────────────────────────────

def load_logo_base64(logo_path=None):
    """Versucht Logo als Base64 zu laden. Gibt None zurück falls nicht vorhanden."""
    paths_to_try = []
    if logo_path:
        paths_to_try.append(logo_path)
    paths_to_try += [
        "MODEL_Logo_Medium.jpg",
        "MODEL_Logo.jpg",
        "MODEL_Logo_Medium.png",
        "MODEL_Logo.png",
    ]
    for p in paths_to_try:
        if os.path.isfile(p):
            ext = os.path.splitext(p)[1].lower()
            mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
            with open(p, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
            return f"data:{mime};base64,{data}"
    return None


def logo_html(logo_b64, height="32px", opacity="1"):
    if logo_b64:
        return f'<img src="{logo_b64}" style="height:{height};width:auto;display:block;opacity:{opacity};" alt="MODEL">'
    return '<span style="font-family:\'Messina Sans\',sans-serif;font-weight:800;font-size:28px;letter-spacing:-0.02em;">MODEL</span>'


# ── HTML-Generierung: Format A (Kurzdigest) ───────────────

FORMAT_A_CSS = """\
:root {
  --coral: #DA5A2D; --amber: #F0B400; --grau5: #F2F2F2;
  --grau10: #E6E6E6; --grau20: #CCCCCC; --grau50: #808080;
  --black: #000000; --white: #FFFFFF;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  font-family: 'Messina Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  color: var(--black); background: var(--white);
  line-height: 1.55; font-size: 15px;
}
.page { max-width: 720px; margin: 0 auto; padding: 48px 56px 56px 56px; background: var(--white); }
header.head { border-bottom: 3px solid var(--coral); padding-bottom: 22px; margin-bottom: 32px; }
.head-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 22px; }
.head-top img { height: 32px; width: auto; display: block; }
.head-meta { text-align: right; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--grau50); line-height: 1.6; }
h1.title { font-weight: 600; font-size: 26px; line-height: 1.2; margin: 0 0 6px 0; }
.subtitle { font-family: 'Messina Serif', Georgia, serif; font-style: italic; font-size: 14px; color: var(--grau50); margin: 0; }
.bullet { padding: 22px 0; border-bottom: 1px solid var(--grau10); }
.bullet:last-of-type { border-bottom: none; }
.bullet-head { display: flex; align-items: baseline; gap: 14px; margin-bottom: 10px; }
.bullet-num { font-family: 'Messina Serif', Georgia, serif; font-size: 12px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--coral); font-weight: 600; min-width: 60px; flex-shrink: 0; }
.bullet-head h3 { font-weight: 600; font-size: 17px; line-height: 1.3; margin: 0; }
.bullet-body { padding-left: 74px; }
.bullet-body p { margin: 0 0 8px 0; font-size: 14px; line-height: 1.6; }
.bullet-body .relevance { font-size: 13px; color: #333; border-left: 2px solid var(--coral); padding: 2px 0 2px 12px; margin-top: 10px; }
.bullet-body .relevance strong { color: var(--coral); font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 600; display: block; margin-bottom: 3px; }
.sources { margin-top: 32px; padding-top: 18px; border-top: 1px dashed var(--grau20); font-size: 11px; line-height: 1.6; color: var(--grau50); }
.sources .label { text-transform: uppercase; letter-spacing: 0.14em; font-weight: 600; font-size: 10px; margin-bottom: 6px; display: block; }
footer.foot { margin-top: 36px; padding-top: 18px; border-top: 3px solid var(--coral); font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--grau50); display: flex; justify-content: space-between; align-items: center; }
footer.foot img { height: 20px; opacity: 0.55; }
"""


def build_bullet_html(theme_key, articles):
    """Baut einen Bullet-Block für Format A."""
    theme = THEMES[theme_key]
    num_tag = theme_key  # z.B. "01 · Lohn"

    if not articles:
        headline = f"{theme['label']}: Keine wesentlichen Veränderungen"
        body = "Im Berichtszeitraum wurden keine signifikanten neuen Entwicklungen identifiziert. Die Marktlage bleibt stabil auf dem zuletzt berichteten Niveau."
        relevance = "Keine unmittelbaren Handlungsimpulse. Weiterbeobachtung empfohlen."
    else:
        best = pick_best_articles(articles, n=2)
        headline = best[0]["title"]
        # Zusammenfassung der besten Artikel kombinieren
        body_parts = []
        for a in best:
            if a.get("summary"):
                body_parts.append(a["summary"])
        body = " ".join(body_parts)
        # Kürzen auf vernünftige Länge
        sentences = split_sentences(body) if body else []
        body = " ".join(sentences[:6]) if sentences else body[:600]

        # Model AG Relevanz
        relevance = generate_relevance_note(theme_key, best)

    # Bold key numbers in body
    body = re.sub(
        r'(\d+[,.]?\d*\s*(?:%|Prozent|Euro|Milliarden?|Millionen?|Franken|CHF|EUR))',
        r'<b>\1</b>',
        body
    )

    return f"""
    <div class="bullet">
      <div class="bullet-head">
        <span class="bullet-num">{num_tag}</span>
        <h3>{_esc(headline)}</h3>
      </div>
      <div class="bullet-body">
        <p>{body}</p>
        <div class="relevance">
          <strong>Für Model AG</strong>
          {relevance}
        </div>
      </div>
    </div>"""


def generate_relevance_note(theme_key, articles):
    """Generiert Model-AG-spezifische Relevanznotiz basierend auf Thema."""
    notes = {
        "01 · Lohn": (
            "Für die Schweizer Standorte Weinfelden, Niedergösgen und Moudon sind "
            "die GAV-Verhandlungen und der Landesindex der Konsumentenpreise (LIK) "
            "massgeblich. Eilenburg orientiert sich am IGBCE-/BAVC-Tarifabschluss "
            "für die chemisch-pharmazeutische Industrie als nächstem Benchmark."
        ),
        "02 · Talent": (
            "Die Schichtarbeit in der Kartonproduktion stellt besondere Anforderungen "
            "an Engagement und Work-Life-Balance. Massnahmen zur Bindung von "
            "Maschinenführern und Instandhaltern haben direkten Einfluss auf die "
            "Produktionskontinuität aller Standorte."
        ),
        "03 · Rekrutierung": (
            "Engpassprofile bei Model: Maschinenführer, Instandhaltungstechniker, "
            "Elektroniker und Automationsspezialisten. Die demografische Alterung "
            "in der Produktion erhöht den Ersatzbedarf an allen Standorten. "
            "Für Eilenburg gelten die deutschen Engpassanalysen der BA direkt."
        ),
        "04 · Führung": (
            "Schicht- und Werkleiter stehen an der Schnittstelle zwischen "
            "Produktionsdruck und Mitarbeiterführung. Change-Kompetenz wird "
            "mit zunehmender Automatisierung und multigenerationaler "
            "Teamzusammensetzung zum Schlüsselfaktor."
        ),
        "05 · KI": (
            "KI-Einsatz im HR muss für Model die Schichtboden-Realität "
            "adressieren, nicht nur Büroarbeitsplatz-Szenarien. Relevante "
            "Anwendungen: prädiktive Personaleinsatzplanung, automatisierte "
            "Schichtplanung und KI-gestützte Kompetenzerfassung."
        ),
    }
    return notes.get(theme_key, "")


def build_format_a(articles, logo_b64):
    """Generiert vollständiges HTML für Format A."""
    today = datetime.now()
    kw = today.isocalendar()[1]
    year = today.year
    date_str = today.strftime("%d.%m.%Y")

    grouped = group_by_theme(articles)

    # Bullets bauen
    bullets_html = ""
    for key in THEMES:
        theme_articles = grouped.get(key, [])
        bullets_html += build_bullet_html(key, theme_articles)

    # Quellen sammeln
    all_sources = set()
    for a in articles:
        all_sources.add(a["source"])
    sources_str = " · ".join(sorted(all_sources))

    logo_header = logo_html(logo_b64, height="32px")
    logo_footer = logo_html(logo_b64, height="20px", opacity="0.55")

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HR Digest · KW {kw}/{year} · Model AG</title>
<style>
{FORMAT_A_CSS}
</style>
</head>
<body>
<div class="page">

  <header class="head">
    <div class="head-top">
      {logo_header}
      <div class="head-meta">
        HR Digest · KW {kw}/{year}<br>
        {date_str}<br>
        Vertraulich — Intern
      </div>
    </div>
    <h1 class="title">HR Digest für die Model AG</h1>
    <p class="subtitle">Fünf Schlaglichter aus dem HR-Markt — aufbereitet für die HR-Leitung. Lesezeit: ca. 4 Minuten.</p>
  </header>

  {bullets_html}

  <div class="sources">
    <span class="label">Quellen</span>
    {_esc(sources_str)}
  </div>

  <footer class="foot">
    <span>Erstellt durch DMA Core · Für: Michael Uebersax, HR-Leitung</span>
    {logo_footer}
  </footer>

</div>
</body>
</html>"""


# ── HTML-Generierung: Format B (Vollreport) ────────────────

FORMAT_B_CSS = """\
:root {
  --coral: #DA5A2D; --amber: #F0B400; --lapis: #5F75AF;
  --grau5: #F2F2F2; --grau10: #E6E6E6; --grau20: #CCCCCC; --grau50: #808080;
  --black: #000000; --white: #FFFFFF;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  font-family: 'Messina Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  color: var(--black); background: var(--white);
  line-height: 1.55; font-size: 15px;
}
.page { max-width: 900px; margin: 0 auto; padding: 56px 64px 80px 64px; background: var(--white); }
.cover { border-bottom: 4px solid var(--coral); padding-bottom: 28px; margin-bottom: 40px; }
.cover-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 36px; }
.cover-logo img { height: 44px; width: auto; display: block; }
.cover-meta { text-align: right; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--grau50); line-height: 1.7; }
h1.cover-title { font-family: 'Messina Serif', Georgia, serif; font-weight: 400; font-size: 44px; line-height: 1.1; margin: 0 0 18px 0; }
.cover-subtitle { font-family: 'Messina Serif', Georgia, serif; font-style: italic; font-size: 18px; color: var(--grau50); margin-bottom: 28px; }
.doc-meta-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; margin-top: 24px; padding-top: 24px; border-top: 1px solid var(--grau10); }
.doc-meta-grid .item .label { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--grau50); margin-bottom: 4px; display: block; }
.doc-meta-grid .item .value { font-size: 14px; font-weight: 500; }
section.theme { margin-bottom: 56px; }
.theme-number { font-family: 'Messina Serif', Georgia, serif; font-size: 13px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--coral); margin-bottom: 8px; display: block; font-weight: 600; }
h2.theme-title { font-weight: 600; font-size: 26px; line-height: 1.2; margin: 0 0 18px 0; }
.theme-intro { font-size: 15px; line-height: 1.6; margin-bottom: 28px; }
h3.subsection { font-size: 12px; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; color: var(--grau50); margin: 28px 0 14px 0; padding-bottom: 6px; border-bottom: 1px solid var(--grau10); }
.fact { border-left: 3px solid var(--coral); padding: 4px 0 4px 18px; margin-bottom: 18px; }
.fact .lead { font-weight: 600; }
.fact p { margin: 0; }
.relevance { background: var(--grau5); padding: 20px 24px; border-radius: 2px; margin: 20px 0 16px 0; }
.relevance .label { font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--coral); font-weight: 600; margin-bottom: 8px; display: block; }
.relevance p { margin: 0 0 10px 0; }
.relevance p:last-child { margin-bottom: 0; }
.sources { font-size: 12px; color: var(--grau50); font-style: italic; line-height: 1.5; padding-top: 10px; border-top: 1px dashed var(--grau20); margin-top: 16px; }
.sources strong { font-style: normal; text-transform: uppercase; letter-spacing: 0.1em; font-size: 10px; display: block; margin-bottom: 4px; }
.lead-callout { background: var(--coral); color: var(--white); padding: 28px 32px; margin-bottom: 48px; border-radius: 2px; }
.lead-callout .tag { font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; opacity: 0.85; margin-bottom: 8px; display: block; }
.lead-callout h3 { font-family: 'Messina Serif', Georgia, serif; font-weight: 400; font-size: 24px; line-height: 1.25; margin: 0 0 10px 0; }
.lead-callout p { margin: 0; font-size: 14px; line-height: 1.55; opacity: 0.95; }
.recs { background: var(--black); color: var(--white); padding: 40px 44px; margin: 48px -8px 0 -8px; border-radius: 2px; }
.recs .recs-tag { font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--amber); font-weight: 600; margin-bottom: 8px; display: block; }
.recs h2 { font-family: 'Messina Serif', Georgia, serif; font-weight: 400; font-size: 32px; margin: 0 0 12px 0; line-height: 1.15; }
.recs .recs-intro { font-size: 14px; opacity: 0.85; margin-bottom: 28px; }
.rec-item { border-top: 1px solid rgba(255,255,255,0.18); padding: 22px 0 18px 0; }
.rec-item:last-child { padding-bottom: 0; }
.rec-item .rec-num { font-family: 'Messina Serif', Georgia, serif; color: var(--amber); font-size: 13px; letter-spacing: 0.2em; text-transform: uppercase; margin-bottom: 4px; display: block; }
.rec-item h4 { font-weight: 600; font-size: 17px; margin: 0 0 12px 0; }
.rec-row { display: grid; grid-template-columns: 90px 1fr; gap: 14px; margin-bottom: 8px; font-size: 13.5px; line-height: 1.55; }
.rec-row .key { font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--amber); padding-top: 3px; font-weight: 600; }
footer.doc-footer { margin-top: 64px; padding-top: 24px; border-top: 4px solid var(--coral); display: flex; justify-content: space-between; align-items: center; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--grau50); }
footer.doc-footer .footer-logo img { height: 24px; opacity: 0.6; }
"""


def build_theme_section_html(theme_key, articles):
    """Baut eine Themen-Section für Format B."""
    theme = THEMES[theme_key]
    num_label = f"Thema {theme_key[:2].strip('0')} · {theme['label']}"

    best = pick_best_articles(articles, n=3)

    # Intro
    if articles:
        intro = articles[0].get("summary", "")[:300]
    else:
        intro = "Im aktuellen Berichtszeitraum wurden keine wesentlichen neuen Entwicklungen identifiziert."

    # Fact blocks
    facts_html = ""
    sources_list = []
    for a in best:
        summary = a.get("summary", "")
        # Bold numbers
        summary = re.sub(
            r'(\d+[,.]?\d*\s*(?:%|Prozent|Euro|Milliarden?|Millionen?|Franken|CHF|EUR))',
            r'<b>\1</b>',
            summary
        )
        title_short = a["title"][:80]
        facts_html += f"""
        <div class="fact">
          <p><span class="lead">{_esc(title_short)}.</span> {summary}</p>
        </div>"""
        sources_list.append(f"{a['source']}")

    if not facts_html:
        facts_html = """
        <div class="fact">
          <p><span class="lead">Keine neuen Entwicklungen.</span> Die Marktlage bleibt stabil auf dem zuletzt berichteten Niveau.</p>
        </div>"""

    relevance = generate_relevance_note(theme_key, best)
    sources_str = " · ".join(sorted(set(sources_list))) if sources_list else "—"

    return f"""
  <section class="theme">
    <span class="theme-number">{num_label}</span>
    <h2 class="theme-title">{theme['label_full']}</h2>
    <p class="theme-intro">{_esc(intro)}</p>

    <h3 class="subsection">Entwicklungen &amp; Fakten</h3>
    {facts_html}

    <div class="relevance">
      <span class="label">Relevanz für die Model AG</span>
      <p>{relevance}</p>
    </div>

    <div class="sources">
      <strong>Quellen</strong>
      {_esc(sources_str)}
    </div>
  </section>"""


def build_lead_callout(grouped):
    """Wählt das Thema mit den meisten/besten Artikeln als Lead Story."""
    best_key = None
    best_count = 0
    for key, arts in grouped.items():
        total_words = sum(a.get("word_count", 0) for a in arts)
        if total_words > best_count:
            best_count = total_words
            best_key = key
    if not best_key or not grouped.get(best_key):
        best_key = list(THEMES.keys())[0]

    theme = THEMES[best_key]
    articles = grouped.get(best_key, [])
    if articles:
        headline = articles[0]["title"]
        body = articles[0].get("summary", "")[:250]
    else:
        headline = theme["label"]
        body = "Im aktuellen Berichtszeitraum das dominante Thema."

    return f"""
  <div class="lead-callout">
    <span class="tag">Lead Story der Woche</span>
    <h3>{_esc(headline)}</h3>
    <p>{_esc(body)}</p>
  </div>"""


def build_recommendations_html():
    """Generiert den Empfehlungsblock (statische Struktur, datengestützt befüllt)."""
    recs = [
        {
            "title": "Lohnbenchmark aktualisieren und Budgetrunde vorbereiten",
            "ziel": "Wettbewerbsfähige Vergütung an allen vier Standorten sicherstellen, bevor der Arbeitsmarkt im Herbst anzieht.",
            "umsetzung": "Aktuelle Tarifdaten (IGBCE/BAVC für Eilenburg, GAV-Verhandlungen für CH-Standorte) konsolidieren und in die Budgetplanung Q4 einfliessen lassen.",
        },
        {
            "title": "Engpassprofile proaktiv sourcen",
            "ziel": "Pipeline für Maschinenführer, Instandhalter und Automationsspezialisten aufbauen, bevor Vakanzen produktionskritisch werden.",
            "umsetzung": "Active-Sourcing-Kampagne für die drei kritischsten Profile starten. Kooperation mit regionalen Berufsschulen und Swissstaffing/Adecco prüfen.",
        },
        {
            "title": "KI-Readiness im HR-Team erhöhen",
            "ziel": "Grundlagen für den regelkonformen Einsatz von KI-Tools im Recruiting und in der Personalplanung schaffen.",
            "umsetzung": "EU AI Act-Anforderungen für HR-Anwendungen intern dokumentieren. Pilotprojekt für KI-gestützte Schichtplanung an einem Standort definieren.",
        },
    ]

    items_html = ""
    for i, rec in enumerate(recs, 1):
        items_html += f"""
      <div class="rec-item">
        <span class="rec-num">Massnahme {i}</span>
        <h4>{rec['title']}</h4>
        <div class="rec-row">
          <span class="key">Ziel</span>
          <span>{rec['ziel']}</span>
        </div>
        <div class="rec-row">
          <span class="key">Umsetzung</span>
          <span>{rec['umsetzung']}</span>
        </div>
      </div>"""

    return f"""
  <div class="recs">
    <span class="recs-tag">Handlungsempfehlungen für die HR-Leitung</span>
    <h2>Drei strategische Sofortmassnahmen für die Model AG</h2>
    <p class="recs-intro">Abgeleitet aus den aktuellen Marktentwicklungen — priorisiert nach Handlungsdruck.</p>
    {items_html}
  </div>"""


def build_format_b(articles, logo_b64):
    """Generiert vollständiges HTML für Format B."""
    today = datetime.now()
    kw = today.isocalendar()[1]
    year = today.year
    date_str = today.strftime("%d.%m.%Y")

    grouped = group_by_theme(articles)

    logo_cover = logo_html(logo_b64, height="44px")
    logo_footer = logo_html(logo_b64, height="24px", opacity="0.6")

    # Lead Callout
    lead_html = build_lead_callout(grouped)

    # Themen-Sections
    sections_html = ""
    for key in THEMES:
        sections_html += build_theme_section_html(key, grouped.get(key, []))

    # Empfehlungen
    recs_html = build_recommendations_html()

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HR Intelligence Report · KW {kw}/{year} · Model AG</title>
<style>
{FORMAT_B_CSS}
</style>
</head>
<body>
<div class="page">

  <div class="cover">
    <div class="cover-top">
      <div class="cover-logo">{logo_cover}</div>
      <div class="cover-meta">
        Ausgabe KW {kw}/{year}<br>
        Vertraulich — Intern
      </div>
    </div>
    <h1 class="cover-title">HR Intelligence Report</h1>
    <p class="cover-subtitle">Aktuelle Entwicklungen im HR-Markt und ihre Bedeutung für die Model AG — Kalenderwoche {kw}, {year}.</p>
    <div class="doc-meta-grid">
      <div class="item">
        <span class="label">Datum</span>
        <span class="value">{date_str}</span>
      </div>
      <div class="item">
        <span class="label">Empfänger</span>
        <span class="value">Michael Uebersax</span>
      </div>
      <div class="item">
        <span class="label">Fokus-Regionen</span>
        <span class="value">CH · DE</span>
      </div>
      <div class="item">
        <span class="label">Owner</span>
        <span class="value">DMA Core</span>
      </div>
    </div>
  </div>

  {lead_html}

  {sections_html}

  {recs_html}

  <footer class="doc-footer">
    <span>HR Intelligence Report · Model AG · KW {kw}/{year} · Erstellt durch DMA Core · Vertraulich — Intern</span>
    <div class="footer-logo">{logo_footer}</div>
  </footer>

</div>
</body>
</html>"""


# ── Hilfsfunktion: HTML-Escaping ───────────────────────────

def _esc(text):
    """Einfaches HTML-Escaping."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ── Main ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="HR Intelligence Digest — Model AG"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Format B: Vollständiger HR Intelligence Report (Default: Format A Kurzdigest)"
    )
    parser.add_argument(
        "--logo", type=str, default=None,
        help="Pfad zur Logo-Datei (JPG/PNG). Wird als Base64 eingebettet."
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Ausgabe-Dateiname (Default: auto-generiert)"
    )
    args = parser.parse_args()

    fmt = "B" if args.full else "A"
    fmt_label = "HR Intelligence Report (Format B)" if args.full else "HR Digest (Format A)"

    print("=" * 60)
    print(f"  🚀 {fmt_label} — Model AG")
    print("=" * 60 + "\n")

    # Logo laden
    logo_b64 = load_logo_base64(args.logo)
    if logo_b64:
        print("✅ Logo geladen und als Base64 eingebettet\n")
    else:
        print("ℹ️  Kein Logo gefunden — verwende Text-Wordmark\n")

    # Scraping
    articles = scrape()

    # HTML generieren
    if args.full:
        html = build_format_b(articles, logo_b64)
    else:
        html = build_format_a(articles, logo_b64)

    # Dateiname
    today = datetime.now()
    kw = today.isocalendar()[1]
    if args.output:
        filename = args.output
    else:
        prefix = "hr-intelligence-report" if args.full else "hr-digest"
        filename = f"{prefix}-{today.strftime('%Y-%m-%d')}-kw{kw}.html"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n{'=' * 60}")
    print(f"✅ Gespeichert: {filename}")
    print(f"📄 {len(articles)} Artikel verarbeitet → {fmt_label}")
    print(f"{'=' * 60}")
    print(f"\nDatei öffnen: {filename}")


if __name__ == "__main__":
    main()
