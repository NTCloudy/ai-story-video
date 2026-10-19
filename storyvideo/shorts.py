"""English curiosity / science Shorts: topic picking, fact research and script writing."""

from __future__ import annotations

import json

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
                                     "image_prompt_2": {"type": "STRING"},
                                     "characters": {"type": "ARRAY", "items": {"type": "STRING"}}},
                      "required": ["narration", "image_prompt", "image_prompt_2", "characters"]},
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
- catastrophic or mind-bending what-ifs (black holes, Earth changes, time travel)
- counter-intuitive facts about YOUR body that viewers can test or feel themselves
- weird animal abilities and predators
- rankings with numbers ("5 animals that...")
Avoid: abstract self-help / mindset content, dry definitions, topics that need long setup."""


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


def pick_topic(history: list[dict], series: list[str] | None = None, attempts: int = 6,
               trends: list[dict] | None = None) -> dict:
    """Pick a topic guaranteed (lexical + semantic checks) not to overlap any previous Short.
    70% of days exploit proven high-view patterns (own stats + YouTube-wide trends), 30% explore."""
    import random
    mode = "exploit" if random.random() < 0.7 else "explore"
    print(f"[Topic] mode: {mode}")
    rejected: list[str] = []
    for _ in range(attempts):
        t = _propose_topic(history, series, rejected, trends or [], mode)
        dup = find_duplicate(t["topic"], t.get("concept", ""), history)
        if not dup:
            return t
        print(f"[Topic] 重複，換一個：{t['topic']} ≈ {dup}")
        rejected.append(t["topic"])
    raise RuntimeError("連續多次都選到重複主題，請在網頁排入新主題")


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
- Must NOT repeat or closely resemble any of these previous topics:
{recent}
- Recent series, newest last: {last_series}. Do not use the same series 3 days in a row.

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


def wikipedia_notes(topic: str, pages: int = 3, chars: int = 2500) -> str:
    """Free, reliable research source: intro sections of the most relevant Wikipedia articles."""
    import requests
    try:
        q, _ = gemini.call(f"Give 2-4 English Wikipedia search keywords (just the words, no quotes) for: {topic}",
                           temperature=0.0, max_models=3)
        q = q.strip().splitlines()[0][:100]
    except Exception:
        q = topic
    r = requests.get(WIKI_API, headers=WIKI_HEADERS, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": q, "gsrlimit": pages,
        "prop": "extracts|info", "exintro": 1, "explaintext": 1, "inprop": "url"})
    r.raise_for_status()
    found = sorted((r.json().get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    notes = [f"[{p['title']}] ({p.get('fullurl', '')})\n{p.get('extract', '')[:chars]}" for p in found if p.get("extract")]
    return "\n\n".join(notes)


def research(topic: str) -> str:
    """Collect verified facts: Wikipedia first (free), then Google Search grounding if available."""
    try:
        notes = wikipedia_notes(topic)
        if notes:
            print(f"[Research] Wikipedia: {notes.count('[')} articles")
            return notes
    except Exception as e:
        print(f"[Research] Wikipedia failed: {e}")
    prompt = (f"Research this YouTube Shorts topic and list 8-12 accurate, surprising, verifiable facts with "
              f"numbers where possible, plus the source website for each fact. Topic: {topic}")
    try:
        text, model = gemini.call(prompt, search=True, temperature=0.2, max_models=2)
        print(f"[Research] facts collected with {model}")
        return text
    except Exception as e:
        print(f"[Research] skipped: {e}")
        return ""


def write_short(topic: str, facts: str = "", series: str = "") -> dict:
    prompt = f"""Write a YouTube Shorts script (35-50 seconds when narrated) for this topic:
"{topic}" (series: {series or 'curiosity'}).

Verified research notes (use ONLY facts consistent with these; never invent numbers):
{facts or '(no notes - use only well-established, widely known facts)'}

Requirements:
1. 5 or 6 scenes. Total narration 95-125 English words. Short punchy sentences, conversational, energetic.
2. Scene 1 narration = the hook: a bold question or shocking statement in under 12 words. No greetings,
   no "in this video", no channel name.
3. Build curiosity scene by scene; put the most surprising fact near the end; last scene ends with a
   satisfying twist. Make it LOOP: the final sentence should lead naturally back into the opening hook, so a
   viewer who keeps watching hears the hook again and it still makes sense. No call to action, no "follow for more".
4. hook_text: 3-6 word on-screen title shown during the first seconds (e.g. "NO MOON FOR 1 DAY?").
5. Two images per scene, so the picture changes every few seconds: image_prompt for the first half of the
   narration and image_prompt_2 for the second half. Make the two shots clearly different (e.g. wide establishing
   shot -> dramatic close-up, a different angle, a reaction, or the consequence) while keeping the same subject and
   setting so they feel continuous. Each is a striking, cinematic VERTICAL 9:16 image matching its part of the
   narration - subject, setting, action, camera angle, lighting. Vary the camera all the time (extreme wide,
   aerial, first-person POV, close-up, macro, cutaway diagram-like view); never repeat a framing in a row and never
   show a person just standing in the middle facing the camera. Scene 1's first image must be the most
   eye-catching picture of the whole video. Do NOT include any art style words and no text in the image.
6. characters: always [] - this channel does not use recurring characters. When a person is needed, describe
   them generically inside that image_prompt (e.g. "a tiny astronaut silhouette falling", "a diver seen from below"),
   and prefer showing the phenomenon itself.
7. title: short internal title. youtube_title: under 70 characters, curiosity-driven, ends with " #shorts".
   youtube_description: 2 sentences + 4 relevant hashtags. tags: 10-15 search keywords.
8. sources: up to 3 source websites used.
9. Must be accurate, family-friendly, and original. Hypotheticals must be clearly framed as hypothetical.
10. Never overstate science: no pop-science myths, no "scientists proved" unless the notes say so, use
    "may", "scientists think" for uncertain claims. sources: list the Wikipedia URLs you actually used."""
    text, model = gemini.call(prompt, SHORT_SCHEMA, temperature=0.9)
    data = json.loads(text)
    data["scenes"] = [s for s in data.get("scenes", []) if s.get("narration", "").strip()]
    if not data["scenes"]:
        raise RuntimeError("Gemini returned no scenes")
    data["model"] = model
    data["topic"] = topic
    data["series"] = series
    return data
