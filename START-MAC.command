#!/bin/bash
# Ra'ad booth launcher — double-click me on the Mac.
# If macOS refuses to run it: open Terminal, type:  bash   then drag this file in and press Enter.
cd "$(dirname "$0")"

# vanilla Mac: first-ever python3 use pops an "install developer tools" dialog — click Install, then rerun me
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found — macOS will offer to install Command Line Tools. Accept, then run me again."
  xcode-select --install 2>/dev/null
  exit 1
fi

python3 -m pip install --quiet edge-tts 2>/dev/null
echo "Starting Ra'ad... opening http://127.0.0.1:8000 in Chrome."
(sleep 2 && (open -a "Google Chrome" http://127.0.0.1:8000 || open http://127.0.0.1:8000)) &
python3 server.py
