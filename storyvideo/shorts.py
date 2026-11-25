"""English curiosity / science Shorts: topic picking, fact research and script writing."""

from __future__ import annotations

import json
import re

from . import gemini

SHORT_STYLE = (
    "cinematic digital painting, dramatic lighting, vivid saturated colors, highly detailed, "
    "epic sense of scale, consistent semi-realistic illustration style, vertical 9:16 composition"
)

DEFAULT_SERIES = [
    "What If (hypothetical science scenarios, e.g. what if the Moon disappeared)",
    "Your Body (surprising facts about the human body)",
    "Psychology (why our brains do weird things)",
    "History Mysteries (strange but true moments in history)",
    "Space (mind-blowing facts about the universe)",
    "Animal Superpowers (incredible real animal abilities)",
]

TOPIC_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "series": {"type": "STRING"},
        "topic": {"type": "STRING"},
        "concept": {"type": "STRING"},
        "why_viral": {"type": "STRING"},
    },
    "required": ["series", "topic", "concept", "why_viral"],
}

DUP_SCHEMA = {
    "type": "OBJECT",
    "properties": {"duplicate": {"type": "BOOLEAN"}, "similar_to": {"type": "STRING"}},
    "required": ["duplicate", "similar_to"],
}

# ---------------- topic de-duplication ----------------
import difflib
import re as _re

_STOP = set("""a an the of to in on for and or is are was were be been being do does did if what why how when where
who which your you our we it its this that these those would could should will can just only really ever happens happen
happened make makes made feel feels get gets got into from with without about by at as than then so very most more one
day second seconds minute minutes earth's""".split())


def _words(text: str) -> set[str]:
    out = set()
    for w in _re.findall(r"[a-z0-9]+", text.lower()):
        if w in _STOP or len(w) < 3:
            continue
        for suf in ("ing", "ies", "es", "ed", "s"):  # crude stemming
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)] + ("y" if suf == "ies" else "")
                break
        out.add(w)
    return out


def lexical_duplicate(topic: str, concept: str, history: list[dict]) -> str:
    """Returns the previous topic this one duplicates (empty string if unique)."""
    tw, cw = _words(topic), _words(concept)
    for h in history:
        ht, hc = h.get("topic", ""), h.get("concept", "")
        hw, hcw = _words(ht), _words(hc)
        if cw and hcw and (cw == hcw or cw <= hw or hcw <= tw):
            return ht
        if tw and hw and len(tw & hw) / len(tw | hw) >= 0.5:
            return ht
        if difflib.SequenceMatcher(None, topic.lower(), ht.lower()).ratio() >= 0.75:
            return ht
    return ""


def semantic_duplicate(topic: str, history: list[dict]) -> str:
    """Ask Gemini whether the topic is essentially the same video as any previous one (best effort)."""
    if not history:
        return ""
    listing = "\n".join(f"- {h.get('topic', '')}" for h in history[-400:])
    prompt = (f"New YouTube Shorts topic: \"{topic}\"\n\nPrevious topics:\n{listing}\n\n"
              "Is the new topic essentially the SAME video as any previous topic (same core phenomenon or same "
              "hypothetical scenario, even if worded differently)? Different angles on a broad field (e.g. two "
              "different facts about the Moon) are NOT duplicates. Answer duplicate true/false and similar_to.")
    try:
        text, _ = gemini.call(prompt, DUP_SCHEMA, temperature=0.0, max_models=4)
        d = json.loads(text)
        return d.get("similar_to", "") or "(similar)" if d.get("duplicate") else ""
    except Exception as e:
        print(f"[Topic] semantic check skipped: {e}")
        return ""


def find_duplicate(topic: str, concept: str, history: list[dict]) -> str:
    return lexical_duplicate(topic, concept, history) or semantic_duplicate(topic, history)

SHORT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "hook_text": {"type": "STRING"},
        "characters": {
            "type": "ARRAY",
            "items": {"type": "OBJECT",
                      "properties": {"name": {"type": "STRING"}, "appearance": {"type": "STRING"}},
                      "required": ["name", "appearance"]},
        },
        "scenes": {
            "type": "ARRAY",
            "items": {"type": "OBJECT",
                      "properties": {"narration": {"type": "STRING"}, "image_prompt": {"type": "STRING"},
                                     "image_prompt_2": {"type": "STRING"}, "switch_word": {"type": "STRING"},
                                     "characters": {"type": "ARRAY", "items": {"type": "STRING"}}},
                      "required": ["narration", "image_prompt", "image_prompt_2", "switch_word", "characters"]},
        },
        "youtube_title": {"type": "STRING"},
        "youtube_description": {"type": "STRING"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "sources": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "hook_text", "characters", "scenes", "youtube_title", "youtube_description", "tags"],
}


VIRAL_PATTERNS = """Patterns of the most-viewed curiosity Shorts on YouTube (use them, never copy titles):
- danger / fear / survival ("the deadliest...", "what would kill you first...")
- extreme superlatives and scale ("the most powerful...", "bigger than...", "hotter than the Sun")
- unsolved mysteries, lost treasures, strange true events
- open scientific debates and controversial hypotheses (e.g. "is there a hidden Planet Nine?") - welcome, as
  long as the claim has not already been disproven
- catastrophic or mind-bending what-ifs (black holes, Earth changes, time travel)
- counter-intuitive facts about YOUR body that viewers can test or feel themselves
- weird animal abilities and predators
- rankings with numbers ("5 animals that...")
Avoid: abstract self-help / mindset content, dry definitions, topics that need long setup.
Never pick gruesome or morbid angles - YouTube shows them to far fewer people and they earn less: animals or pets
eating / attacking their owners, corpses or decomposition, cannibalism, gore and graphic injuries, torture,
suicide or self-harm, disturbing deaths of people or pets. A danger topic is fine when it is about the science of
surviving it (e.g. "what would kill you first at the bottom of the ocean"), not about the gore.
Never pick topics whose point is practical safety / survival / first-aid / medical advice that viewers might act on
in a real emergency ("how to escape a sinking car", "what to do if...", "how to survive a...", treating bites,
burns or poisoning): one wrong or outdated tip can hurt someone. Explain the science of a phenomenon instead,
without telling viewers what to do."""

