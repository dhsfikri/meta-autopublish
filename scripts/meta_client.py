r"""Meta Graph API client for Facebook Page & Instagram Business automation.

Supports:
  - verify:   Validate token and auto-discover linked FB Page ID & IG Business Account ID
  - learn:    Pull FB Page + IG profile, recent posts/media, insights, and sample images for brand discovery
  - insights: Pull recent post-level & account-level analytics for weekly optimization
  - publish:  Publish Single Photo or Carousel (same media & caption) to FB Page + IG

Reads credentials from environment variables or d:\Gemini\.env (never hardcodes secrets).
"""

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent


def load_env_file(env_path: pathlib.Path | None = None) -> dict[str, str]:
    path = env_path or (ROOT_DIR / ".env")
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def get_config(key: str, required: bool = True, env_path: pathlib.Path | None = None) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        val = load_env_file(env_path).get(key, "").strip()
    if required and not val:
        print(f"ERROR: {key} tidak ditemui dalam environment atau .env", file=sys.stderr)
        sys.exit(1)
    return val


def graph_request(
    method: str,
    endpoint: str,
    token: str,
    params: dict | None = None,
    form_data: dict | None = None,
) -> dict:
    query = dict(params or {})
    query["access_token"] = token
    url = f"{GRAPH_BASE}/{endpoint.lstrip('/')}"
    if method.upper() == "GET":
        url = f"{url}?{urllib.parse.urlencode(query)}"
        body = None
        headers = {"Accept": "application/json"}
    else:
        payload = dict(form_data or {})
        payload["access_token"] = token
        body = urllib.parse.urlencode(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"Meta Graph API Error HTTP {e.code} ({endpoint}): {err_body}", file=sys.stderr)
        sys.exit(1)


def graph_request_safe(
    method: str,
    endpoint: str,
    token: str,
    params: dict | None = None,
) -> dict | None:
    """Non-fatal GET helper for optional insight metrics that may vary by account."""
    query = dict(params or {})
    query["access_token"] = token
    url = f"{GRAPH_BASE}/{endpoint.lstrip('/')}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None


def discover_pages(token: str) -> list[dict]:
    data = graph_request(
        "GET",
        "me/accounts",
        token,
        params={
            "fields": "id,name,category,about,website,fan_count,followers_count,access_token,instagram_business_account{id,username,name,biography,followers_count,media_count,profile_picture_url}"
        },
    )
    return data.get("data", [])


def resolve_target(token: str, page_id: str | None = None) -> dict:
    """Resolve Page ID, Page Access Token, and linked IG Business Account ID."""
    pages = discover_pages(token)
    if pages:
        if page_id:
            for p in pages:
                if p.get("id") == page_id:
                    return p
            print(f"ERROR: Page ID {page_id} tidak dijumpai dalam senarai Page token ini.", file=sys.stderr)
            sys.exit(1)
        return pages[0]

    # Fallback if token is already a direct Page Access Token
    me = graph_request(
        "GET",
        "me",
        token,
        params={
            "fields": "id,name,category,about,website,fan_count,followers_count,instagram_business_account{id,username,name,biography,followers_count,media_count,profile_picture_url}"
        },
    )
    me["access_token"] = token
    return me


def download_file(url: str, dest: pathlib.Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MetaBrandLearner/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.read())
            return True
    except Exception:
        return False


def cmd_verify(args: argparse.Namespace) -> None:
    token = get_config("META_ACCESS_TOKEN", env_path=args.env)
    pages = discover_pages(token)
    if not pages:
        target = resolve_target(token)
        pages = [target]

    print(f"Berjaya sambung ke Meta Graph API ({GRAPH_VERSION}). Ditemui {len(pages)} Facebook Page:\n")
    for idx, p in enumerate(pages, 1):
        ig = p.get("instagram_business_account") or {}
        print(f"[{idx}] Facebook Page: {p.get('name')} (ID: {p.get('id')})")
        print(f"    Kategori : {p.get('category', '-')}")
        print(f"    Followers: {p.get('followers_count', p.get('fan_count', '-'))}")
        if ig:
            print(f"    Instagram: @{ig.get('username')} (ID: {ig.get('id')}, Followers: {ig.get('followers_count', '-')})")
        else:
            print("    Instagram: TIADA akaun IG Business yang dipautkan ke Page ini.")
        print()


