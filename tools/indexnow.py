"""Tell Bing and other IndexNow search engines which pages changed, so new times are picked up within hours.

Usage:
  python3 tools/indexnow.py --changed      # pages changed in the last commit (used by the GitHub Action)
  python3 tools/indexnow.py URL [URL ...]  # specific pages
The key file 5a9b0e43e0d02f990301cc0a2e25aad9.txt at the site root proves we own icetimes.ca.
"""
import json, subprocess, sys, urllib.request

SITE = "https://icetimes.ca"
HOST = "icetimes.ca"
KEY = "5a9b0e43e0d02f990301cc0a2e25aad9"


def changed_urls():
    out = subprocess.run(["git", "diff", "--name-only", "HEAD~1", "HEAD"], capture_output=True, text=True, check=True).stdout.split()
    urls = []
    for f in out:
        if f == "index.html":
            urls.append(SITE + "/")
        elif f.endswith("/index.html"):
            urls.append(f"{SITE}/{f[:-len('index.html')]}")
    return urls


def ping(urls):
    if not urls:
        print("No changed pages; nothing to send.")
        return
    for i in range(0, len(urls), 9000):
        body = json.dumps({"host": HOST, "key": KEY, "keyLocation": f"{SITE}/{KEY}.txt", "urlList": urls[i:i + 9000]}).encode()
        req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"IndexNow: sent {len(urls[i:i + 9000])} URLs, HTTP {r.status}")


if __name__ == "__main__":
    args = sys.argv[1:]
    ping(changed_urls() if args == ["--changed"] else args)
