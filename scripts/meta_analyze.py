r"""Summarize Meta brand discovery & weekly insights JSON for copy/strategy planning."""

import json
import pathlib
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

MYT = timezone(timedelta(hours=8))


def to_myt_hour(ts: str) -> str:
    if not ts:
        return "?"
    try:
        # Handle ISO timestamps like 2025-10-01T12:34:56+0000
        ts_norm = ts.replace("Z", "+00:00")
        if len(ts_norm) >= 5 and ts_norm[-5] in ("+", "-") and ":" not in ts_norm[-5:]:
            ts_norm = ts_norm[:-2] + ":" + ts_norm[-2:]
        dt = datetime.fromisoformat(ts_norm).astimezone(MYT)
        return dt.strftime("%Y-%m-%d %H:%M MYT (%a)")
    except Exception:
        return ts[:16]


def main() -> None:
    path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(
        r"D:\Gemini\brands\sir-dharma-syamim\discovery\brand_discovery.json"
    )
    d = json.loads(path.read_text(encoding="utf-8"))

    print("=== FACEBOOK PAGE ===")
    print(json.dumps(d.get("facebook_page", {}), indent=2, ensure_ascii=False))

    print("\n=== INSTAGRAM ACCOUNT ===")
    ig = dict(d.get("instagram_account", {}))
    ig.pop("profile_picture_url", None)
    print(json.dumps(ig, indent=2, ensure_ascii=False))

    ig_media = d.get("instagram_media", [])
    fb_posts = d.get("facebook_posts", [])

    print(f"\n=== IG RECENT MEDIA ({len(ig_media)} total, showing top 20) ===")
    ig_types = Counter(m.get("media_type", "UNKNOWN") for m in ig_media)
    print("Media types:", dict(ig_types))
    for i, m in enumerate(ig_media[:20], 1):
        cap = (m.get("caption") or "").replace("\n", " | ")[:180]
        ins = m.get("insights") or {}
        reach = ins.get("reach", "-")
        saved = ins.get("saved", "-")
        shares = ins.get("shares", "-")
        inter = ins.get("total_interactions", "-")
        t = to_myt_hour(m.get("timestamp", ""))
        print(
            f"{i:02d}. [{t}] {m.get('media_type')} | "
            f"L:{m.get('like_count',0)} C:{m.get('comments_count',0)} "
            f"Reach:{reach} Save:{saved} Share:{shares} Int:{inter}"
        )
        if cap:
            print(f"    {cap}")

    print(f"\n=== FB RECENT POSTS ({len(fb_posts)} total, showing top 20) ===")
    for i, fp in enumerate(fb_posts[:20], 1):
        msg = (fp.get("message") or "").replace("\n", " | ")[:180]
        likes = (fp.get("likes") or {}).get("summary", {}).get("total_count", 0)
        comms = (fp.get("comments") or {}).get("summary", {}).get("total_count", 0)
        shares = (fp.get("shares") or {}).get("count", 0)
        t = to_myt_hour(fp.get("created_time", ""))
        print(f"{i:02d}. [{t}] L:{likes} C:{comms} S:{shares}")
        if msg:
            print(f"    {msg}")

    print("\n=== DOWNLOADED SAMPLE VISUALS ===")
    for s in d.get("downloaded_samples", []):
        print(s)


if __name__ == "__main__":
    main()