def cmd_learn(args: argparse.Namespace) -> None:
    token = get_config("META_ACCESS_TOKEN", env_path=args.env)
    page_id_cfg = args.page_id or get_config("META_PAGE_ID", required=False, env_path=args.env)
    target = resolve_target(token, page_id=page_id_cfg or None)

    page_id = target["id"]
    page_token = target.get("access_token") or token
    page_name = target.get("name", "unknown-brand")
    ig = target.get("instagram_business_account") or {}
    ig_id = ig.get("id")

    slug = args.brand or "".join(c.lower() if c.isalnum() else "-" for c in page_name).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")

    out_dir = ROOT_DIR / "brands" / slug / "discovery"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Menarik data pembelajaran untuk: {page_name} -> {out_dir}")

    # 1. Recent Facebook Page posts
    fb_posts_resp = graph_request_safe(
        "GET",
        f"{page_id}/posts",
        page_token,
        params={
            "limit": args.limit,
            "fields": "id,message,created_time,permalink_url,full_picture,shares,likes.summary(true),comments.summary(true)",
        },
    ) or {"data": []}
    fb_posts = fb_posts_resp.get("data", [])

    # 2. Recent Instagram media + insights
    ig_media: list[dict] = []
    if ig_id:
        ig_resp = graph_request_safe(
            "GET",
            f"{ig_id}/media",
            page_token,
            params={
                "limit": args.limit,
                "fields": "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
            },
        ) or {"data": []}
        ig_media = ig_resp.get("data", [])

        # Pull per-post insights for top recent IG posts
        for item in ig_media[: min(15, len(ig_media))]:
            metrics = "reach,saved,shares,total_interactions"
            ins = graph_request_safe(
                "GET",
                f"{item['id']}/insights",
                page_token,
                params={"metric": metrics},
            )
            if ins and "data" in ins:
                item["insights"] = {
                    m["name"]: (m.get("values", [{}])[0].get("value"))
                    for m in ins["data"]
                }

    # 3. Download sample poster images (up to 8) so visual style can be inspected
    samples_dir = out_dir / "sample_visuals"
    downloaded = []
    if ig.get("profile_picture_url"):
        p = samples_dir / "ig_profile.jpg"
        if download_file(ig["profile_picture_url"], p):
            downloaded.append(str(p))

    img_count = 0
    for idx, m in enumerate(ig_media):
        if img_count >= args.samples:
            break
        url = m.get("media_url") if m.get("media_type") in ("IMAGE", "CAROUSEL_ALBUM") else m.get("thumbnail_url")
        if url:
            dest = samples_dir / f"ig_{idx+1:02d}_{m['id']}.jpg"
            if download_file(url, dest):
                downloaded.append(str(dest))
                img_count += 1

    if img_count < args.samples:
        for idx, p in enumerate(fb_posts):
            if img_count >= args.samples:
                break
            url = p.get("full_picture")
            if url:
                dest = samples_dir / f"fb_{idx+1:02d}_{p['id']}.jpg"
                if download_file(url, dest):
                    downloaded.append(str(dest))
                    img_count += 1

    report = {
        "brand_slug": slug,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "facebook_page": {
            "id": page_id,
            "name": page_name,
            "category": target.get("category"),
            "about": target.get("about"),
            "website": target.get("website"),
            "followers_count": target.get("followers_count", target.get("fan_count")),
        },
        "instagram_account": ig,
        "facebook_posts_count": len(fb_posts),
        "instagram_media_count": len(ig_media),
        "facebook_posts": fb_posts,
        "instagram_media": ig_media,
        "downloaded_samples": downloaded,
    }

    report_path = out_dir / "brand_discovery.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSIAP! Data pembelajaran disimpan ke: {report_path}")
    print(f"- FB Posts ditarik : {len(fb_posts)}")
    print(f"- IG Media ditarik : {len(ig_media)}")
    print(f"- Sampel visual    : {len(downloaded)} gambar di {samples_dir}")


def make_story_url(image_url: str, theme: str = "") -> str:
    """Convert a Cloudinary 1:1 URL into a seamless 9:16 (1080x1920) Story URL via on-the-fly padding."""
    if "/image/upload/" not in image_url:
        return image_url
    bg_hex = "0B5D3B" if "dark" in (theme or "").lower() else "FFFFFF"
    return image_url.replace("/image/upload/", f"/image/upload/c_pad,w_1080,h_1920,b_rgb:{bg_hex}/", 1)


def publish_story_to_facebook(page_id: str, page_token: str, image_url: str) -> dict:
    photo = graph_request(
        "POST",
        f"{page_id}/photos",
        page_token,
        form_data={"url": image_url, "published": "false"},
    )
    return graph_request(
        "POST",
        f"{page_id}/photo_stories",
        page_token,
        form_data={"photo_id": photo["id"]},
    )


