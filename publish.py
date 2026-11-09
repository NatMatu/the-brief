#!/usr/bin/env python3
"""Turn a brief note into an episode and publish the private podcast feed.

Usage: python3 publish.py <path to Brief/Briefs/YYYY-MM-DD.md>

Reads config.json next to this file:
  base_url  - where GitHub Pages serves this folder, e.g. https://<user>.github.io/<repo>
  voice     - macOS voice name; falls back to Daniel if not installed
  keep      - how many episodes stay in the feed (older ones are deleted)
"""
import json, re, subprocess, sys, datetime, html
from pathlib import Path
from email.utils import format_datetime

HERE = Path(__file__).resolve().parent
EP = HERE / "episodes"
CFG = json.loads((HERE / "config.json").read_text())


def speakable(md: str) -> str:
    s = re.sub(r"(?s)^---.*?---\n", "", md, count=1)      # frontmatter
    s = s.split("\n---\n")[0]                              # footer is not read aloud
    s = re.sub(r"(?s)## Read in full.*", "", s)            # links section is not read aloud
    s = re.sub(r"!\[\[[^\]]*\]\]", "", s)                  # embeds
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)         # links -> text
    s = re.sub(r"^#+ (.*)$", r"\1.\n", s, flags=re.M)      # headings -> spoken pause
    s = re.sub(r"[*_`]", "", s)
    s = s.replace("—", ", ").replace("–", " to ")
    s = re.sub(r"^\s*-\s+", "", s, flags=re.M)
    return s.strip() + "\n\nThat's the brief. The links are in the written version."


def inline(t: str) -> str:
    t = html.escape(t, quote=False)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    return t.replace("`", "")


def show_notes(md: str) -> str:
    """The written brief as simple HTML, for the episode's show notes. Footer included, small."""
    s = re.sub(r"(?s)^---.*?---\n", "", md, count=1)
    s = re.sub(r"!\[\[[^\]]*\]\]", "", s)
    body, _, footer = s.partition("\n---\n")
    out, in_list = [], False
    for line in body.splitlines():
        line = line.rstrip()
        if line.startswith("# "):
            continue                                       # the episode title already says it
        if re.match(r"^\s*-\s+", line):
            if not in_list:
                out.append("<ul>"); in_list = True
            item = inline(re.sub(r"^\s*-\s+", "", line))
            out.append(f"<li>{item}</li>")
            continue
        if in_list:
            out.append("</ul>"); in_list = False
        if line.startswith("## "):
            out.append(f"<h3>{inline(line[3:])}</h3>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    if footer.strip():
        out.append(f"<p><small>{inline(footer.strip())}</small></p>")
    return "\n".join(out)


def voice() -> str:
    want = CFG.get("voice", "Daniel")
    have = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    return want if any(l.startswith(want) for l in have.splitlines()) else "Daniel"


def duration(p: Path) -> int:
    out = subprocess.run(["afinfo", str(p)], capture_output=True, text=True).stdout
    m = re.search(r"estimated duration: ([\d.]+)", out)
    return int(float(m.group(1))) if m else 0


def write_notes(brief: Path):
    EP.mkdir(exist_ok=True)
    md = brief.read_text()
    title = re.search(r"^# (.+)$", md, flags=re.M)
    (EP / f"{brief.stem}.title").write_text(title.group(1) if title else f"Brief {brief.stem}")
    (EP / f"{brief.stem}.notes.html").write_text(show_notes(md))


def make_episode(brief: Path) -> Path:
    EP.mkdir(exist_ok=True)
    date = brief.stem
    txt = HERE / f".{date}.txt"
    txt.write_text(speakable(brief.read_text()))
    out = EP / f"{date}.m4a"
    subprocess.run(["say", "-v", voice(), "-r", str(CFG.get("rate", 180)), "-f", str(txt),
                    "-o", str(out), "--file-format=m4af", "--data-format=aac"], check=True)
    txt.unlink()
    return out


def write_feed():
    eps = sorted(EP.glob("*.m4a"), reverse=True)
    for old in eps[CFG.get("keep", 6):]:                   # nothing piles up
        for f in EP.glob(f"{old.stem}.*"):
            f.unlink()
    eps = eps[:CFG.get("keep", 6)]
    base = CFG["base_url"].rstrip("/")
    items = []
    for p in eps:
        d = datetime.datetime.strptime(p.stem, "%Y-%m-%d").replace(
            hour=6, tzinfo=datetime.timezone.utc)
        t = p.with_suffix(".title")
        title = html.escape(t.read_text() if t.exists() else p.stem)
        n = EP / f"{p.stem}.notes.html"
        notes = n.read_text().replace("]]>", "]]&gt;") if n.exists() else ""
        items.append(f"""    <item>
      <title>{title}</title>
      <description><![CDATA[{notes}]]></description>
      <content:encoded><![CDATA[{notes}]]></content:encoded>
      <guid isPermaLink="false">brief-{p.stem}</guid>
      <pubDate>{format_datetime(d)}</pubDate>
      <enclosure url="{base}/episodes/{p.name}" length="{p.stat().st_size}" type="audio/x-m4a"/>
      <itunes:duration>{duration(p)}</itunes:duration>
    </item>""")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>The Brief</title>
    <link>{base}/</link>
    <itunes:image href="{base}/cover.png"/>
    <image><url>{base}/cover.png</url><title>The Brief</title><link>{base}/</link></image>
    <description>A private morning brief.</description>
    <language>en-gb</language>
    <itunes:author>The Brief</itunes:author>
    <itunes:block>Yes</itunes:block>
    <itunes:explicit>false</itunes:explicit>
{chr(10).join(items)}
  </channel>
</rss>
"""
    (HERE / "feed.xml").write_text(feed)


def push(date: str):
    def git(*a):
        return subprocess.run(["git", "-C", str(HERE), *a], capture_output=True, text=True)
    if not git("remote").stdout.strip():
        print("No GitHub remote yet: episode made locally, not published."); return
    git("add", "-A")
    git("commit", "-m", f"Brief {date}")
    r = git("push", "-q", "origin", "HEAD")
    print("Published." if r.returncode == 0 else f"PUSH FAILED: {r.stderr.strip()}")
    if r.returncode != 0:
        sys.exit(1)


if __name__ == "__main__":
    brief = Path(sys.argv[1]).expanduser().resolve()
    write_notes(brief)
    if "--notes-only" in sys.argv:                         # refresh show notes, keep the audio
        print(f"Show notes refreshed for {brief.stem}")
    else:
        ep = make_episode(brief)
        print(f"Episode: {ep.name}, {duration(ep)//60} min, voice {voice()}")
    write_feed()
    push(brief.stem)