ADVICE = re.compile(
    r"\b(how to|what to do|should you|escape|survive|survival tips?|first[- ]aid|treat(?:ing)?|cure|remedy|"
    r"save your life|stay alive)\b", re.I)


def is_advice(topic: str, concept: str = "") -> bool:
    """Topics framed as real-world safety / survival / medical instructions."""
    return bool(ADVICE.search(f"{topic} {concept}"))

MORBID = re.compile(
    r"\b(eat|eats|eating|ate|devour\w*)\b[^.?!]{0,30}\b(owner|owners|human|humans|people|person|corpse|body|bodies)\b"
    r"|\b(corpse|corpses|cadaver|decompos\w*|rotting|cannibal\w*|gore|gory|gruesome|torture\w*|suicide|self[- ]harm|"
    r"dismember\w*|mutilat\w*|disembowel\w*)\b", re.I)


def is_morbid(topic: str, concept: str = "") -> bool:
    return bool(MORBID.search(f"{topic} {concept}"))


def performance_summary(history: list[dict]) -> str:
    rows = [h for h in history if h.get("views") is not None]
    if not rows:
        return "(no data yet)"
    by_series: dict[str, list[int]] = {}
    for h in rows:
        by_series.setdefault(h.get("series") or "?", []).append(h["views"])
    lines = [f"- {k}: avg {sum(v) // len(v)} views over {len(v)} Shorts" for k, v in
             sorted(by_series.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))]
    best = sorted(rows, key=lambda h: -h["views"])[:5]
    lines.append("Best performers: " + "; ".join(f"{h['topic']} ({h['views']} views)" for h in best))
    worst = sorted(rows, key=lambda h: h["views"])[:3]
    lines.append("Weakest: " + "; ".join(f"{h['topic']} ({h['views']} views)" for h in worst))
    return "\n".join(lines)


def trends_summary(trends: list[dict], n: int = 30) -> str:
    def english(t: str) -> bool:
        return sum(c.isascii() for c in t) / max(len(t), 1) > 0.9
    good = [t for t in trends if english(t["title"]) and "#kids" not in t["title"].lower()][:n]
    return "\n".join(f"- {t['views']:,} views: {t['title']}" for t in good) or "(no trend data)"


# old series names -> current theme names (so our own stats can be grouped by theme)
THEME_ALIASES = {"what if": "Physics & What-Ifs", "space": "Space", "scary science": "Survival & Danger",
                 "psychology": "Psychology & Brain", "your body": "Human Body", "history mysteries": "History",
                 "animal superpowers": "Animals", "unsolved mysteries": "Mysteries & Unexplained"}


def normalize_theme(series: str) -> str:
    s = (series or "").strip()
    return THEME_ALIASES.get(s.lower(), s)


def proven_themes(history: list[dict], today: str = "", min_age_days: int = 2, top: int = 3) -> list[dict]:
    """Our own best themes: average views of Shorts that are at least `min_age_days` old (newer ones have not
    been shown to many people yet). [{theme, avg_views, count, examples}] best first."""
    from datetime import date, timedelta
    cutoff = (date.fromisoformat(today) if today else date.today()) - timedelta(days=min_age_days)
    groups: dict[str, list[dict]] = {}
    for h in history:
        theme = normalize_theme(h.get("series", ""))
        if not theme or h.get("views") is None or h.get("date", "9999") > cutoff.isoformat():
            continue
        groups.setdefault(theme, []).append(h)
    out = []
    for theme, rows in groups.items():
        rows.sort(key=lambda h: -h["views"])
        out.append({"theme": theme, "avg_views": sum(h["views"] for h in rows) // len(rows), "count": len(rows),
                    "examples": [f"{h.get('title', h.get('topic', ''))} ({h['views']:,} views on our channel)"
                                 for h in rows[:4]]})
    out.sort(key=lambda t: -t["avg_views"])
    return out[:top]


def need_proven(history: list[dict], per_week: int = 2) -> bool:
    """True when the last 6 Shorts contain fewer than `per_week` 'proven' picks, so every 7 consecutive
    Shorts include at least `per_week` Shorts from our best-performing themes."""
    return per_week > 0 and sum(1 for h in history[-6:] if h.get("mode") == "proven") < per_week


def pick_proven_theme(history: list[dict], today: str = "") -> dict | None:
    import random
    best = proven_themes(history, today)
    yesterday = normalize_theme(history[-1].get("series", "")) if history else ""
    pool = [t for t in best if t["theme"] != yesterday] or best
    if not pool:
        return None
    t = random.choices(pool, weights=[max(t["avg_views"], 1) for t in pool], k=1)[0]
    return {"theme": t["theme"], "median_views": t["avg_views"], "examples": t["examples"]}


