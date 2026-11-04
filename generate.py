#!/usr/bin/env python3
"""Replace the dancer in a video with the person in a photo, via OpenRouter video models.

Usage:
  python3 generate.py --video dance.mp4 --person me.jpg --out out.mp4 [--model bytedance/seedance-2.5]

Reads OPENROUTER_API_KEY from the environment or from a .env file next to this script.
"""
import argparse
import base64
import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://openrouter.ai/api/v1"

DEFAULT_PROMPT = (
    "Use the reference video for everything: the exact dance choreography, timing, body movements, "
    "gestures, camera framing and camera motion, the football stadium at night, the pitch, the crowd "
    "and the lighting. Replace the dancer with the person from the reference image: same face, "
    "glasses, hairstyle and body shape. He wears exactly the outfit from the reference image: a plain "
    "white crew-neck T-shirt and loose beige/cream trousers, with ordinary white outdoor sneakers "
    "(not slippers). He performs the same dance as the original dancer, on the same spot on the "
    "field. Realistic, natural lighting matching the stadium floodlights, no extra people in the "
    "foreground."
)


def load_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not key and os.path.exists(env):
        for line in open(env):
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("OPENROUTER_API_KEY not set")
    return key


def data_url(path):
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


def request(method, url, key, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read()
            return json.loads(raw) if raw[:1] in (b"{", b"[") else raw
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')}")


def ref(path_or_url, kind):
    url = path_or_url if path_or_url.startswith(("http://", "https://")) else data_url(path_or_url)
    return {"type": f"{kind}_url", f"{kind}_url": {"url": url}}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True, help="driving dance video (path or https URL)")
    p.add_argument("--person", required=True, help="photo of the person (path or https URL)")
    p.add_argument("--out", default="out.mp4")
    p.add_argument("--model", default="bytedance/seedance-2.5")
    p.add_argument("--duration", type=int, default=None)
    p.add_argument("--resolution", default="480p")
    p.add_argument("--aspect", default="16:9")
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--keep-audio", action="store_true", help="mux the original video's audio into the result")
    a = p.parse_args()
    key = load_key()

    duration = a.duration
    if duration is None and not a.video.startswith("http"):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.video],
                             capture_output=True, text=True).stdout
        duration = round(float(out))

    body = {
        "model": a.model,
        "prompt": a.prompt,
        "generate_audio": False,
        "input_references": [ref(a.video, "video"), ref(a.person, "image")],
    }
    if duration:
        body["duration"] = duration
    if a.resolution:
        body["resolution"] = a.resolution
    if a.aspect:
        body["aspect_ratio"] = a.aspect

    job = request("POST", f"{API}/videos", key, body)
    print("submitted:", json.dumps(job))
    poll = job.get("polling_url") or f"{API}/videos/{job['id']}"
    while True:
        time.sleep(10)
        st = request("GET", poll, key)
        print("status:", st.get("status"), flush=True)
        if st.get("status") == "completed":
            break
        if st.get("status") in ("failed", "cancelled", "expired"):
            sys.exit("job ended: " + json.dumps(st))

    print("usage:", json.dumps(st.get("usage")))
    raw_out = a.out if not a.keep_audio else a.out + ".noaudio.mp4"
    content = request("GET", st["unsigned_urls"][0], key)
    open(raw_out, "wb").write(content)
    if a.keep_audio and not a.video.startswith("http"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw_out, "-i", a.video, "-map", "0:v", "-map", "1:a?",
                        "-c:v", "copy", "-c:a", "aac", "-shortest", a.out], check=True)
        os.remove(raw_out)
    print("saved:", a.out)


if __name__ == "__main__":
    main()
