"""Gate check for the login wall. Starts server.py on a free port with test
credentials, then pokes every route from outside like a stranger would.
Prints LOGIN CHECK PASS only if every assertion holds."""
import http.client, os, socket, subprocess, sys, time, urllib.parse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL, PW = "gate@test.local", "Gate-Test-Pass-91"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
env = dict(os.environ, RAAD_EMAIL=EMAIL, RAAD_PASSWORD=PW, HOST="127.0.0.1", PORT=str(PORT))
proc = subprocess.Popen([sys.executable, "server.py"], cwd=HERE, env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def login(email, pw):
    body = urllib.parse.urlencode({"email": email, "password": pw})
    return req("POST", "/login", body, {"Content-Type": "application/x-www-form-urlencoded"})


fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


try:
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            break
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
    if proc.poll() is not None:
        print(proc.stderr.read().decode("utf-8", "replace"))
        sys.exit("server exited early")

    s, h, b = req("GET", "/")
    check(s in (302, 303) and h.get("location", "").endswith("/login"), "anon GET / should redirect to /login, got %s" % s)
    check(b"Barq Racing \xc2\xb7 AI Assistant" not in b, "anon GET / leaked the voice page")

    s, h, b = req("GET", "/login")
    check(s == 200 and b'type="password"' in b and b'name="email"' in b, "login page missing form")

    for path in ("/ask", "/voice"):
        s, h, b = req("POST", path, b"{}", {"Content-Type": "application/json"})
        check(s == 401, "anon POST %s should be 401, got %s" % (path, s))

    s, h, b = login(EMAIL, "wrong-password")
    check(s == 401 and "raad_session=" not in h.get("set-cookie", "").replace("raad_session=;", ""),
          "wrong password should be 401 with no session, got %s %s" % (s, h.get("set-cookie")))
    s, h, b = login("someone@else.com", PW)
    check(s == 401, "wrong email should be 401, got %s" % s)

    s, h, b = login(EMAIL, PW)
    ck = h.get("set-cookie", "")
    check(s in (302, 303) and h.get("location", "").endswith("/"), "good login should redirect to /, got %s" % s)
    check("raad_session=" in ck and "httponly" in ck.lower(), "good login cookie missing or not HttpOnly: %r" % ck)
    cookie = ck.split(";")[0]

    s, h, b = req("GET", "/", headers={"Cookie": cookie})
    check(s == 200 and b"Barq Racing \xc2\xb7 AI Assistant" in b, "logged-in GET / should serve the voice page, got %s" % s)

    s, h, b = req("POST", "/ask", b"not json", {"Cookie": cookie, "Content-Type": "application/json"})
    check(s == 400, "logged-in POST /ask with bad body should reach handler (400), got %s" % s)

    name, val = cookie.split("=", 1)
    forged = "%s=%s" % (name, val[:-2] + ("AA" if not val.endswith("AA") else "BB"))
    s, h, b = req("GET", "/", headers={"Cookie": forged})
    check(s in (302, 303), "tampered cookie should be rejected, got %s" % s)
    s, h, b = req("GET", "/", headers={"Cookie": "raad_session=9999999999.deadbeef"})
    check(s in (302, 303), "made-up cookie should be rejected, got %s" % s)

    s, h, b = req("GET", "/logout", headers={"Cookie": cookie})
    check(s in (302, 303), "logout should redirect, got %s" % s)

    for _ in range(8):
        login(EMAIL, "guess")
    s, h, b = login(EMAIL, PW)
    check(s == 429, "after 8 wrong guesses even the right password should be locked out (429), got %s" % s)
finally:
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()

if fails:
    print("FAILED:")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("LOGIN CHECK PASS")