def pick_topic(history: list[dict], series: list[str] | None = None, attempts: int = 6,
               trends: list[dict] | None = None, themes: list[dict] | None = None, cooldown: int = 7,
               proven_per_week: int = 2, today: str = "", exclude: list[dict] | None = None) -> dict:
    """Pick a topic guaranteed (lexical + semantic checks) not to overlap any previous Short.
    At least `proven_per_week` of every 7 Shorts come from our own best-viewed themes ("proven").
    Otherwise with `themes` (trend mode): today's theme is the most popular trending theme not used in the last
    `cooldown` days, and the topic is proposed inside it. Without themes: 70% exploit our best series, 30% explore.
    `exclude`: topics this run already dropped ({topic, concept, series}) because they could not be researched or
    checked. They are not proposed again, and a trend pick moves to another theme."""
    import random
    exclude = exclude or []
    theme = pick_proven_theme(history, today) if need_proven(history, proven_per_week) else None
    mode = "proven" if theme else ""
    if theme:
        trend = next((t for t in themes or [] if t["theme"] == theme["theme"]), None)
        if trend:  # what is hot in that theme on YouTube right now, plus our own winners
            theme["examples"] = theme["examples"] + trend["examples"][:4]
    else:
        dropped = {d.get("series", "") for d in exclude}
        others = [t for t in themes or [] if t["theme"] not in dropped]
        theme = pick_theme(others or themes, history, cooldown) if themes else None
        mode = "trend" if theme else ("exploit" if random.random() < 0.7 else "explore")
    print(f"[Topic] mode: {mode}" + (f" | theme: {theme['theme']} ({theme['median_views']:,} views)" if theme else ""))
    rejected: list[str] = [f"{d.get('topic', '')} (could not be verified)" for d in exclude]
    for _ in range(attempts):
        t = (_propose_in_theme(history, theme, rejected) if theme
             else _propose_topic(history, series, rejected, trends or [], mode))
        if is_advice(t["topic"], t.get("concept", "")):
            print(f"[Topic] 題目是求生／安全建議，換一個：{t['topic']}")
            rejected.append(t["topic"] + " (safety advice)")
            continue
        if is_morbid(t["topic"], t.get("concept", "")):
            print(f"[Topic] 題目太獵奇，換一個：{t['topic']}")
            rejected.append(t["topic"] + " (too morbid)")
            continue
        dup = find_duplicate(t["topic"], t.get("concept", ""), history + exclude)
        if not dup:
            t["mode"] = mode
            return t
        print(f"[Topic] 重複，換一個：{t['topic']} ≈ {dup}")
        rejected.append(t["topic"])
    raise RuntimeError("連續多次都選到重複主題，請在網頁排入新主題")


# ---------------- trending themes (what is hot on YouTube Shorts right now) ----------------
THEMES = ["Animals", "Ocean Life", "Insects & Bugs", "Pets", "Dinosaurs & Prehistoric Life", "Plants & Nature",
          "Space", "Earth & Geology", "Weather & Natural Disasters", "Human Body", "Psychology & Brain",
          "Health & Food Science", "Food Facts", "History", "Ancient Civilizations", "Mysteries & Unexplained",
          "Technology & Inventions", "Engineering & Megastructures", "Physics & What-Ifs", "Chemistry & Materials",
          "Geography & Countries", "Money & Economics", "Sports & Records", "Language & Words",
          "Optical Illusions & Perception", "Survival & Danger"]
LABEL_SCHEMA = {"type": "ARRAY", "items": {"type": "OBJECT",
                                           "properties": {"i": {"type": "INTEGER"}, "theme": {"type": "STRING"}},
                                           "required": ["i", "theme"]}}
_KIDS = ("#kids", "for kids", "kids learn", "nursery", "toddler", "preschool", "cocomelon")


def _english(t: str) -> bool:
    return sum(c.isascii() for c in t) / max(len(t), 1) > 0.9


def label_themes(trends: list[dict], min_count: int = 2) -> list[dict]:
    """Group trending Shorts into stable themes (Gemini labels every title with one of THEMES).
    Returns themes sorted by popularity: [{theme, count, median_views, examples}]. Kids content is ignored."""
    import statistics
    items = [t for t in trends if _english(t["title"]) and not any(k in t["title"].lower() for k in _KIDS)][:160]
    if not items:
        return []
    listing = "\n".join(f"{i}. {t['title'][:110]}" for i, t in enumerate(items))
    prompt = (f"Classify each YouTube Short title into exactly one theme from this list:\n{', '.join(THEMES)}\n"
              "Use \"Other\" only if nothing fits. Return [{i, theme}] for every title.\n\n" + listing)
    text, _ = gemini.call(prompt, LABEL_SCHEMA, temperature=0.0, max_models=4)
    groups: dict[str, list[dict]] = {}
    for row in json.loads(text):
        i, theme = row.get("i"), row.get("theme", "")
        if isinstance(i, int) and 0 <= i < len(items) and theme in THEMES:
            groups.setdefault(theme, []).append(items[i])
    out = []
    for theme, vids in groups.items():
        if len(vids) < min_count:
            continue
        vids.sort(key=lambda v: -v["views"])
        out.append({"theme": theme, "count": len(vids), "median_views": int(statistics.median(v["views"] for v in vids)),
                    "examples": [f"{v['title'][:90]} ({v['views']:,} views)" for v in vids[:6]]})
    return sorted(out, key=lambda t: -t["median_views"])


def pick_theme(themes: list[dict] | None, history: list[dict], cooldown: int = 7, top: int = 6) -> dict | None:
    """Today's theme: weighted pick among the most popular trending themes not used in the last `cooldown`
    Shorts (so the theme changes every day and many themes get tested)."""
    import math
    import random
    recent = {h.get("series", "") for h in history[-cooldown:]} if cooldown > 0 else set()
    pool = [t for t in (themes or []) if t["theme"] not in recent][:top]
    if not pool:
        return None
    weights = [math.sqrt(max(t["median_views"], 1)) * (1 + math.log10(t["count"])) for t in pool]
    return random.choices(pool, weights=weights, k=1)[0]


