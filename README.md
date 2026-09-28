# Ra'ad, the Barq Racing voice assistant

Ra'ad (رعد, "Thunder") is a talking helper for the Barq Racing booth at the
STEM Racing World Finals. You hold a key or the screen, ask a question out loud, and it
answers out loud in the same language you used, Arabic or English.

It knows about the team, the members, sponsors and the official 2026 rules.
Anything about the design of our car, BOLT, stays secret. It will not share it.

This copy is private. It sits behind a login, and only the team owner has the
password. It will be taken down after the World Finals.

## How it works

1. The web page records your voice while you hold SPACE (on a laptop) or
   press and hold the screen (on a phone).
2. Groq Whisper turns the speech into text and detects the language.
3. DeepSeek writes a short answer. For rules questions it first looks up the
   matching part of the official rulebooks in `rules/`.
4. ElevenLabs reads the answer out loud. With no ElevenLabs key it uses free
   Microsoft Edge voices instead.
5. The glowing orb on the page plays the answer.

Everything runs from one small Python file, `server.py`. It uses only the
Python standard library plus `edge-tts`.

## What you need

* Python 3.9 or newer
* A Groq API key (console.groq.com), for hearing
* A DeepSeek API key (platform.deepseek.com), for thinking
* An ElevenLabs API key (elevenlabs.io), for the voice. This one is optional.
* An email and password for the login

## Run it on your own computer

Install the one extra package:

```bash
pip install -r requirements.txt
```

Make a file called `secrets.json` next to `server.py`. Git never uploads it.

```json
{
  "groq_api_key": "gsk_...",
  "deepseek_api_key": "sk-...",
  "elevenlabs_api_key": "...",
  "login_email": "you@example.com",
  "login_password": "a long password"
}
```

You can use environment variables instead: `GROQ_API_KEY`,
`DEEPSEEK_API_KEY`, `ELEVENLABS_API_KEY`, `RAAD_EMAIL` and `RAAD_PASSWORD`.
If both are set, the environment variable wins.

Start it:

```bash
python server.py
```

Open http://127.0.0.1:8000, log in, tap "tap to start listening" and allow
the microphone.

On the booth Mac you can just double-click `START-MAC.command`. It installs
`edge-tts`, starts the server and opens Chrome. Put the login in
`secrets.json` first, or the server will stop and tell you it is missing.

## Put it online with Render

1. Push this repo to GitHub.
2. On render.com choose New, then Blueprint, and pick this repo. Render reads
   `render.yaml` and creates a free web service.
3. Render asks for the secret values. Fill in `RAAD_EMAIL`, `RAAD_PASSWORD`,
   `GROQ_API_KEY`, `DEEPSEEK_API_KEY` and `ELEVENLABS_API_KEY`.
   `RAAD_PASSWORD` must be at least 12 characters, or the server will not
   start. Use a random one from a password manager.
4. When the deploy finishes, open the https address Render gives you and log in.
   The microphone only works over https, and Render gives you that for free.

The free plan goes to sleep when nobody uses it, so the first visit after a
break can take about a minute to load.

## How the login works

* Every page and every question needs a login. Nobody can use the paid APIs
  without it.
* After you log in, the browser keeps a signed cookie for 12 hours.
* Changing the password logs out every browser.
* Five wrong tries from one place locks that place out for 10 minutes. Thirty
  wrong tries from anywhere locks all logins for 10 minutes.

## Files

| File | What it does |
|------|--------------|
| `server.py` | the whole backend and the login |
| `voice.html` | the orb page and the microphone |
| `login.html` | the login page |
| `knowledge.md` | what Ra'ad knows about the team. It is read again for every question, so edits apply right away |
| `config.json` | names, wake words and voices. Keep the key fields empty here |
| `rules/*.txt` | the official rulebooks as plain text |
| `render.yaml` | the Render setup |
| `tests/` | checks for the login and for what gets published |

## Test the login

```bash
python tests/check_login.py
```

It starts the server with test details and prints `LOGIN CHECK PASS` when
the login wall works.
