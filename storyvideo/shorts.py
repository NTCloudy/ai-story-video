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
        "why_viral": {"type": "STRING"},
    },
    "required": ["series", "topic", "why_viral"],
}

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
                                     "characters": {"type": "ARRAY", "items": {"type": "STRING"}}},
                      "required": ["narration", "image_prompt", "characters"]},
        },
        "youtube_title": {"type": "STRING"},
        "youtube_description": {"type": "STRING"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "sources": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "hook_text", "characters", "scenes", "youtube_title", "youtube_description", "tags"],
}


def pick_topic(history: list[str], series: list[str] | None = None) -> dict:
    series = series or DEFAULT_SERIES
    recent = "\n".join(f"- {t}" for t in history[-120:]) or "(none yet)"
    prompt = f"""You run a fast-growing English YouTube Shorts channel about curiosity and science for a global
audience (teens and adults). Pick ONE new video topic for today.

Series to rotate between:
{chr(10).join('- ' + s for s in series)}

Rules:
- Must be factual / scientifically grounded (hypotheticals must follow real physics/biology).
- Must have a strong curiosity hook that makes people stop scrolling in 1 second.
- Must NOT repeat or closely resemble any of these previous topics:
{recent}
- Prefer the series that was used least recently.
Return the series name (short form, e.g. "What If"), the topic phrased as the video question, and why it will go viral."""
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
   satisfying twist or takeaway plus a very short call to action like "Follow for more what-ifs."
4. hook_text: 3-6 word on-screen title shown during the first seconds (e.g. "NO MOON FOR 1 DAY?").
5. image_prompt (English) for each scene: a striking, cinematic VERTICAL 9:16 image matching the narration -
   subject, setting, action, camera angle, lighting. Do NOT include any art style words and no text in the image.
   If a recurring character appears, refer to it by name only.
6. characters: only if a recurring character/person is needed (max 2), with a detailed fixed appearance; else [].
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
