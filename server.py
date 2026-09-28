"""Ra'ad (Thunder) — Barq Racing voice assistant server.
Speech-to-speech: browser mic -> Groq Whisper (STT, auto AR/EN) -> DeepSeek
(or local Ollama fallback) -> Edge neural TTS -> audio back to the orb page.
Wake word required: "Thunder" (EN) / "رعد" (AR).
Runs anywhere with Python 3.9+ (built for MacBook M2 booth laptop).
Only non-stdlib dependency: edge-tts  (pip install edge-tts).
"""
import http.server, socketserver, json, urllib.request, urllib.parse
import base64, hashlib, hmac, os, re, subprocess, sys, tempfile, threading, time, uuid

HOST = os.environ.get("HOST", "127.0.0.1")   # hosts like Render need HOST=0.0.0.0
PORT = int(os.environ.get("PORT", "8000"))
HERE = os.path.dirname(os.path.abspath(__file__))
KB_PATH = os.path.join(HERE, "knowledge.md")
CFG_PATH = os.path.join(HERE, "config.json")
OLLAMA = "http://127.0.0.1:11434/api/chat"
GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"
DEEPSEEK = "https://api.deepseek.com/chat/completions"
UA = "Mozilla/5.0 (Macintosh; Apple Silicon) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def load_cfg():
    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    # keys live in gitignored secrets.json (config.json stays committable)
    try:
        with open(os.path.join(HERE, "secrets.json"), encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if v})
    except Exception:
        pass
    # env vars override everything
    cfg["groq_api_key"] = os.environ.get("GROQ_API_KEY", cfg.get("groq_api_key", ""))
    cfg["deepseek_api_key"] = os.environ.get("DEEPSEEK_API_KEY", cfg.get("deepseek_api_key", ""))
    cfg["elevenlabs_api_key"] = os.environ.get("ELEVENLABS_API_KEY", cfg.get("elevenlabs_api_key", ""))
    cfg["login_email"] = os.environ.get("RAAD_EMAIL", cfg.get("login_email", ""))
    cfg["login_password"] = os.environ.get("RAAD_PASSWORD", cfg.get("login_password", ""))
    return cfg


