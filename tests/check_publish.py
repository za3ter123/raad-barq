"""Gate check before the repo goes public. Lists every file git would publish
and fails if any secret value, visitor log, or unwanted file would go out.
Prints PUBLISH CHECK PASS only if every assertion holds."""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*a):
    return subprocess.run(["git", *a], cwd=HERE, capture_output=True, text=True, check=True).stdout


top = os.path.normcase(os.path.realpath(git("rev-parse", "--show-toplevel").strip()))
if top != os.path.normcase(os.path.realpath(HERE)):
    sys.exit("barq-bolt is not its own git repo (toplevel=%s)" % top)

files = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard").split("\n")) - {""})
fails = []

# positive controls: the list must be real, and the secrets file must exist to be tested against
for must in ("server.py", "voice.html", "knowledge.md", "README.md", ".gitignore"):
    if must not in files:
        fails.append("expected %s in published set" % must)
if not os.path.exists(os.path.join(HERE, "secrets.json")):
    fails.append("secrets.json missing on disk, cannot test for leaks")

with open(os.path.join(HERE, "secrets.json"), encoding="utf-8") as f:
    secrets = [v for v in json.load(f).values() if isinstance(v, str) and len(v) >= 8]
if not secrets:
    fails.append("no secret values found to scan for")

for bad in ("secrets.json", "transcripts.log", "raad-server.log", "GATES.md"):
    if bad in files:
        fails.append("%s would be published" % bad)
for fn in files:
    if fn.lower().endswith((".mp3", ".log", ".pdf")) or fn.startswith((".claude/", "__pycache__/", ".ruff_cache/", ".unlazy/")):
        fails.append("unwanted file would be published: %s" % fn)
    with open(os.path.join(HERE, fn), "rb") as f:
        data = f.read()
    for s in secrets:
        if s.encode() in data:
            fails.append("secret value found in %s" % fn)

print("published files (%d):" % len(files))
for fn in files:
    print("  " + fn)
if fails:
    print("FAILED:")
    for m in fails:
        print(" -", m)
    sys.exit(1)
print("PUBLISH CHECK PASS")