def publish_story_to_instagram(ig_id: str, page_token: str, image_url: str) -> dict:
    container = graph_request(
        "POST",
        f"{ig_id}/media",
        page_token,
        form_data={"image_url": image_url, "media_type": "STORIES"},
    )
    time.sleep(3)
    return graph_request(
        "POST",
        f"{ig_id}/media_publish",
        page_token,
        form_data={"creation_id": container["id"]},
    )


def publish_to_facebook(page_id: str, page_token: str, image_urls: list[str], caption: str) -> dict:
    if len(image_urls) == 1:
        return graph_request(
            "POST",
            f"{page_id}/photos",
            page_token,
            form_data={"url": image_urls[0], "caption": caption, "published": "true"},
        )

    # Multi-photo carousel on Facebook Page
    attached = []
    for url in image_urls:
        res = graph_request(
            "POST",
            f"{page_id}/photos",
            page_token,
            form_data={"url": url, "published": "false"},
        )
        attached.append({"media_fbid": res["id"]})

    form_data = {"message": caption}
    for idx, item in enumerate(attached):
        form_data[f"attached_media[{idx}]"] = json.dumps(item)
    return graph_request("POST", f"{page_id}/feed", page_token, form_data=form_data)


def publish_to_instagram(ig_id: str, page_token: str, image_urls: list[str], caption: str) -> dict:
    if len(image_urls) == 1:
        container = graph_request(
            "POST",
            f"{ig_id}/media",
            page_token,
            form_data={"image_url": image_urls[0], "caption": caption},
        )
        time.sleep(3)
        return graph_request(
            "POST",
            f"{ig_id}/media_publish",
            page_token,
            form_data={"creation_id": container["id"]},
        )

    # Carousel on Instagram
    child_ids = []
    for url in image_urls:
        c = graph_request(
            "POST",
            f"{ig_id}/media",
            page_token,
            form_data={"image_url": url, "is_carousel_item": "true"},
        )
        child_ids.append(c["id"])
        time.sleep(1)

    parent = graph_request(
        "POST",
        f"{ig_id}/media",
        page_token,
        form_data={
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": caption,
        },
    )
    time.sleep(3)
    return graph_request(
        "POST",
        f"{ig_id}/media_publish",
        page_token,
        form_data={"creation_id": parent["id"]},
    )