def _propose_in_theme(history: list[dict], theme: dict, rejected: list[str]) -> dict:
    recent = "\n".join(f"- {h.get('topic', '')} [{h.get('concept', '')}]" for h in history[-300:]) or "(none yet)"
    if rejected:
        recent += "\nAlso rejected just now (too similar to past videos):\n" + "\n".join(f"- {r}" for r in rejected)
    prompt = f"""You run a fast-growing English YouTube Shorts channel of surprising facts for a global audience
(teens and adults, NOT kids content). Today's theme is "{theme['theme']}" - one of the hottest themes on YouTube
Shorts right now. The most-viewed recent Shorts in this theme:
{chr(10).join('- ' + e for e in theme['examples'])}

Pick ONE new video topic inside this theme, inspired by what makes those videos popular but with a fresh,
original angle (never copy a title).

Rules:
- Must be factual / scientifically or historically accurate (hypotheticals must follow real science).
- Must have a strong curiosity hook that makes people stop scrolling in 1 second; a little-known fact beats a famous one.
- Do not put specific numbers, measurements or statistics in the topic (no "2-inch", "1,000 pounds", "millions of
  gallons"); they are not verified yet. A list count like "5 animals" is fine.
- Must NOT repeat or closely resemble any of these previous topics:
{recent}

{VIRAL_PATTERNS}

Return series = "{theme['theme']}" exactly, the topic phrased as the video question, the core concept
(1-4 lowercase words naming the exact subject, e.g. "octopus hearts", "hypnic jerk"), and why it will go viral."""
    text, _ = gemini.call(prompt, TOPIC_SCHEMA, temperature=1.0)
    t = json.loads(text)
    t["series"] = theme["theme"]
    return t


def _propose_topic(history: list[dict], series: list[str] | None, rejected: list[str],
                   trends: list[dict] | None = None, mode: str = "explore") -> dict:
    series = series or DEFAULT_SERIES
    recent = "\n".join(f"- {h.get('topic', '')} [{h.get('concept', '')}]" for h in history[-300:]) or "(none yet)"
    if rejected:
        recent += "\nAlso rejected just now (too similar to past videos):\n" + "\n".join(f"- {r}" for r in rejected)
    last_series = [h.get("series", "") for h in history[-6:]]
    prompt = f"""You run a fast-growing English YouTube Shorts channel about curiosity and science for a global
audience (teens and adults). Pick ONE new video topic for today.

Series to rotate between:
{chr(10).join('- ' + s for s in series)}

Rules:
- Must be factual / scientifically grounded (hypotheticals must follow real physics/biology).
- Must have a strong curiosity hook that makes people stop scrolling in 1 second.
- Do not put specific numbers, measurements or statistics in the topic (no "2-inch", "1,000 pounds", "millions of
  gallons"); they are not verified yet. A list count like "5 animals" is fine.
- Must NOT repeat or closely resemble any of these previous topics:
{recent}
- Recent series, newest last: {last_series}. Do not use the same series as the most recent Short.

Our channel's performance so far:
{performance_summary(history)}

Most-viewed similar Shorts on YouTube in the last 30 days:
{trends_summary(trends or [])}

{VIRAL_PATTERNS}

Today's strategy: {"EXPLOIT - choose a topic in the style/theme that is proven to get the most views (our best series and the YouTube-wide winners above), but with a fresh, original angle" if mode == "exploit" else "EXPLORE - try a promising series or theme we have not tested much yet, still using the viral patterns"}.
Return the series name (short form, e.g. "What If"), the topic phrased as the video question, the core concept
(1-4 lowercase words naming the exact phenomenon, e.g. "hypnic jerk", "earth stops spinning"), and why it will go viral."""
    text, _ = gemini.call(prompt, TOPIC_SCHEMA, temperature=1.0)
    return json.loads(text)


WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_HEADERS = {"User-Agent": "CloudFindsTheWorld-ShortsBot/1.0 (https://github.com/NTCloudy/ai-story-video)"}


def concept_keywords(concept: str) -> set[str]:
    """Content words of the core concept, e.g. "hairy frog claws" -> {"hairy", "frog", "claw"}."""
    return _words(concept)


def _mentions(text: str, keywords: set[str]) -> bool:
    return bool(keywords & _words(text))


