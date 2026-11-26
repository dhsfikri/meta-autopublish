r"""Scheduled publisher for Meta (Facebook Page + Instagram Business).

Designed to run via GitHub Actions on a cron schedule (or locally with --dry-run).
Reads brands/<brand>/queue.json, publishes all due 'pending' posts whose
scheduled_at <= current Malaysia time (+08:00), and updates queue.json in place.
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import meta_client  # noqa: E402

MYT = timezone(timedelta(hours=8))


def parse_iso_myt(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MYT)
    return dt.astimezone(MYT)


def run_scheduler(brand: str, dry_run: bool = False, env_path: pathlib.Path | None = None) -> int:
    queue_path = ROOT_DIR / "brands" / brand / "queue.json"
    if not queue_path.exists():
        print(f"ERROR: Fail jadual tidak ditemui: {queue_path}", file=sys.stderr)
        return 1

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    posts = queue.get("posts", [])
    now = datetime.now(MYT)
    print(f"[{now.strftime('%Y-%m-%d %H:%M MYT')}] Semak jadual untuk '{brand}' ({len(posts)} jumlah post)...")

    due_posts = []
    for post in posts:
        if post.get("status") != "pending":
            continue
        sched = parse_iso_myt(post["scheduled_at"])
        if sched <= now:
            due_posts.append(post)

    if not due_posts:
        print("Tiada post yang sampai waktu untuk dipublish sekarang.")
        return 0

    print(f"Ditemui {len(due_posts)} post sedia untuk dipublish.")

    target = None
    page_id = queue.get("page_id") or meta_client.get_config("META_PAGE_ID", required=False, env_path=env_path)
    if not dry_run:
        token = meta_client.get_config("META_ACCESS_TOKEN", env_path=env_path)
        target = meta_client.resolve_target(token, page_id=page_id or None)

    changed = False
    for post in due_posts:
        post_id = post.get("id", "unknown")
        is_reel = post.get("format") == "reel" or bool(post.get("video_url"))
        video_url = post.get("video_url")
        cover_url = post.get("cover_url")
        image_urls = post.get("image_urls", [])
        caption = post.get("caption", "")

        if is_reel and not video_url:
            print(f"[SKIP] {post_id}: format reel tetapi tiada video_url.", file=sys.stderr)
            post["status"] = "failed"
            post["error"] = "Missing video_url"
            changed = True
            continue
        if not is_reel and not image_urls:
            print(f"[SKIP] {post_id}: tiada image_urls.", file=sys.stderr)
            post["status"] = "failed"
            post["error"] = "Missing image_urls"
            changed = True
            continue

        if dry_run:
            kind = "Reel MP4" if is_reel else f"{len(image_urls)} gambar"
            print(f"[DRY-RUN] Akan publish '{post_id}' ({kind}) ke FB Page & IG.")
            print(f"          Jadual: {post['scheduled_at']} | Kapsyen: {caption[:80]}...")
            continue

        try:
            pid = target["id"]
            ptoken = target.get("access_token") or meta_client.get_config("META_ACCESS_TOKEN", env_path=env_path)
            ig_id = (target.get("instagram_business_account") or {}).get("id")

            result = {}
            if is_reel:
                if not post.get("ig_only"):
                    result["facebook"] = meta_client.publish_reel_to_facebook(pid, ptoken, video_url, caption)
                if not post.get("fb_only") and ig_id:
                    result["instagram"] = meta_client.publish_reel_to_instagram(
                        ig_id,
                        ptoken,
                        video_url,
                        caption,
                        cover_url=cover_url,
                        share_to_feed=bool(post.get("share_to_feed", False)),
                    )
                if post.get("post_to_story"):
                    story_url = post.get("story_video_url") or video_url
                    if not post.get("ig_only"):
                        try:
                            result["facebook_story"] = meta_client.publish_story_to_facebook(pid, ptoken, story_url)
                        except (SystemExit, Exception) as se:
                            result["facebook_story_error"] = str(se)
                    if not post.get("fb_only") and ig_id:
                        try:
                            result["instagram_story"] = meta_client.publish_story_to_instagram(ig_id, ptoken, story_url)
                        except (SystemExit, Exception) as se:
                            result["instagram_story_error"] = str(se)
            else:
                if not post.get("ig_only"):
                    result["facebook"] = meta_client.publish_to_facebook(pid, ptoken, image_urls, caption)
                if not post.get("fb_only") and ig_id:
                    result["instagram"] = meta_client.publish_to_instagram(ig_id, ptoken, image_urls, caption)

                # Auto-publish Slide 1 as a seamless 9:16 Story to both FB Page & IG (default: True)
                if post.get("share_to_story", True):
                    story_url = post.get("story_url") or meta_client.make_story_url(
                        image_urls[0], post.get("theme", "")
                    )
                    if not post.get("ig_only"):
                        try:
                            result["facebook_story"] = meta_client.publish_story_to_facebook(pid, ptoken, story_url)
                        except BaseException as se:
                            result["facebook_story_error"] = str(se)
                            print(f"[WARN] FB Story gagal untuk '{post_id}': {se}", file=sys.stderr)
                    if not post.get("fb_only") and ig_id:
                        try:
                            result["instagram_story"] = meta_client.publish_story_to_instagram(ig_id, ptoken, story_url)
                        except BaseException as se:
                            result["instagram_story_error"] = str(se)
                            print(f"[WARN] IG Story gagal untuk '{post_id}': {se}", file=sys.stderr)

            post["status"] = "published"
            post["published_at"] = datetime.now(MYT).isoformat(timespec="seconds")
            post["meta_result"] = result
            post.pop("error", None)
            changed = True
            print(f"[OK] Berjaya publish '{post_id}' ke Meta: {json.dumps(result)}")
        except SystemExit as e:
            post["status"] = "failed"
            post["error"] = f"Meta API exited with code {e.code}"
            changed = True
            print(f"[FAIL] Gagal publish '{post_id}'", file=sys.stderr)
        except Exception as e:
            post["status"] = "failed"
            post["error"] = str(e)
            changed = True
            print(f"[FAIL] Gagal publish '{post_id}': {e}", file=sys.stderr)

    if changed and not dry_run:
        queue_path.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Jadual dikemas kini: {queue_path}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish due scheduled Meta posts from queue.json")
    parser.add_argument("--brand", default="sir-dharma-syamim", help="Nama folder jenama dalam brands/")
    parser.add_argument("--dry-run", action="store_true", help="Uji tanpa publish sebenar ke Meta")
    parser.add_argument("--env", type=pathlib.Path, default=None, help="Path ke fail .env")
    args = parser.parse_args()
    sys.exit(run_scheduler(args.brand, dry_run=args.dry_run, env_path=args.env))


if __name__ == "__main__":
    main()