def publish_reel_to_facebook(
    page_id: str,
    page_token: str,
    video_url: str,
    caption: str,
) -> dict:
    """Publish a Reel to Facebook Page via Meta Graph API video_reels 3-step hosted URL flow."""
    start = graph_request(
        "POST",
        f"{page_id}/video_reels",
        page_token,
        form_data={"upload_phase": "start"},
    )
    video_id = start["video_id"]
    upload_url = start["upload_url"]

    req = urllib.request.Request(
        upload_url,
        data=b"",
        headers={
            "Authorization": f"OAuth {page_token}",
            "file_url": video_url,
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            upload_res = json.loads(resp.read().decode("utf-8"))
            if not upload_res.get("success", True):
                raise RuntimeError(f"FB Reel hosted upload failed: {upload_res}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"FB Reel Upload Error HTTP {e.code}: {err_body}", file=sys.stderr)
        sys.exit(1)

    finish = graph_request(
        "POST",
        f"{page_id}/video_reels",
        page_token,
        form_data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": caption,
        },
    )
    finish["video_id"] = video_id
    return finish


def publish_reel_to_instagram(
    ig_id: str,
    page_token: str,
    video_url: str,
    caption: str,
    cover_url: str | None = None,
    share_to_feed: bool = False,
) -> dict:
    """Publish a Reel to Instagram Business Account via Graph API REELS container + status polling."""
    form = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
    }
    if cover_url:
        form["cover_url"] = cover_url

    container = graph_request("POST", f"{ig_id}/media", page_token, form_data=form)
    creation_id = container["id"]

    # Poll until IG finishes processing the video container (max ~3 minutes)
    for _ in range(36):
        time.sleep(5)
        st = graph_request_safe("GET", creation_id, page_token, params={"fields": "status_code,status"})
        code = (st or {}).get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG Reel container gagal diproses: {st}")

    return graph_request(
        "POST",
        f"{ig_id}/media_publish",
        page_token,
        form_data={"creation_id": creation_id},
    )


def cmd_publish_reel(args: argparse.Namespace) -> None:
    token = get_config("META_ACCESS_TOKEN", env_path=args.env)
    page_id_cfg = args.page_id or get_config("META_PAGE_ID", required=False, env_path=args.env)
    target = resolve_target(token, page_id=page_id_cfg or None)
    page_id = target["id"]
    page_token = target.get("access_token") or token
    ig_id = (target.get("instagram_business_account") or {}).get("id")

    caption = pathlib.Path(args.caption_file).read_text(encoding="utf-8").strip() if args.caption_file else args.caption
    results = {}
    if not args.ig_only:
        results["facebook"] = publish_reel_to_facebook(page_id, page_token, args.video_url, caption)
    if not args.fb_only:
        if not ig_id:
            print("WARNING: Tiada IG Business Account dipautkan, langkau IG.", file=sys.stderr)
        else:
            results["instagram"] = publish_reel_to_instagram(
                ig_id,
                page_token,
                args.video_url,
                caption,
                cover_url=args.cover_url,
                share_to_feed=args.share_to_feed,
            )

    print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_publish(args: argparse.Namespace) -> None:
    token = get_config("META_ACCESS_TOKEN", env_path=args.env)
    page_id_cfg = args.page_id or get_config("META_PAGE_ID", required=False, env_path=args.env)
    target = resolve_target(token, page_id=page_id_cfg or None)
    page_id = target["id"]
    page_token = target.get("access_token") or token
    ig_id = (target.get("instagram_business_account") or {}).get("id")

    caption = pathlib.Path(args.caption_file).read_text(encoding="utf-8") if args.caption_file else args.caption
    image_urls = args.image_url

    results = {}
    if not args.ig_only:
        results["facebook"] = publish_to_facebook(page_id, page_token, image_urls, caption)
    if not args.fb_only:
        if not ig_id:
            print("WARNING: Tiada IG Business Account dipautkan, langkau IG.", file=sys.stderr)
        else:
            results["instagram"] = publish_to_instagram(ig_id, page_token, image_urls, caption)

    print(json.dumps(results, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Meta Graph API helper for FB Page & IG automation")
    parser.add_argument("--env", type=pathlib.Path, default=None, help="Path ke fail .env (default: d:\\Gemini\\.env)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify", help="Semak token dan senaraikan FB Page + IG Business yang bersambung")

    p_learn = sub.add_parser("learn", help="Tarik profil, post lepas, analitik & sampel gambar untuk belajar identiti jenama")
    p_learn.add_argument("--page-id", default=None, help="Facebook Page ID tertentu (pilihan jika hanya ada 1 Page)")
    p_learn.add_argument("--brand", default=None, help="Nama folder jenama (slug) dalam brands/")
    p_learn.add_argument("--limit", type=int, default=25, help="Jumlah post lepas untuk ditarik (default: 25)")
    p_learn.add_argument("--samples", type=int, default=8, help="Jumlah gambar poster lepas untuk dimuat turun (default: 8)")

    p_pub = sub.add_parser("publish", help="Publish single photo atau carousel ke FB Page & IG")
    p_pub.add_argument("--page-id", default=None, help="Facebook Page ID")
    p_pub.add_argument("--image-url", action="append", required=True, help="Public HTTPS image URL (ulang untuk carousel)")
    p_pub.add_argument("--caption", default="", help="Teks kapsyen")
    p_pub.add_argument("--caption-file", default=None, help="Fail teks mengandungi kapsyen")
    p_pub.add_argument("--fb-only", action="store_true")
    p_pub.add_argument("--ig-only", action="store_true")

    p_reel = sub.add_parser("publish-reel", help="Publish video Reel (MP4) ke FB Page & IG Reels")
    p_reel.add_argument("--page-id", default=None, help="Facebook Page ID")
    p_reel.add_argument("--video-url", required=True, help="Public HTTPS MP4 URL (contoh: Cloudinary)")
    p_reel.add_argument("--cover-url", default=None, help="Public HTTPS cover PNG/JPG URL (untuk IG Reel)")
    p_reel.add_argument("--caption", default="", help="Teks kapsyen")
    p_reel.add_argument("--caption-file", default=None, help="Fail teks mengandungi kapsyen")
    p_reel.add_argument("--fb-only", action="store_true")
    p_reel.add_argument("--ig-only", action="store_true")
    p_reel.add_argument("--share-to-feed", action="store_true", help="Papar juga Reel di IG Profile Grid (default: Reels tab sahaja)")

    args = parser.parse_args()
    if args.command == "verify":
        cmd_verify(args)
    elif args.command == "learn":
        cmd_learn(args)
    elif args.command == "publish":
        cmd_publish(args)
    elif args.command == "publish-reel":
        cmd_publish_reel(args)


if __name__ == "__main__":
    main()