def _wiki_search(q: str, pages: int, chars: int) -> list[str]:
    import requests
    r = requests.get(WIKI_API, headers=WIKI_HEADERS, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": q, "gsrlimit": pages,
        "prop": "extracts|info", "exintro": 1, "explaintext": 1, "inprop": "url"})
    r.raise_for_status()
    found = sorted((r.json().get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    return [f"[{p['title']}] ({p.get('fullurl', '')})\n{p.get('extract', '')[:chars]}" for p in found if p.get("extract")]


# The intro of an article often leaves out the one fact a Short is about. 11/25: the Toothpaste article explains
# why orange juice tastes bad after brushing in its body, not in its intro, and three drafts were rejected for
# saying so. The notes therefore also carry the body paragraphs that are about the concept, as long as the notes
# stay within NOTES_LIMIT, the part of the notes the last check reads.
NOTES_LIMIT = 12000
BODY_PARAGRAPHS = 2          # per article
BODY_PARAGRAPH_CHARS = 800


def _wiki_body(title: str) -> str:
    """Plain text of one whole article (the search only returns intros)."""
    import requests
    r = requests.get(WIKI_API, headers=WIKI_HEADERS, timeout=30, params={
        "action": "query", "format": "json", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": title})
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages", {})
    return next(iter(pages.values()), {}).get("extract", "") or ""


def _trim_paragraph(p: str, keys: set[str], chars: int) -> str:
    """A long paragraph is cut to whole sentences, starting at the first sentence that mentions the concept."""
    if len(p) <= chars:
        return p
    sentences = re.split(r"(?<=[.!?])\s+", p)
    while len(sentences) > 1 and not keys & _words(sentences[0]):
        sentences.pop(0)
    out = sentences[0][:chars]
    for s in sentences[1:]:
        if len(out) + 1 + len(s) > chars:
            break
        out += " " + s
    return out


def concept_paragraphs(body: str, keys: set[str], skip: str = "", limit: int = BODY_PARAGRAPHS,
                       chars: int = BODY_PARAGRAPH_CHARS) -> list[str]:
    """Paragraphs of an article that are about the concept: they mention at least two of its keywords (or its
    only keyword). Best matches first, then article order. `skip` is text the notes already have (the intro)."""
    need = min(2, len(keys))
    if not need:
        return []
    found = []
    for n, p in enumerate(body.split("\n")):
        p = p.strip()
        if len(p) < 80 or p.startswith("=") or p[:80] in skip:
            continue
        hits = len(keys & _words(p))
        if hits >= need:
            found.append((-hits, n, p))
    return [_trim_paragraph(p, keys, chars) for _, _, p in sorted(found)[:limit]]


def _body_paragraphs(note: str, keys: set[str], room: int) -> list[str]:
    """The paragraphs to add to one "[Title] (url)\\nintro" note, at most `room` characters in total.
    Best effort: when the article cannot be read, the note keeps its intro only."""
    try:
        title = note[1:note.index("] (")]
        found = concept_paragraphs(_wiki_body(title), keys, skip=note)
    except Exception as e:
        print(f"[Research] article body skipped: {str(e)[:120]}")
        return []
    kept = []
    for p in found:
        if len(p) + 1 > room:
            break
        kept.append(p)
        room -= len(p) + 1
    if kept:
        print(f"[Research] {title}: {len(kept)} more paragraphs about the concept from the article body")
    return kept


def search_words(topic: str, limit: int = 8) -> str:
    """Wikipedia query for a question when no keywords are available: its content words OR-ed together.
    The full question ("Why Do Rocket Launch Pads ...?") usually finds nothing."""
    out = []
    for w in _re.findall(r"[a-z][a-z'-]+", topic.lower()):
        w = w.strip("'-")
        if len(w) >= 3 and w not in _STOP and w not in out:
            out.append(w)
    return " OR ".join(out[:limit]) or topic


def wikipedia_notes(topic: str, pages: int = 3, chars: int = 2500, concept: str = "") -> str:
    """Free, reliable research source: intro sections of the most relevant Wikipedia articles, plus the body
    paragraphs of those articles that are about the core concept.
    Articles that never mention the core concept are dropped, so a vague question ("this animal") cannot
    pull in an unrelated subject."""
    try:
        q, _ = gemini.call(f"Give 2-4 English Wikipedia search keywords (just the words, no quotes) for: {topic}"
                           + (f" (core concept: {concept})" if concept else ""), temperature=0.0, max_models=3)
        q = q.strip().splitlines()[0][:100]
    except Exception:
        q = concept or search_words(topic)  # the concept names the exact phenomenon; the question can be vague
    keys = concept_keywords(concept)
    notes = _wiki_search(q, pages, chars)
    if keys:
        notes = [n for n in notes if _mentions(n, keys)]
        if not notes and q != concept:
            notes = [n for n in _wiki_search(concept, pages, chars) if _mentions(n, keys)]
        room = NOTES_LIMIT - len("\n\n".join(notes))
        for i, note in enumerate(notes):
            extra = _body_paragraphs(note, keys, room)
            room -= sum(len(p) + 1 for p in extra)
            notes[i] = "\n".join([note] + extra)
    return "\n\n".join(notes)


def research(topic: str, concept: str = "") -> str:
    """Collect verified facts: Wikipedia first (free), then Google Search grounding if available."""
    try:
        notes = wikipedia_notes(topic, concept=concept)
        if notes:
            articles = re.findall(r"^\[.+\] \(", notes, flags=re.M)  # note headers; the text can contain "["
            print(f"[Research] Wikipedia: {len(articles)} articles")
            return notes
        print("[Research] Wikipedia had no article about the topic")
    except Exception as e:
        print(f"[Research] Wikipedia failed: {e}")
    prompt = (f"Research this YouTube Shorts topic and list 8-12 accurate, surprising, verifiable facts with "
              f"numbers where possible, plus the source website for each fact. Topic: {topic}"
              + (f" (core concept: {concept})" if concept else ""))
    try:
        text, model = gemini.call(prompt, search=True, temperature=0.2, max_models=2)
        print(f"[Research] facts collected with {model}")
        return text
    except Exception as e:
        print(f"[Research] skipped: {e}")
        return ""


def write_short(topic: str, facts: str = "", series: str = "", concept: str = "", feedback: str = "") -> dict:
    prompt = f"""Write a YouTube Shorts script (35-50 seconds when narrated) for this topic:
"{topic}" (series: {series or 'curiosity'}).
{f'The video MUST be about exactly this: {concept}. Name it in the narration.' if concept else ''}
{f'A previous draft was rejected: {feedback}. Fix that.' if feedback else ''}
Verified research notes (use ONLY facts consistent with these; never invent numbers; ignore any note that is
not about the topic above):
{facts or '(no notes - use only well-established, widely known facts)'}

Requirements:
1. 5 or 6 scenes. Total narration 95-125 English words. Short punchy sentences, conversational, energetic.
2. Scene 1 narration = the hook: a bold question or shocking statement in under 12 words. No greetings,
   no "in this video", no channel name.
3. Build curiosity scene by scene; put the most surprising fact near the end; last scene ends with a
   satisfying twist or takeaway plus a very short call to action like "Follow for more what-ifs."
4. hook_text: 3-6 word on-screen title shown during the first seconds (e.g. "NO MOON FOR 1 DAY?").
5. Pictures follow the narration, not a timer: a picture should stay on screen while the narration talks about
   it, typically 3-6 seconds. image_prompt = what the viewer should see while the scene's narration starts.
   Every scene with 15 or more words MUST also have image_prompt_2 = the new thing the narration moves on to (a new
   object, place, scale or consequence) and switch_word = the exact word of the narration where that new picture
   should appear (at least 5 words into the scene). Only scenes under 15 words use empty strings for
   image_prompt_2 and switch_word. Every picture must look clearly different from the one before it
   (different subject, place, scale or moment) - never two near-identical images. Each is a striking, cinematic
   VERTICAL 9:16 image matching its part of the narration - subject, setting, action, camera angle, lighting.
   Vary the camera (extreme wide, aerial, first-person POV, close-up, macro, cutaway diagram-like view) and never
   show a person just standing in the middle facing the camera. Scene 1's first image must be the most
   eye-catching picture of the whole video. Do NOT include any art style words and no text in the image.
   Avoid things image AIs draw badly or confusingly: reflections of scenes inside helmet visors or eyes, empty
   suits or helmets, books / letters / manuscripts / signs / screens with writing, close-up hands, and
   metaphorical or surreal mash-ups. Keep each picture literal and instantly readable.
   Never ask for graphic or medical pictures: no wounds, blood, burns, rashes, blisters, welts, sores, lesions,
   skin irritation or skin diseases, injuries or surgery. Show the cause instead (the plant, the substance, the
   animal, the place) or a person seen from a distance.
6. characters: always [] - this channel does not use recurring characters. When a person is needed, describe
   them generically inside that image_prompt (e.g. "a tiny astronaut silhouette falling", "a diver seen from below"),
   and prefer showing the phenomenon itself.
7. title: short internal title. youtube_title: under 70 characters, curiosity-driven, ends with " #shorts".
   youtube_description: 2 sentences + 4 relevant hashtags. tags: 10-15 search keywords.
8. sources: up to 3 source websites used.
9. Must be accurate, family-friendly, and original. Hypotheticals must be clearly framed as hypothetical.
   Never give viewers safety, survival, first-aid, medical or "what to do" instructions (no "you must...",
   "break the window", "wait until..."); explain why something happens, not how to act in an emergency.
   Never turn a theoretical possibility into a claim in the title or hook (say "could", not "will kill you").
10. Never overstate science: no pop-science myths, no "scientists proved" unless the notes say so, use
    "may", "scientists think" for uncertain claims. sources: list the Wikipedia URLs you actually used.
11. Every specific number, percentage, date, record or superlative ("the longest", "the first"), every vague
    magnitude ("millions of", "hundreds of thousands of") and every technical term must appear in the research
    notes (the topic's own numbers were NOT verified - drop them unless the notes have them) - if the notes do not have it, leave it out or say it
    without the number. Never invent names for effects. Never state anecdotes as proven science.
12. Unsolved mysteries, controversies and debated hypotheses are welcome: present them as open questions or
    competing theories. Never present a claim that has already been disproven or debunked as true or possible
    (e.g. hoaxes, fake photos, refuted theories); if you mention one, say clearly that it was debunked."""
    text, model = gemini.call(prompt, SHORT_SCHEMA, temperature=0.9)
    data = json.loads(text)
    data["scenes"] = [s for s in data.get("scenes", []) if s.get("narration", "").strip()]
    if not data["scenes"]:
        raise RuntimeError("Gemini returned no scenes")
    data["model"] = model
    data["topic"] = topic
    data["series"] = series
    return data


# ---------------- graphic picture prompts ----------------
# 11/18: "raised, reddened skin irritation and dermatitis welts on a forearm" was drawn as raw open wounds
GRAPHIC = re.compile(
    r"\b(wounds?|wounded|lesions?|rash(es)?|blisters?|blistering|welts?|dermatitis|eczema|ulcers?|pus|scabs?|"
    r"gangrene|necro\w*|sores?|bleeding|bloody|blood[- ]?soaked|gore|gory|corpses?|injur(y|ies|ed)|mutilat\w*|"
    r"severed|surgery|surgical|infected|burn(ed|t)? skin|skin (irritation|disease|infection|condition|burns?)|"
    r"open flesh|raw flesh)\b", re.I)


def graphic_prompts(sb: dict) -> list[str]:
    """Picture prompts asking for wounds, rashes, blood or other medical close-ups."""
    out = []
    for i, sc in enumerate(sb.get("scenes", []), 1):
        for key in ("image_prompt", "image_prompt_2"):
            m = GRAPHIC.search(sc.get(key) or "")
            if m:
                out.append(f"scene {i} {key}: '{m.group(0)}'")
    return out


# ---------------- deterministic figure check ----------------
# Gemini's claims check (lite model first) passed "millions of gallons" and "hundreds of thousands of galaxies"
# when the notes said nothing / "approximately 100,000". Every figure must be backed by a number in the notes.
_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
          "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUMWORD = {**{w: i for i, w in enumerate(_UNITS)}, **_TENS}
_NW = "|".join(sorted(list(_NUMWORD) + ["hundred", "point", "a", "half"], key=len, reverse=True))
_WORDRUN = rf"(?:{_NW})(?:[\s-]+(?:and[\s-]+)?(?:{_NW}))*"
# vague magnitudes -> (low, high): "hundreds of thousands" means at least 200,000, so "about 100,000" is not enough
_VAGUE = [
    ("hundreds of thousands", 2e5, 1e6), ("tens of thousands", 2e4, 1e5),
    ("hundreds of millions", 2e8, 1e9), ("tens of millions", 2e7, 1e8),
    ("hundreds of billions", 2e11, 1e12), ("tens of billions", 2e10, 1e11),
    ("trillions", 2e12, 1e15), ("billions", 2e9, 1e12), ("millions", 2e6, 1e9),
    ("thousands", 2e3, 1e6), ("hundreds", 200, 1e3),
]
_UNIT_RE = (r"%|percent|x\b|times|inch|inches|in\b|foot|feet|ft|yards?|meters?|metres?|cm|mm|km|kilometers?|"
            r"kilometres?|miles?|mph|km/h|pounds?|lbs?|kg|kilograms?|grams?|tons?|tonnes?|degrees?|°|gallons?|"
            r"liters?|litres?|psi|atm|seconds?|minutes?|hours?|days?|weeks?|months?|years?|decades?|centuries|"
            r"century|light[- ]years?|volts?|watts?|decibels?|db\b|hz")
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_FIG = re.compile(
    r"(?P<vague>" + "|".join(v[0] for v in _VAGUE) + r")\b"
    r"|(?<![\w.,/:])(?P<num>" + _NUM + r")(?![\w,]*\d)(?P<ord>st|nd|rd|th)?\b"
    r"(?:\s*(?P<pct>%|percent))?(?:[\s-]*(?P<sc>thousand|million|billion|trillion)\b)?"
    # spelled out for the voice: "two hundred fifty million", "one point two billion", "forty percent"
    rf"|\b(?P<word>{_WORDRUN})(?:[\s-]+(?P<wsc>thousand|million|billion|trillion)\b"
    rf"|(?=[\s-]+(?:{_UNIT_RE})\b))",
    re.I)
_UNIT = re.compile(rf"^[\s-]*({_UNIT_RE})", re.I)
# unit spellings and abbreviations compared as one word ("60,000 ft" backs "thousands of feet")
_ALIAS = {"ft": "foot", "feet": "foot", "km": "kilometer", "kilometre": "kilometer", "kilometres": "kilometer",
          "kilometers": "kilometer", "m": "meter", "metre": "meter", "metres": "meter", "meters": "meter",
          "lb": "pound", "lbs": "pound", "pounds": "pound", "mi": "mile", "miles": "mile", "kg": "kilogram",
          "kilograms": "kilogram", "litre": "liter", "litres": "liter", "liters": "liter", "gallons": "gallon",
          "tonnes": "ton", "tonne": "ton", "tons": "ton", "yrs": "year", "years": "year"}


def _words_to_number(run: str) -> float | None:
    toks = [t for t in re.split(r"[\s-]+", run.lower()) if t and t != "and"]
    total, decimals, frac = 0.0, None, False
    for t in toks:
        if t == "point":
            decimals = ""
        elif decimals is not None:
            if t not in _NUMWORD or _NUMWORD[t] > 9:
                return None
            decimals += str(_NUMWORD[t])
        elif t == "half":
            frac = True
        elif t == "a":
            total = total or (0 if frac else 1)
        elif t == "hundred":
            total = (total or 1) * 100
        else:
            total += _NUMWORD[t]
    if frac:
        total = (total or 1) * 0.5
    if decimals:
        total += float("0." + decimals)
    return total or None


def _context(text: str, n: int = 3) -> set[str]:
    """First content words of a text, unit abbreviations normalised ("ft" -> "foot")."""
    out = set()
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in ("of", "the", "a", "an", "about", "some", "over", "up", "to", "and", "per", "in"):
            continue
        w = _ALIAS.get(w, w)
        out |= _words(w) or {w}
        if len(out) >= n:
            break
    return out


def _figures(text: str) -> list[tuple[str, float, float, str, str]]:
    """(phrase, low, high, vague_key, following_text) for every figure in the text. Exact numbers have
    low == high and key ""."""
    text = re.sub(r"https?://\S+", " ", text)
    out = []
    for m in _FIG.finditer(text):
        end = text[m.end():m.end() + 40]
        if m.group("vague"):
            key = m.group("vague").lower()
            lo, hi = next((lo, hi) for v, lo, hi in _VAGUE if v == key)
            nxt = re.match(r"\s+(?:of\s+)?[A-Za-z]+", end)
            out.append((m.group(0) + (nxt.group(0) if nxt else ""), lo, hi, key, end))
            continue
        if m.group("word"):
            v = _words_to_number(m.group("word"))
            if v is None:
                continue
            unit = None
            if m.group("wsc"):
                v *= _SCALE[m.group("wsc").lower()]
            else:
                unit = _UNIT.match(end)
                if v <= 10 and not (unit and unit.group(1).lower() in ("%", "percent")):
                    continue  # "two years", "three times": small counts, as for digits
            if v in (0, 1):
                continue
            out.append((m.group(0) + (unit.group(0) if unit else ""), v, v, "", end))
            continue
        if m.group("ord"):
            continue  # "the 3rd", "20th century"
        v = float(m.group("num").replace(",", ""))
        if m.group("sc"):
            v *= _SCALE[m.group("sc").lower()]
        unit = _UNIT.match(end)
        if not (m.group("pct") or m.group("sc")) and v <= 10 and v == int(v) and not unit:
            continue  # small counts ("5 animals", "3 hearts") are not measurements
        if v in (0, 1):
            continue
        out.append((m.group(0) + (unit.group(0) if unit and not m.group("sc") else ""), v, v, "", end))
    return out


HYPOTHETICAL = re.compile(
    r"\b(what if|what would (\w+ )?happen|what (\w+ )?happens if|imagine|hypothetical(ly)?|if you could)\b", re.I)


def unsupported_figures(text: str, facts: str, tolerance: float = 0.1, premise: str = "") -> list[str]:
    """Figures in text that no number in the research notes backs. An exact figure needs a notes number within
    10 % (rounding); a vague magnitude needs a notes number inside its range about the same thing (one of its
    next words), or the same wording in the notes. `premise`: a what-if topic whose own figures are the
    hypothetical setup ("a baseball at 90% light speed"), not claims, so they are allowed."""
    known = _figures(facts) + (_figures(premise) if premise and HYPOTHETICAL.search(premise) else [])
    values = [(lo, after) for _, lo, hi, key, after in known if not key]
    vague_in_notes = {k[3] for k in known if k[3]}
    bad = []
    for phrase, lo, hi, key, after in _figures(text):
        if key:
            # "millions of gallons" needs a notes number in range that is about gallons, not "520 million years";
            # the thing counted can come after a modifier ("thousands of tiny zooids")
            noun = _context(after, 3)
            ok = key in vague_in_notes or any(lo <= f < hi and (not noun or noun & _context(a, 4))
                                              for f, a in values)
        else:
            tol = 0 if re.fullmatch(r"1\d{3}s?|20\d{2}s?", phrase) else tolerance  # years must match exactly
            ok = any(abs(lo - f) <= tol * max(abs(lo), abs(f)) for f, _ in values)
        if not ok and phrase not in bad:
            bad.append(phrase)
    return bad


def notes_figures(facts: str, n: int = 15) -> str:
    vals = [k[0] for k in _figures(facts) if not k[3]]
    return ", ".join(dict.fromkeys(vals[:n])) or "none"


def ground_topic(topic: str, concept: str, facts: str) -> str:
    """The topic is picked before research, so it can carry figures nobody checked (e.g. "2-Inch Hole",
    "1,000 Pounds of Force"). After research, rewrite it without them so the script is not tied to them."""
    bad = unsupported_figures(topic, facts, premise=topic) if facts else []
    if not bad:
        return topic
    prompt = f"""Rewrite this YouTube Shorts video question. Keep the same subject and curiosity hook, but remove
these figures because the research notes do not support them: {bad}. Use a number only if it appears in the
research notes. Return only the new question, nothing else.
Question: {topic}
{f'Core concept: {concept}' if concept else ''}
Research notes:
{facts[:6000]}"""
    try:
        new, _ = gemini.call(prompt, temperature=0.3, max_models=3)
        new = new.strip().splitlines()[0].strip().strip('"').strip()
    except Exception as e:
        print(f"[Topic] could not remove unsupported figures {bad}: {str(e)[:120]}")
        return topic
    if new and not unsupported_figures(new, facts):
        print(f"[Topic] removed unsupported figures {bad}: {new}")
        return new
    print(f"[Topic] rewrite still has unsupported figures, keeping the original: {new}")
    return topic


CONSISTENCY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "script_matches_topic": {"type": "BOOLEAN"},
        "title_matches_script": {"type": "BOOLEAN"},
        "claims_supported": {"type": "BOOLEAN"},
        "reason": {"type": "STRING"},
    },
    "required": ["script_matches_topic", "title_matches_script", "reason"],
}


def check_consistency(sb: dict, topic: str, concept: str = "", facts: str = "") -> tuple[bool, str]:
    """Pre-upload gate: the narration must be about the chosen topic, and the title / hook / description must
    describe what the narration actually says. Returns (ok, reason)."""
    narration = " ".join(s.get("narration", "") for s in sb.get("scenes", []))
    packaging = f"{sb.get('youtube_title', '')} {sb.get('hook_text', '')} {sb.get('youtube_description', '')}"
    keys = concept_keywords(concept)
    if keys and not _mentions(narration, keys):
        return False, f"narration never mentions the concept '{concept}'"
    if keys and not _mentions(packaging, keys) and not (_words(sb.get("youtube_title", "")) & _words(narration)):
        return False, "title / hook / description share nothing with the narration or the concept"
    graphic = graphic_prompts(sb)
    if graphic:
        reason = (f"graphic medical pictures requested ({'; '.join(graphic)}). Show the cause instead (the plant, "
                  f"substance, animal or place) or a person from a distance - no wounds, rashes, blood or sick skin")
        print(f"[Check] pictures: {reason}")
        return False, reason
    if facts:
        bad = unsupported_figures(f"{packaging} {narration}", facts, premise=topic)
        if bad:
            reason = (f"figures not in the research notes: {', '.join(repr(b) for b in bad)}. Leave them out or "
                      f"use only figures the notes give ({notes_figures(facts)})")
            print(f"[Check] figures: {reason}")
            return False, reason
    notes_block = (f"Research notes (the only allowed source of specific claims):\n{facts[:NOTES_LIMIT]}"
                   if facts else "")
    claims_rule = ("false if the title, hook, description or narration contains a specific number, percentage, date, "
                   "record or superlative (\"the longest\", \"the loudest\"), named effect / technical term, or a "
                   "claim stated as settled fact that the research notes do not support (or contradict). Common "
                   "general knowledge is fine; debated ideas are fine when framed as possibilities. Otherwise true."
                   if facts else "always true.")
    prompt = f"""You are the last check before a YouTube Short is published. Be strict.
Planned topic: {topic}
{f'Core concept: {concept}' if concept else ''}
YouTube title: {sb.get('youtube_title', '')}
On-screen hook: {sb.get('hook_text', '')}
Description: {sb.get('youtube_description', '')}
Narration: {narration}
{notes_block}

script_matches_topic: true only if the narration is mainly about the planned topic / concept. Judge the subject
only: the narration may leave out or correct numbers and measurements in the planned topic (they were not verified).
title_matches_script: true only if the title, hook and description accurately describe what the narration is
about (no different subject, no promise the narration does not deliver).
claims_supported: {claims_rule}
reason: one short sentence explaining any false (quote the unsupported claim)."""
    try:
        text, model = gemini.call(prompt, CONSISTENCY_SCHEMA, temperature=0.0, lite_first=True)
    except Exception as e:
        # never publish unverified: stop and let the next run try again
        raise RuntimeError(f"無法確認標題和內容是否相符（Gemini 無法使用）：{str(e)[:200]}") from e
    v = json.loads(text)
    ok = bool(v.get("script_matches_topic")) and bool(v.get("title_matches_script")) \
        and (not facts or v.get("claims_supported", True) is not False)
    print(f"[Check] topic={v.get('script_matches_topic')} title={v.get('title_matches_script')}"
          f" claims={v.get('claims_supported')} ({model})"
          + ("" if ok else f": {v.get('reason', '')}"))
    return ok, v.get("reason", "")