def load_kb():
    try:
        with open(KB_PATH, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "(no knowledge file yet)"


def persona(cfg):
    return (
        "You are %s (Arabic name: %s), the voice of Barq Racing, a Kuwaiti F1 in Schools "
        "(STEM Racing) team, chatting with visitors at the team's booth. "
        "PERSONALITY: a friendly, sharp teammate, warm and quick, never a corporate bot. Talk "
        "like a real person: use contractions, vary how you open each reply, get straight to "
        "the point. Never say 'Great question', 'As an AI', 'I'd be happy to', 'Certainly', "
        "'Absolutely' or any other filler. Now and then, not every reply (roughly one in four), "
        "add a light, harmless joke or playful line, for example about speed, lightning, or "
        "Hajin, the team's racing camel mascot. Never joke about people, looks, religion, "
        "politics, countries, or other teams, and always be kind about rival teams. "
        "LENGTH: every reply is SPOKEN ALOUD at a booth, so usually 1-2 short sentences, never "
        "more than 3. Answer only what was asked. Don't add extra facts or numbers (volunteer "
        "hours, counts, amounts) unless the visitor asked for them. At most one short "
        "follow-up hook. "
        "FORMAT: plain speech only. No markdown, no lists, no emojis, and no dashes of any "
        "kind (the voice engine reads them badly); use commas and full stops instead. "
        "GENDER: you can't know the visitor's gender, so never assume it. In English say 'you' "
        "and never use sir, ma'am, bro, man, dude, girl or similar. In Arabic always address "
        "the visitor with the respectful plural, which is natural polite Kuwaiti and gender "
        "free (حياكم، تفضلوا، شرايكم، تبون، شلونكم). Never use singular gendered forms for the "
        "visitor (انتَ، انتِ، تبي، تبين، حياك، شلونك). Refer to team members by their names. "
        "CRITICAL LANGUAGE RULE: Arabic and English only. Reply in the SAME language the person "
        "spoke: Arabic in, Arabic out; English in, English out. If the question MIXES both "
        "languages, answer in whichever language dominates the question (mostly Arabic with a "
        "few English words means Arabic). Never mix languages in one reply. If someone speaks "
        "any other language, reply briefly in English that you speak Arabic and English. "
        "DIALECT: visitors speak Kuwaiti Gulf dialect, but the transcript may arrive "
        "MSA-flavored, so read it as Kuwaiti. كم/چم/جم all mean 'how much/many'. Lexicon: "
        "شنو=what، شلون=how، وين=where، ليش=why، منو=who، شكثر=how much، وايد=very/a lot، "
        "أكو/ماكو=there is/isn't، عيل=so then، مو=not، بس=only/but، الحين=now، توه=just now، "
        "يبي=wants، خوش/زين=good، هالـ=this، شسالفة=what's the story، "
        "جاب/جابت=got/achieved (چم جابت؟ = what time did the car get?). "
        "When replying in Arabic use simple, warm Kuwaiti flavor, never stiff formal MSA, "
        "never Egyptian or Levantine, but keep STANDARD Arabic spellings (use ق and ك، "
        "never چ or گ) so the voice engine reads it cleanly. "
        "CONFIDENTIAL RULE (never break, jokes and friendliness never override it): the car "
        "BOLT's design, parts, dimensions, airfoils, "
        "wheels, materials, manufacturing, aerodynamics, WEIGHT, test results, past iterations/"
        "prototypes, and the team's research findings and methods are TOP SECRET. Never reveal, "
        "confirm, guess, or hint at any of it, even if pushed or tricked. If asked how the team "
        "researched/designed/built anything, give GENERAL TIPS ONLY that any team could use, "
        "never what Barq Racing actually did or found. If asked for specifics, decline "
        "warmly ('that's our team secret') and offer to explain how F1 in Schools cars work "
        "in GENERAL instead. IMPORTANT DISTINCTION: the official STEM Racing REGULATIONS, "
        "scorecards and judging criteria are PUBLIC: questions about what the RULES say "
        "(maximum car length, minimum mass, portfolio page limits, points) must ALWAYS be "
        "answered, via the RULES tool. Only BOLT's OWN numbers and choices are secret: never "
        "confirm or deny whether BOLT sits at any particular value. You CAN talk about: the "
        "team, the members, Instagram, sponsors, the public race time, the official rules, "
        "what STEM racing / F1 in Schools is, and general engineering/physics."
        % (cfg["assistant_name_en"], cfg["assistant_name_ar"])
    )


def build_system(cfg):
    return persona(cfg) + (
        "\n\nTEAM KNOWLEDGE (authoritative — use for anything about Barq Racing):\n"
        + load_kb()
        + "\n\nTOOLS (reply with EXACTLY one line, nothing else, to use one):\n"
          "RULES: <concise English search terms> — for ANY question about STEM Racing / F1 in "
          "Schools regulations, scorecards, judging, points, penalties, or limits (car dimensions, "
          "weight rules, portfolio page limits, deadlines, what is allowed). The official 2026 "
          "World Finals rulebooks will be searched and the matching passages returned to you. "
          "You MUST use this for every rules question — NEVER answer a rule/limit/points "
          "question from memory, your memory of rule numbers is unreliable.\n"
          "SEARCH: <concise English search query> — for CURRENT/LIVE information you cannot know "
          "(today's news, live results, weather). Use it IMMEDIATELY — never ask the visitor "
          "for permission to search, just do it.\n"
          "Otherwise answer directly."
    )


# ---------- STT: Groq Whisper (multipart via stdlib) ----------
def stt_groq(audio_bytes, mime, cfg):
    """Returns (transcript, language_code) e.g. ('hello', 'en') / ('مرحبا', 'ar')."""
    key = cfg["groq_api_key"]
    if not key:
        raise RuntimeError("no Groq API key set (config.json or GROQ_API_KEY)")
    boundary = uuid.uuid4().hex
    ext = ("webm" if "webm" in mime else "ogg" if "ogg" in mime
           else "mp4" if ("mp4" in mime or "m4a" in mime or "aac" in mime) else "wav")
    parts = []
    # Whisper prompt = fake preceding transcript in Kuwaiti register (Whisper continues
    # style, it doesn't follow instructions) — biases dialect decoding + proper-noun spelling
    stt_prompt = ("هلا، شلونك؟ شنو هذا؟ چم صار وقتها؟ وايد حلو ماشاءالله! أكو سباق اليوم. "
                  "سيارة BOLT من فريق Barq Racing، رعد، F1 in Schools، STEM Racing.")
    for name, val in (("model", "whisper-large-v3"), ("response_format", "verbose_json"),
                      ("prompt", stt_prompt)):
        parts.append(
            ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
             % (boundary, name, val)).encode()
        )
    parts.append(
        ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.%s\"\r\n"
         "Content-Type: %s\r\n\r\n" % (boundary, ext, mime)).encode()
    )
    parts.append(audio_bytes)
    parts.append(("\r\n--%s--\r\n" % boundary).encode())
    body = b"".join(parts)
    req = urllib.request.Request(GROQ_STT, data=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "multipart/form-data; boundary=" + boundary,
        "User-Agent": UA,  # Groq's edge 403s the default Python UA
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    lang = out.get("language", "en").lower()  # comes back as "english"/"arabic"
    lang = "ar" if lang.startswith("ar") else "en"
    return out.get("text", "").strip(), lang


# ---------- LLM: DeepSeek, falling back to local Ollama ----------
def llm_chat(messages, cfg):
    if cfg["deepseek_api_key"]:
        payload = json.dumps({
            "model": "deepseek-chat", "messages": messages,
            "max_tokens": 200, "temperature": 0.7,
        }).encode()
        req = urllib.request.Request(DEEPSEEK, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["deepseek_api_key"],
        })
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    # fallback: local Ollama
    payload = json.dumps({
        "model": cfg["ollama_fallback_model"], "stream": False, "messages": messages,
        "keep_alive": "30m", "options": {"num_predict": 160},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read()).get("message", {}).get("content", "").strip()


# ---------- TTS: ElevenLabs (primary — fast, natural, bilingual) ----------
ELEVEN = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128"


def tts_eleven(text, lang, cfg):
    """Returns mp3 bytes. One multilingual voice handles both Arabic and English."""
    voice = (cfg.get("elevenlabs_voice_id_ar") if lang == "ar"
             else cfg.get("elevenlabs_voice_id_en")) or cfg.get("elevenlabs_voice_id", "JBFqnCBsd6RMkjVDRZzb")
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_flash_v2_5",   # lowest latency, 32 languages incl. Arabic
    }).encode()
    req = urllib.request.Request(ELEVEN % voice, data=payload, headers={
        "Content-Type": "application/json",
        "xi-api-key": cfg["elevenlabs_api_key"],
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def tts(text, lang, cfg):
    """ElevenLabs if a key is set; free Edge voices otherwise."""
    if lang != "ar":
        # English TTS butchers "Ra'ad" — swap in Arabic script; the multilingual
        # model pronounces رعد properly even mid-English-sentence (CEO-approved)
        text = re.sub(r"(?i)\bra'?ad\b", "رعد", text)
    if cfg["elevenlabs_api_key"]:
        try:
            return tts_eleven(text, lang, cfg)
        except Exception:
            pass  # fall through to Edge so the booth never goes silent
    return tts_edge(text, lang, cfg)


# ---------- TTS fallback: Edge neural voices via edge-tts CLI ----------
def tts_edge(text, lang, cfg):
    """Returns mp3 bytes."""
    voice = cfg["tts_voice_ar"] if lang == "ar" else cfg["tts_voice_en"]
    out_path = os.path.join(tempfile.gettempdir(), "raad_tts_%s.mp3" % uuid.uuid4().hex)
    try:
        subprocess.run(
            [sys.executable, "-m", "edge_tts", "--voice", voice,
             "--text", text, "--write-media", out_path],
            check=True, capture_output=True, timeout=60,
        )
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


# ---------- wake word ----------
def strip_punct(s):
    return re.sub(r"[^\w؀-ۿ' ]+", " ", s.lower()).strip()


def wake_check(transcript, cfg):
    """Wake word must appear near the START of the utterance.
    Returns the question with the wake word removed, or None if not woken."""
    clean = strip_punct(transcript)
    for w in cfg["wake_words"]:
        w = strip_punct(w)
        m = re.search(r"(?:^|\s)%s(?:$|\s)" % re.escape(w), clean[:40])
        if m:
            rest = clean[m.end():].strip(" ,._-؟?!")
            return rest if rest else transcript  # woken with no question -> greet
    return None


# ---------- STEM Racing rulebook brain (rules/*.txt, keyword retrieval) ----------
RULES_DIR = os.path.join(HERE, "rules")
_rules_chunks = None  # [(source, chunk_text)]
_STOP = set("the a an of to in for and or is are be on at with by from as it this that "
            "what which how many much max maximum min minimum limit can may must".split())


def load_rules():
    global _rules_chunks
    if _rules_chunks is not None:
        return _rules_chunks
    chunks = []
    try:
        for fn in sorted(os.listdir(RULES_DIR)):
            if not fn.endswith(".txt"):
                continue
            src = fn.rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
            text = open(os.path.join(RULES_DIR, fn), encoding="utf-8").read()
            # strip per-page header/footer boilerplate so chunks hold real content
            _boiler = re.compile(
                r"(?i)^\s*(aramco stem racing world finals.*|©\s?20\d\d.*|page \d+ of \d+\s*"
                r"|\d{1,2} (january|february|march|april|may|june|july|august|september|october|november|december) 20\d\d\s*)$"
            )
            text = "\n".join(l for l in text.split("\n") if not _boiler.match(l))
            buf = ""
            for line in text.split("\n"):
                buf += line + "\n"
                # flush at ~700 chars, but only at a sentence/heading boundary
                if len(buf) > 700 and (line.strip() == "" or line.rstrip().endswith((".", ":"))
                                       or re.match(r"^\s*(T|C)\d+\.", line)):
                    chunks.append((src, buf.strip()))
                    buf = ""
            if buf.strip():
                chunks.append((src, buf.strip()))
    except Exception:
        pass
    _rules_chunks = chunks
    return chunks


def rules_lookup(query):
    """Top rulebook passages matching the (English) query — simple word-overlap scoring."""
    words = [w for w in re.findall(r"[a-z0-9.]+", query.lower()) if w not in _STOP]
    if not words:
        return "(no query terms)"
    bigrams = [" ".join(p) for p in zip(words, words[1:])]
    is_limit_q = bool(re.search(r"(?i)max|min|limit|weight|mass|length|width|height|how (many|much)|pages", query))
    scored = []
    for src, chunk in load_rules():
        low = chunk.lower()
        # skip table-of-contents style chunks (mostly tiny lines / bare numbers)
        lines = [l.strip() for l in chunk.split("\n") if l.strip()]
        if lines and sum(1 for l in lines if len(l) < 25) > len(lines) * 0.6:
            continue
        score = sum(min(low.count(w), 2) for w in words)
        score += sum(5 * low.count(b) for b in bigrams)
        if is_limit_q and re.search(r"(?i)absolute (min|max)|maximum of|minimum of|assessed pages", chunk):
            score += 4
        if score:
            scored.append((score, src, chunk))
    scored.sort(key=lambda t: -t[0])
    out, used = [], 0
    for score, src, chunk in scored[:8]:
        piece = "[%s]\n%s" % (src, chunk[:900])
        if used + len(piece) > 6000:
            break
        out.append(piece)
        used += len(piece)
    return "\n\n".join(out) or "(nothing found in the rulebooks)"


# ---------- live Instagram (headless HTTP — nothing appears on screen) ----------
IG_URL = "https://i.instagram.com/api/v1/users/web_profile_info/?username=%s"
_ig_cache = {"t": 0.0, "txt": ""}


def insta_live(cfg):
    """Fresh profile stats + latest posts for the team Instagram.
    Cached 10 min; returns '' on any failure (knowledge.md snapshot still covers basics)."""
    if time.time() - _ig_cache["t"] < 600 and _ig_cache["txt"]:
        return _ig_cache["txt"]
    try:
        handle = cfg.get("instagram_handle", "barq.racingkw")
        req = urllib.request.Request(IG_URL % handle, headers={
            "User-Agent": UA, "x-ig-app-id": "936619743392459"})
        with urllib.request.urlopen(req, timeout=10) as r:
            u = json.loads(r.read())["data"]["user"]
        posts = []
        for e in u["edge_owner_to_timeline_media"]["edges"][:6]:
            n = e["node"]
            cap = n["edge_media_to_caption"]["edges"]
            caption = cap[0]["node"]["text"].replace("\n", " ")[:120] if cap else "(no caption)"
            likes = n.get("edge_liked_by", n.get("edge_media_preview_like", {})).get("count", "?")
            posts.append("- %s (%s likes)" % (caption, likes))
        txt = ("LIVE INSTAGRAM DATA for @%s (fetched minutes ago — prefer this over the "
               "knowledge snapshot for follower/post numbers):\n"
               "%s followers, %s posts.\nBio: %s\nLatest posts:\n%s") % (
            handle, u["edge_followed_by"]["count"],
            u["edge_owner_to_timeline_media"]["count"],
            u.get("biography", "").replace("\n", " "), "\n".join(posts))
        _ig_cache["t"], _ig_cache["txt"] = time.time(), txt
        return txt
    except Exception:
        return ""


def _strip_snips(snips):
    clean = [re.sub(r"<[^>]+>", "", s).replace("&#x27;", "'").replace("&amp;", "&").strip()
             for s in snips[:4]]
    return [c for c in clean if c]


def web_search(query):
    """Keyless web search: DuckDuckGo HTML scrape, Bing HTML fallback (DDG rate-limits)."""
    q = urllib.parse.quote(query)
    try:
        req = urllib.request.Request("https://html.duckduckgo.com/html/?q=" + q,
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", "ignore")
        clean = _strip_snips(re.findall(r'class="result__snippet".*?>(.*?)</a>', html, re.S))
        if clean:
            return "\n".join("- " + c for c in clean)
    except Exception:
        pass
    try:
        req = urllib.request.Request("https://www.startpage.com/sp/search?query=" + q,
                                     headers={"User-Agent": UA, "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", "ignore")
        clean = _strip_snips(re.findall(r'class="description[^"]*"[^>]*>(.*?)</', html, re.S))
        if clean:
            return "\n".join("- " + c for c in clean)
        return "(no results found)"
    except Exception as e:
        return "(web search unavailable: %s)" % e


# auto-inject rulebook passages when the question smells like a regulations question
_RULES_TRIG = re.compile(
    r"(?i)regulat|\brules?\b|scrutineer|penalt|\blegal\b|allowed|permitted|portfolio|pages"
    r"|minimum|maximum|\bmin\b|\bmax\b|\blimit"
    r"|قانون|لوائح|اللوائح|قواعد|مسموح|صفحات|عقوب|فحص|الحد|أقصى|اقصى|أدنى|ادنى")
_AR2EN = {"وزن": "weight", "الوزن": "weight", "طول": "length", "عرض": "width",
          "ارتفاع": "height", "صفحات": "pages", "سيارة": "car", "السيارة": "car",
          "أقصى": "maximum", "اقصى": "maximum", "أدنى": "minimum", "ادنى": "minimum",
          "محفظة": "portfolio", "ملف": "portfolio", "جناح": "wing", "عجلات": "wheels",
          "عجلة": "wheel", "قوانين": "regulations", "مسافة": "clearance"}


def _rules_query(question):
    extra = " ".join(en for ar, en in _AR2EN.items() if ar in question)
    return (question + " " + extra).strip()


def answer(question, cfg):
    system = build_system(cfg)
    # regulations question? -> pull rulebook passages into context deterministically
    if _RULES_TRIG.search(question):
        passages = rules_lookup(_rules_query(question))
        if passages and not passages.startswith("("):
            system += ("\n\nOFFICIAL RULEBOOK PASSAGES (retrieved for this question):\n" + passages +
                       "\n\nSTRICT RULE: any regulation number/limit you state MUST appear "
                       "VERBATIM in the passages above. Your own memory of rule numbers is WRONG — "
                       "it is from old seasons. If the passages do not contain the number asked for, "
                       "you MUST reply that the 2026 regulations don't state it / you're not certain, "
                       "and suggest asking a Barq Racing team member. NEVER invent or recall a number.")
    # question mentions Instagram (EN or AR)? -> pull live stats into context
    if re.search(r"insta|follower|انست|متابع", question, re.I):
        live = insta_live(cfg)
        if live:
            system += "\n\n" + live
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": question}]
    try:
        out = llm_chat(msgs, cfg)
    except Exception as e:
        return "(brain error: %s)" % e
    # one hop of rulebook lookup if the model asked for it (may appear after a preamble line)
    m_rules = re.search(r"(?im)\bRULES\s*:\s*(.+)$", out)
    if m_rules:
        passages = rules_lookup(m_rules.group(1).strip())
        msgs.append({"role": "assistant", "content": out})
        msgs.append({"role": "user",
                     "content": "Official rulebook passages:\n" + passages +
                     "\n\nNow answer my original question using these, in MY language, "
                     "concise for speaking aloud. If the passages don't contain the answer, "
                     "say you're not certain rather than guessing."})
        try:
            out = llm_chat(msgs, cfg)
        except Exception as e:
            out = "(brain error after rules lookup: %s)" % e
        return out
    # one hop of live web search if the model asked for it
    m_search = re.search(r"(?im)\bSEARCH\s*:\s*(.+)$", out)
    if m_search:
        results = web_search(m_search.group(1).strip())
        msgs.append({"role": "assistant", "content": out})
        msgs.append({"role": "user",
                     "content": "Web results:\n" + results +
                     "\n\nNow answer my original question using ONLY these results, in MY language, "
                     "concise for speaking aloud. If the results are empty, unavailable, or don't "
                     "actually contain the answer, say you couldn't find it right now — NEVER guess "
                     "or invent an answer."})
        try:
            out = llm_chat(msgs, cfg)
        except Exception as e:
            out = "(brain error after search: %s)" % e
    return out


# ---------- login wall: one owner, stateless signed session cookie ----------
LOGIN_EMAIL = LOGIN_PASSWORD = ""
SESSION_KEY = b""
SESSION_TTL = 12 * 3600
COOKIE = "raad_session"
MAX_BODY = 15 * 1024 * 1024
LOCK_WINDOW = 600            # 10 minutes, for both counting failures and the lockout
IP_LIMIT = 5
_fails = {}                  # client IP -> [failure times]
_locked_until = {}
# ponytail: logged-out cookies live in memory only, so a restart forgets them and a cookie
# stolen before logout works again until its 12 h expiry. Persist this set if that matters.
_revoked = {}                # cookie value -> expiry unix time
_lock = threading.Lock()


def sign(exp):
    return hmac.new(SESSION_KEY, exp.encode(), hashlib.sha256).hexdigest()


def new_session():
    exp = str(int(time.time()) + SESSION_TTL)
    return exp + "." + sign(exp)


def session_ok(val):
    exp, _, sig = val.partition(".")
    if not re.fullmatch(r"[0-9]{1,12}", exp) or int(exp) < time.time():
        return False
    with _lock:
        if val in _revoked:
            return False
    return hmac.compare_digest(sig.encode(), sign(exp).encode())


def revoke(val):
    now = time.time()
    with _lock:
        for k in [k for k, exp in _revoked.items() if exp < now]:
            del _revoked[k]  # expired cookies are dead anyway
        _revoked[val] = int(val.partition(".")[0])


def locked(ip):
    with _lock:
        return _locked_until.get(ip, 0) > time.time()


def record_fail(ip):
    now = time.time()
    with _lock:
        ts = [t for t in _fails.get(ip, []) if now - t < LOCK_WINDOW] + [now]
        if len(ts) >= IP_LIMIT:
            _locked_until[ip] = now + LOCK_WINDOW
            ts = []
        _fails[ip] = ts
        for key in [k for k, v in _fails.items() if not v or now - v[-1] >= LOCK_WINDOW]:
            del _fails[key]  # keep the tables small
        for key in [k for k, t in _locked_until.items() if t <= now]:
            del _locked_until[key]


def reset_fails(ip):
    with _lock:
        _fails.pop(ip, None)


def keep_awake(url):
    """Render's free plan sleeps after 15 idle minutes; a ping every 10 keeps the booth instant.
    ponytail: one service running 24/7 is ~744 h a month, inside Render's 750 free hours."""
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(url + "/login", timeout=30).close()
        except Exception:
            pass


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", headers=()):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, where, cookie=None):
        self._send(303, "", "text/plain", [("Location", where)] + ([("Set-Cookie", cookie)] if cookie else []))

    def _login_page(self, code=200, err=""):
        with open(os.path.join(HERE, "login.html"), encoding="utf-8") as f:
            self._send(code, f.read().replace("<!--ERR-->", err), "text/html; charset=utf-8")

    def _session(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def _authed(self):
        return session_ok(self._session())

    def _ip(self):
        # ponytail: first X-Forwarded-For entry is client-controlled. Spoofing it only locks the
        # made-up IP, never the owner's; it also lets a guesser rotate IPs, which the 1 s delay
        # per failure slows. Use the proxy-added (last) entry if guessing becomes a real threat.
        return self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.client_address[0]

    def _cookie_flags(self):
        https = self.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower() == "https"
        return "; Path=/; HttpOnly; SameSite=Lax" + ("; Secure" if https else "")

    def _length(self):
        """Content-Length as int, -1 if missing-but-malformed or negative."""
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return -1
        return n if n >= 0 else -1

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/login":
            self._login_page()
        elif path == "/logout":
            if self._authed():
                revoke(self._session())
            self._redirect("/login", COOKIE + "=; Max-Age=0" + self._cookie_flags())
        elif path == "/logo.jpeg":  # public: the login page shows it
            with open(os.path.join(HERE, "logo.jpeg"), "rb") as f:
                self._send(200, f.read(), "image/jpeg")
        elif not self._authed():
            self._redirect("/login")
        elif path in ("/", "/index.html"):
            with open(os.path.join(HERE, "voice.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def _do_login(self):
        ip = self._ip()
        if locked(ip):  # even the right password waits out the lockout
            self._login_page(429, "Too many tries. Wait 10 minutes.")
            return
        n = self._length()
        if n < 0 or n > 4096:  # a login form is tiny
            self._login_page(413 if n > 0 else 400, "Bad request.")
            return
        form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        email = form.get("email", [""])[0].strip().lower()
        pw = form.get("password", [""])[0]
        email_ok = hmac.compare_digest(email.encode(), LOGIN_EMAIL.encode())
        pw_ok = hmac.compare_digest(pw.encode(), LOGIN_PASSWORD.encode())
        if not (email_ok and pw_ok):
            record_fail(ip)
            time.sleep(1)  # slows guessing; only this request's thread waits
            self._login_page(401, "Wrong email or password.")
            return
        reset_fails(ip)
        self._redirect("/", COOKIE + "=" + new_session() + "; Max-Age=%d" % SESSION_TTL
                       + self._cookie_flags())

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/login":
            self._do_login()
            return
        # auth before reading any body or touching a paid API
        if not self._authed():
            self._send(401, json.dumps({"error": "login required"}))
            return
        n = self._length()
        if n < 0:
            self._send(400, json.dumps({"error": "bad request"}))
            return
        if n > MAX_BODY:
            self._send(413, json.dumps({"error": "request too large"}))
            return
        cfg = load_cfg()
        if path == "/ask":  # text fallback for typing / testing
            try:
                q = json.loads(self.rfile.read(n) or "{}").get("q", "").strip()
            except Exception:
                self._send(400, json.dumps({"a": "(bad request)"}))
                return
            if not q:  # nothing to ask: don't pay for a model call
                self._send(400, json.dumps({"a": "(empty question)"}))
                return
            self._send(200, json.dumps({"a": answer(q, cfg)}))
            return

        if path != "/voice":
            self._send(404, "not found", "text/plain")
            return

        # /voice : raw audio in -> JSON {woke, heard, reply, lang, audio(b64 mp3)}
        try:
            audio = self.rfile.read(n)
            mime = self.headers.get("Content-Type", "audio/webm")
        except Exception:
            self._send(400, json.dumps({"error": "bad request"}))
            return
        try:
            heard, lang = stt_groq(audio, mime, cfg)
        except Exception as e:
            self._send(200, json.dumps({"woke": False, "error": "stt: %s" % e}))
            return
        # code-switched speech: reply in whichever language dominates the question
        ar_n = len(re.findall(r"[؀-ۿ]", heard))
        en_n = len(re.findall(r"[A-Za-z]", heard))
        if ar_n or en_n:
            lang = "ar" if ar_n >= en_n else "en"
        if not heard:
            self._send(200, json.dumps({"woke": False, "heard": ""}))
            return
        try:
            with open(os.path.join(HERE, "transcripts.log"), "a", encoding="utf-8") as f:
                f.write("[%s] heard=%r lang=%s\n" % (time.strftime("%H:%M:%S"), heard, lang))
        except OSError:
            pass
        if self.headers.get("X-PTT") == "1":
            # push-to-talk: no wake word needed (still strip the name if said)
            question = wake_check(heard, cfg) or heard
        else:
            question = wake_check(heard, cfg)
            if question is None:
                self._send(200, json.dumps({"woke": False, "heard": heard}))
                return
        reply = answer(question, cfg)
        lang = "ar" if re.search(r"[؀-ۿ]", reply) else ("ar" if lang == "ar" else "en")
        resp = {"woke": True, "heard": heard, "reply": reply, "lang": lang}
        try:
            resp["audio"] = base64.b64encode(tts(reply, lang, cfg)).decode()
        except Exception as e:
            resp["error"] = "tts: %s" % e
        self._send(200, json.dumps(resp))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    cfg = load_cfg()
    LOGIN_EMAIL = cfg["login_email"].strip().lower()
    LOGIN_PASSWORD = cfg["login_password"]
    if not LOGIN_EMAIL or not LOGIN_PASSWORD:
        sys.exit("ERROR: no login set. Set RAAD_EMAIL and RAAD_PASSWORD env vars, or put "
                 "login_email and login_password in secrets.json.")
    # ponytail: no global lock. A random 12+ character password has so many possibilities that
    # even thousands of parallel guesses per second never find it; a global lock would only let
    # strangers lock the owner out.
    if len(LOGIN_PASSWORD) < 12:
        sys.exit("ERROR: RAAD_PASSWORD must be at least 12 characters.")
    # changing the password logs everyone out; restarts don't
    SESSION_KEY = hashlib.sha256((os.environ.get("RAAD_SESSION_SECRET")
                                  or LOGIN_EMAIL + "\n" + LOGIN_PASSWORD).encode()).digest()
    brain = "DeepSeek API" if cfg["deepseek_api_key"] else "local Ollama (%s)" % cfg["ollama_fallback_model"]
    stt = "Groq Whisper" if cfg["groq_api_key"] else "MISSING GROQ KEY — voice will not work"
    voice_out = "ElevenLabs Flash (AR+EN)" if cfg["elevenlabs_api_key"] else "Edge neural (free fallback)"
    print("Ra'ad / Thunder on http://%s:%d  (login required)" % (HOST, PORT))
    print("  brain: %s | stt: %s | tts: %s" % (brain, stt, voice_out), flush=True)
    if os.environ.get("RENDER_EXTERNAL_URL"):  # set by Render only; nothing happens locally
        threading.Thread(target=keep_awake, args=(os.environ["RENDER_EXTERNAL_URL"].rstrip("/"),),
                         daemon=True).start()
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((HOST, PORT), H) as httpd:
        httpd.serve_forever()
