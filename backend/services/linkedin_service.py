"""
LinkedIn Voyager API client.
Uses the same internal API that linkedin.com browser uses.

Session setup: opens a real visible Chrome window (Playwright headful) so the user
can log in with their own credentials. Cookies are extracted automatically after login.
API calls (search, profile lookup, messaging) use httpx directly — fast, no browser needed.
"""
import asyncio
import base64
import json
import os
import random
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# Thread pool exclusively for the headful login browser (not used for API calls)
_pw_executor = ThreadPoolExecutor(max_workers=1)

SESSION_FILE = Path(__file__).parent.parent / ".linkedin_session.json"

# Persistent Chrome profile directory — survives server restarts.
# After the user logs in once, Chrome stores session cookies here.
# Subsequent searches relaunch Chrome with this profile (auto-login, no cookie injection).
PERSISTENT_PROFILE_DIR = Path.home() / ".talon-chrome-profile"

BASE_URL = "https://www.linkedin.com"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


# ──────────────────────────────────────────────────────────────────────────────
# Session helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_session() -> Optional[Dict[str, str]]:
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_session(
    li_at: str,
    jsessionid: str,
    meta: Optional[Dict] = None,
    bcookie: str = "",
    bscookie: str = "",
    extra: Optional[Dict[str, str]] = None,
) -> None:
    data = {"li_at": li_at, "jsessionid": jsessionid}
    if bcookie:
        data["bcookie"] = bcookie.strip().strip('"')
    if bscookie:
        data["bscookie"] = bscookie.strip().strip('"')
    # Store all extra cookies from the browser session (bcookie, lang, liap, etc.)
    if extra:
        for k, v in extra.items():
            if k not in data and v:
                data[k] = v
    if meta:
        data.update(meta)
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f, indent=2)


def clear_session() -> None:
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def session_exists() -> bool:
    return SESSION_FILE.exists()


# ──────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ──────────────────────────────────────────────────────────────────────────────

def _headers(jsessionid: str) -> Dict[str, str]:
    csrf = jsessionid.strip('"')
    return {
        "User-Agent": _UA,
        "Accept": "application/vnd.linkedin.normalized+json+2.1",
        "Accept-Language": "en-US,en;q=0.9",
        "x-li-lang": "en_US",
        "x-restli-protocol-version": "2.0.0",
        "x-li-track": json.dumps({
            "clientVersion": "1.13.2718",
            "mpVersion": "1.13.2718",
            "osName": "web",
            "timezoneOffset": -7,
            "timezone": "America/Los_Angeles",
            "deviceFormFactor": "DESKTOP",
            "mpName": "voyager-web",
        }),
        "csrf-token": csrf,
        "Referer": "https://www.linkedin.com/search/results/people/",
        "Origin": BASE_URL,
    }


def _cookies(li_at: str, jsessionid: str, bcookie: str = "", bscookie: str = "", extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    # LinkedIn expects JSESSIONID quoted in the Cookie header (matching browser behavior)
    j = jsessionid.strip('"')
    jar: Dict[str, str] = {"li_at": li_at, "JSESSIONID": f'"{j}"'}
    if bcookie:
        b = bcookie.strip().strip('"')
        jar["bcookie"] = f'"{b}"'
    if bscookie:
        bs = bscookie.strip().strip('"')
        jar["bscookie"] = f'"{bs}"'
    # Include any extra cookies saved from the browser session (lang, liap, etc.)
    if extra:
        for name, val in extra.items():
            if name not in jar:
                jar[name] = val
    return jar


def _client(li_at: str, jsessionid: str, bcookie: str = "", bscookie: str = "", extra_cookies: Optional[Dict[str, str]] = None) -> httpx.AsyncClient:
    # Never follow redirects for Voyager API calls — a redirect means auth failed.
    return httpx.AsyncClient(
        timeout=20.0,
        headers=_headers(jsessionid),
        cookies=_cookies(li_at, jsessionid, bcookie, bscookie, extra_cookies),
        follow_redirects=False,
    )


def _extra_cookies_from_session(sess: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """All browser cookies beyond the core four — required for many Voyager write calls."""
    known = {"li_at", "jsessionid", "bcookie", "bscookie", "name", "headline", "linkedin_url"}
    extra = {k: v for k, v in sess.items() if k not in known and isinstance(v, str) and v}
    return extra if extra else None


def _client_from_session(sess: Dict[str, Any]) -> httpx.AsyncClient:
    """Create a Voyager API client from a loaded session dict, including all saved cookies."""
    return _client(
        sess["li_at"],
        sess.get("jsessionid", "ajax:0"),
        sess.get("bcookie", ""),
        sess.get("bscookie", ""),
        extra_cookies=_extra_cookies_from_session(sess),
    )


def _parse_me_response(data: Dict[str, Any]) -> Dict[str, str]:
    """Extract profile fields from /voyager/api/me JSON."""
    mini = data.get("miniProfile") or data.get("data", {}).get("miniProfile") or {}
    if not mini:
        for item in data.get("included", []):
            if "firstName" in item or item.get("$type", "").endswith("MiniProfile"):
                mini = item
                break
    first = mini.get("firstName", "") or mini.get("localizedFirstName", "")
    last = mini.get("lastName", "") or mini.get("localizedLastName", "")
    name = f"{first} {last}".strip()
    pub = mini.get("publicIdentifier", "")
    occupation = mini.get("occupation", "") or mini.get("headline", "")
    return {
        "name": name or "LinkedIn User",
        "headline": occupation,
        "linkedin_url": f"https://linkedin.com/in/{pub}" if pub else "",
    }


async def _validate_via_httpx(
    li_at: str,
    jsessionid: str,
    bcookie: str = "",
    bscookie: str = "",
    extra_cookies: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Fast session check via Voyager API (no Chrome)."""
    js = (jsessionid or "ajax:0").strip().strip('"')
    try:
        async with _client(li_at, js, bcookie, bscookie, extra_cookies) as c:
            resp = await c.get(f"{BASE_URL}/voyager/api/me")

        if resp.is_redirect:
            return {"valid": False, "error": "Session expired — sign in again in Settings"}
        if resp.status_code in (401, 403):
            return {
                "valid": False,
                "error": "LinkedIn rejected cookies — use browser login or paste fresh li_at + JSESSIONID",
            }
        if resp.status_code != 200:
            return {"valid": False, "error": f"LinkedIn returned HTTP {resp.status_code}"}

        # Refresh JSESSIONID from response if LinkedIn rotated it
        new_js = js
        for name, value in resp.cookies.items():
            if name == "JSESSIONID":
                new_js = value.strip('"')
                break

        try:
            data = resp.json()
        except Exception:
            return {"valid": False, "error": "Invalid response from LinkedIn"}

        profile = _parse_me_response(data)

        return {
            "valid": True,
            "jsessionid": new_js,
            **profile,
        }
    except httpx.TimeoutException:
        return {"valid": False, "error": "LinkedIn timed out — check your network"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


_CDP_PORT = 9223          # The ONE persistent Chrome browser (login + search)

# Module-level: the persistent Chrome process (kept alive after login)
_browser_proc = None
_browser_profile: Optional[Path] = None


def _cdp_get_linkedin_cookies() -> Dict[str, str]:
    """
    Use Chrome DevTools Protocol to get LinkedIn cookies in plaintext.
    Polls all open tabs; when a LinkedIn feed tab is found, reads cookies via CDP.
    Returns {"li_at": ..., "JSESSIONID": ...} or {} if not found.
    """
    import json as _json
    import urllib.request as _req
    from websockets.sync.client import connect as _ws_connect

    try:
        resp = _req.urlopen(f"http://localhost:{_CDP_PORT}/json/list", timeout=2)
        targets = _json.loads(resp.read())
    except Exception:
        return {}

    # Find a tab that's on the LinkedIn feed/home
    feed_target = None
    for t in targets:
        url = t.get("url", "")
        if "linkedin.com" in url and any(x in url for x in ("/feed", "/home", "/mynetwork", "/jobs")):
            feed_target = t
            break
    # Also accept any linkedin.com tab (user might be on a subpage after login)
    if not feed_target:
        for t in targets:
            url = t.get("url", "")
            if "linkedin.com" in url and "/login" not in url and "/authwall" not in url and "/uas/" not in url:
                feed_target = t
                break

    if not feed_target or not feed_target.get("webSocketDebuggerUrl"):
        return {}

    try:
        with _ws_connect(feed_target["webSocketDebuggerUrl"], open_timeout=5) as ws:
            ws.send(_json.dumps({"id": 1, "method": "Network.getAllCookies"}))
            raw = _json.loads(ws.recv(timeout=5))
            all_cookies = raw.get("result", {}).get("cookies", [])

        # Collect all LinkedIn cookies — li_at, JSESSIONID, bcookie, bscookie, lang, liap, etc.
        # All are required for Voyager API calls to succeed.
        result: Dict[str, str] = {}
        for c in all_cookies:
            if "linkedin.com" in c.get("domain", ""):
                name = c["name"]
                val = c["value"].strip('"')
                if name not in result:  # keep first (most specific host)
                    result[name] = val
        return result
    except Exception as e:
        print(f"[linkedin] CDP cookie read error: {e}", flush=True)
        return {}


def _kill_browser() -> None:
    """Terminate the persistent Chrome browser process. Preserves the profile directory."""
    global _browser_proc, _browser_profile
    if _browser_proc is not None:
        try:
            _browser_proc.terminate()
            _browser_proc.wait(timeout=5)
        except Exception:
            pass
        _browser_proc = None
    # Do NOT delete _browser_profile — it's now PERSISTENT_PROFILE_DIR on disk.
    # We keep it so Chrome can auto-login on next launch.
    _browser_profile = None


def _launch_login_browser_sync() -> Dict[str, Any]:
    """
    Launch Chrome with remote debugging. Opens linkedin.com/login.
    After login is detected, Chrome STAYS OPEN (persistent browser).
    This same browser is later reused for searches — no cookie injection needed.
    """
    global _browser_proc, _browser_profile
    import subprocess

    # Kill any existing browser first
    _kill_browser()

    # Also kill any stale process on the debug port
    try:
        pids = subprocess.run(["lsof", "-ti", f":{_CDP_PORT}"], capture_output=True, text=True, timeout=3).stdout.strip()
        if pids:
            subprocess.run(["kill", "-9"] + pids.split(), timeout=3)
            time.sleep(0.5)
    except Exception:
        pass

    # Use persistent profile dir (survives server restarts — Chrome auto-logs in after first login)
    PERSISTENT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile_dir = PERSISTENT_PROFILE_DIR

    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome_bin).exists():
        chrome_bin = "/Applications/Chromium.app/Contents/MacOS/Chromium"
    if not Path(chrome_bin).exists():
        return {"valid": False, "error": "Google Chrome not found — please install Chrome"}

    print(f"[linkedin] Launching Chrome (debug port {_CDP_PORT}, profile={profile_dir})...", flush=True)
    proc = subprocess.Popen(
        [
            chrome_bin,
            f"--remote-debugging-port={_CDP_PORT}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--new-window",
            "https://www.linkedin.com/login",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(3)
    try:
        subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'], timeout=3, capture_output=True)
    except Exception:
        pass

    print("[linkedin] Waiting for LinkedIn login...", flush=True)
    deadline = time.time() + 180
    found: Dict[str, str] = {}

    while time.time() < deadline:
        time.sleep(3)
        if proc.poll() is not None:
            print("[linkedin] Chrome exited during login wait", flush=True)
            break
        try:
            cookies = _cdp_get_linkedin_cookies()
        except Exception as e:
            print(f"[linkedin] CDP poll error: {e}", flush=True)
            cookies = {}
        if cookies.get("li_at"):
            found = cookies
            print("[linkedin] Login detected — got li_at!", flush=True)
            time.sleep(2)
            final = _cdp_get_linkedin_cookies()
            if final.get("li_at"):
                found = final
            break

    if not found.get("li_at"):
        proc.terminate()
        # Don't delete profile_dir — it's persistent on disk
        return {"valid": False, "error": "Login timed out or was cancelled — try again"}

    # *** Keep Chrome running — store globally for reuse in searches ***
    _browser_proc = proc
    _browser_profile = profile_dir  # persistent dir, not a temp
    print(f"[linkedin] Browser kept alive (PID {proc.pid}) profile={profile_dir}", flush=True)

    # Minimize Chrome so it's not in the user's way
    try:
        subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to set miniaturized of window 1 to true'], timeout=3, capture_output=True)
    except Exception:
        pass

    result: Dict[str, Any] = {
        "valid": True,
        "li_at": found["li_at"],
        "jsessionid": found.get("JSESSIONID", "").strip('"'),
    }
    for k, v in found.items():
        if k not in ("li_at", "JSESSIONID"):
            result[k] = v

    # ── Fetch profile from the already-open LinkedIn tab ──────────────────
    # Use fetch() from within the page — avoids TLS fingerprint issues.
    # This replaces the extra validate_session() call in browser_login().
    try:
        from websockets.sync.client import connect as _wsc
        tabs = _cdp_list_tabs(_CDP_PORT)
        li_tab = next(
            (t for t in tabs
             if "linkedin.com" in t.get("url", "")
             and "/login" not in t.get("url", "")
             and t.get("webSocketDebuggerUrl")),
            None,
        )
        if li_tab:
            csrf_for_profile = result["jsessionid"].strip('"')
            js_me = f"""
            (async function(){{
                try {{
                    const r = await fetch('/voyager/api/me',{{
                        headers:{{
                            'Accept':'application/vnd.linkedin.normalized+json+2.1',
                            'csrf-token':'{csrf_for_profile}',
                            'x-restli-protocol-version':'2.0.0',
                        }},
                        credentials:'include',
                    }});
                    if(r.ok){{const d=await r.json();return JSON.stringify({{ok:true,d:d}});}}
                    return JSON.stringify({{ok:false,s:r.status}});
                }}catch(e){{return JSON.stringify({{ok:false,e:e.message}});}}
            }})()
            """
            with _wsc(li_tab["webSocketDebuggerUrl"], open_timeout=5, max_size=10 * 1024 * 1024) as _wp:
                _wp.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))
                try: _wp.recv(timeout=3)
                except Exception: pass
                _wp.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                                     "params": {"expression": js_me, "awaitPromise": True, "returnByValue": True}}))
                _dl = time.time() + 12
                while time.time() < _dl:
                    try:
                        _msg = json.loads(_wp.recv(timeout=1.5))
                        if _msg.get("id") == 2:
                            _raw = _msg.get("result", {}).get("result", {}).get("value", "")
                            if _raw:
                                _outer = json.loads(_raw)
                                if _outer.get("ok"):
                                    _data = _outer["d"]
                                    _mini = (_data.get("miniProfile")
                                             or _data.get("data", {}).get("miniProfile") or {})
                                    if not _mini:
                                        for _item in _data.get("included", []):
                                            if "firstName" in _item:
                                                _mini = _item; break
                                    _first = _mini.get("firstName", "") or _mini.get("localizedFirstName", "")
                                    _last = _mini.get("lastName", "") or _mini.get("localizedLastName", "")
                                    _name = f"{_first} {_last}".strip()
                                    _pub = _mini.get("publicIdentifier", "")
                                    _occ = _mini.get("occupation", "") or ""
                                    if _name:
                                        result["name"] = _name
                                        result["headline"] = _occ
                                        result["linkedin_url"] = f"https://linkedin.com/in/{_pub}" if _pub else ""
                                        print(f"[linkedin] Profile: {_name} — {_occ[:50]}", flush=True)
                            break
                    except Exception:
                        pass
    except Exception as _e:
        print(f"[linkedin] Profile fetch (non-critical): {_e}", flush=True)

    return result


async def launch_login_browser() -> Dict[str, Any]:
    """
    Launch Chrome with a temp profile to let the user sign in to LinkedIn.
    Reads cookies directly from the SQLite database — no Playwright, no Keychain dialog.
    Runs in a thread so it doesn't block the async event loop.
    Times out after 200 seconds.
    """
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(_pw_executor, _launch_login_browser_sync)
    try:
        return await asyncio.wait_for(future, timeout=200.0)
    except asyncio.TimeoutError:
        return {"valid": False, "error": "Login timed out — please try again"}


async def setup_session(
    li_at: str,
    jsessionid: str = "",
    bcookie: str = "",
    bscookie: str = "",
) -> Dict[str, Any]:
    """
    Validate li_at + JSESSIONID by calling /voyager/api/me via httpx.
    No browser — instant result (< 2 seconds).
    Both cookies must be pasted from Chrome DevTools → Application → Cookies → linkedin.com.
    """
    li_at = li_at.strip()
    if not li_at:
        return {"valid": False, "error": "Paste your li_at cookie value from Chrome DevTools"}

    # Normalize JSESSIONID; default ajax:0 if user only pasted li_at (often still works)
    jsessionid = (jsessionid or "ajax:0").strip().strip('"')

    print(f"[linkedin] setup_session: validating via Voyager API...", flush=True)
    result = await validate_session(li_at, jsessionid, bcookie, bscookie)

    if result.get("valid"):
        # Pass jsessionid through so the router can store it
        result["jsessionid"] = jsessionid
        print(f"[linkedin] setup_session: valid — name={result.get('name')!r}", flush=True)
    else:
        print(f"[linkedin] setup_session: invalid — {result.get('error')}", flush=True)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Session validation
# ──────────────────────────────────────────────────────────────────────────────

def _validate_via_browser_sync(li_at: str, jsessionid: str, bcookie: str = "", bscookie: str = "", extra: Optional[Dict] = None) -> Dict[str, Any]:
    """Validate a LinkedIn session by loading /voyager/api/me in a real Chrome browser."""
    import subprocess, shutil, tempfile, urllib.request, time

    from websockets.sync.client import connect as ws_connect

    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome_bin).exists():
        return {"valid": False, "error": "Chrome not found"}

    val_port = 9226
    try:
        pids = subprocess.run(["lsof", "-ti", f":{val_port}"], capture_output=True, text=True, timeout=2).stdout.strip()
        if pids:
            subprocess.run(["kill", "-9"] + pids.split(), timeout=2)
            time.sleep(0.3)
    except Exception:
        pass

    tmp_profile = Path(tempfile.mkdtemp(prefix="talon-val-"))
    proc = subprocess.Popen(
        [chrome_bin, f"--remote-debugging-port={val_port}", f"--user-data-dir={tmp_profile}",
         "--headless=new", "--disable-gpu", "--no-first-run", "--disable-sync",
         "--disable-blink-features=AutomationControlled"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(3)

    try:
        ws, _send_inner, _recv_inner, _ws_url = _cdp_connect_to_tab(val_port, timeout=10)

        with ws:
            _mid2 = [0]
            def send(m, p=None):
                _mid2[0] += 1; _id = _mid2[0]
                ws.send(json.dumps({"id": _id, "method": m, "params": p or {}})); return _id
            def recv_id(tid, timeout=8.0):
                dl = time.time() + timeout
                while time.time() < dl:
                    try:
                        msg = json.loads(ws.recv(timeout=min(1.0, dl - time.time())))
                        if msg.get("id") == tid: return msg
                    except: pass
                return None

            recv_id(send("Network.enable"), 3)
            send("Page.addScriptToEvaluateOnNewDocument", {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})

            # Set cookies
            cookies = [{"name": "li_at", "value": li_at, "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": True}]
            j = jsessionid.strip('"') or "ajax:0"
            cookies.append({"name": "JSESSIONID", "value": j, "domain": ".linkedin.com", "path": "/", "secure": True})
            if bcookie:
                cookies.append({"name": "bcookie", "value": bcookie.strip().strip('"'), "domain": ".linkedin.com", "path": "/", "secure": True})
            if bscookie:
                cookies.append({"name": "bscookie", "value": bscookie.strip().strip('"'), "domain": ".linkedin.com", "path": "/", "secure": True})
            if extra:
                for k, v in extra.items():
                    if isinstance(v, str) and v:
                        cookies.append({"name": k, "value": v.strip().strip('"'), "domain": ".linkedin.com", "path": "/", "secure": True})

            recv_id(send("Network.setCookies", {"cookies": cookies}), 4)

            # Navigate to /voyager/api/me
            nav_id = send("Page.navigate", {"url": "https://www.linkedin.com/voyager/api/me"})
            recv_id(nav_id, 6)

            # Capture response body
            data_result = None
            dl = time.time() + 15
            pending_rids: Dict[str, str] = {}

            while time.time() < dl:
                try:
                    event = json.loads(ws.recv(timeout=1.0))
                except Exception:
                    continue

                m = event.get("method", "")
                p = event.get("params", {})

                if m == "Network.requestWillBeSent":
                    url = p.get("request", {}).get("url", "")
                    if "voyager/api/me" in url:
                        pending_rids[p["requestId"]] = url

                elif m == "Network.responseReceived":
                    rid = p.get("requestId", "")
                    url = p.get("response", {}).get("url", "")
                    status = p.get("response", {}).get("status", 0)
                    if rid in pending_rids or "voyager/api/me" in url:
                        if status == 200:
                            time.sleep(0.2)
                            body_msg = recv_id(send("Network.getResponseBody", {"requestId": rid}), 5)
                            if body_msg and not body_msg.get("error"):
                                try:
                                    data_result = json.loads(body_msg["result"]["body"])
                                    break
                                except Exception:
                                    pass
                        else:
                            return {"valid": False, "error": f"LinkedIn API returned HTTP {status}"}

            if not data_result:
                return {"valid": False, "error": "Could not read LinkedIn profile — try signing in again"}

            mini = (data_result.get("miniProfile") or data_result.get("data", {}).get("miniProfile") or {})
            if not mini:
                for item in data_result.get("included", []):
                    if "firstName" in item or item.get("$type", "").endswith("MiniProfile"):
                        mini = item; break

            first = mini.get("firstName", "") or mini.get("localizedFirstName", "")
            last = mini.get("lastName", "") or mini.get("localizedLastName", "")
            name = f"{first} {last}".strip()
            pub = mini.get("publicIdentifier", "")
            occupation = mini.get("occupation", "") or mini.get("headline", "")
            return {"valid": True, "name": name or "LinkedIn User", "headline": occupation,
                    "linkedin_url": f"https://linkedin.com/in/{pub}" if pub else ""}

    except Exception as e:
        return {"valid": False, "error": str(e)}
    finally:
        try: proc.terminate(); proc.wait(timeout=5)
        except: pass
        shutil.rmtree(str(tmp_profile), ignore_errors=True)


async def validate_session(
    li_at: str,
    jsessionid: str,
    bcookie: str = "",
    bscookie: str = "",
    extra_cookies: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Check LinkedIn session — httpx first (fast), Chrome fallback."""
    result = await _validate_via_httpx(li_at, jsessionid, bcookie, bscookie, extra_cookies)
    if result.get("valid"):
        return result

    httpx_err = result.get("error", "")
    print(f"[linkedin] httpx validation failed ({httpx_err}), trying Chrome...", flush=True)

    loop = asyncio.get_event_loop()
    try:
        browser_result = await loop.run_in_executor(
            _pw_executor,
            _validate_via_browser_sync,
            li_at, jsessionid or "ajax:0", bcookie, bscookie, extra_cookies,
        )
        if browser_result.get("valid"):
            browser_result["jsessionid"] = (jsessionid or "ajax:0").strip().strip('"')
            return browser_result
        return {
            "valid": False,
            "error": browser_result.get("error") or httpx_err or "Session invalid",
        }
    except Exception as e:
        return {"valid": False, "error": httpx_err or str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# People search
# ──────────────────────────────────────────────────────────────────────────────

def _parse_mini_profile(mini: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert a LinkedIn miniProfile dict into a lead dict."""
    public_id = mini.get("publicIdentifier", "")
    first = mini.get("firstName", "") or mini.get("localizedFirstName", "")
    last = mini.get("lastName", "") or mini.get("localizedLastName", "")
    name = f"{first} {last}".strip()

    if not name or not public_id:
        return None

    entity_urn = mini.get("entityUrn", "")
    profile_id = entity_urn.split(":")[-1] if entity_urn else ""
    object_urn = mini.get("objectUrn", "")
    member_id = object_urn.split(":")[-1] if object_urn else ""

    occupation = mini.get("occupation", "")
    title, company = "", ""
    if " at " in occupation:
        parts = occupation.split(" at ", 1)
        title = parts[0].strip()
        company = parts[1].strip()
    else:
        title = occupation

    return {
        "name": name,
        "title": title,
        "company": company,
        "company_size": "",
        "linkedin_url": f"https://linkedin.com/in/{public_id}",
        "linkedin_public_id": public_id,
        "linkedin_profile_id": profile_id,
        "linkedin_member_id": member_id,
        "tech_stack": [],
        "description": occupation,
    }


def _parse_search_response(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse Voyager search API JSON into a flat list of lead dicts.
    Handles multiple response shapes LinkedIn has used.
    """
    people: List[Dict[str, Any]] = []

    # Shape 1: {elements: [{elements: [{miniProfile: {...}}]}]} (dash/clusters or blended)
    for section in raw.get("elements", []):
        # Section can itself be a result item (shape 3) or a cluster (shape 1/2)
        if "miniProfile" in section:
            lead = _parse_mini_profile(section["miniProfile"])
            if lead:
                people.append(lead)
            continue

        for item in section.get("elements", []):
            mini = item.get("miniProfile")
            if mini:
                lead = _parse_mini_profile(mini)
                if lead:
                    people.append(lead)
                continue
            # Some responses nest under "entityCustomTrackingInfo" or similar
            # Try "target" field used in newer search responses
            target = item.get("targetUrn") or item.get("target")
            if not target:
                # Deep search in item for any miniProfile key
                for v in item.values():
                    if isinstance(v, dict) and "publicIdentifier" in v:
                        lead = _parse_mini_profile(v)
                        if lead:
                            people.append(lead)
                        break

    # Shape 2: {included: [{$type: "...MiniProfile", ...}]}
    if not people:
        for item in raw.get("included", []):
            t = item.get("$type", "")
            if "MiniProfile" in t or "publicIdentifier" in item:
                lead = _parse_mini_profile(item)
                if lead:
                    people.append(lead)

    return people


def _cdp_list_tabs(port: int) -> List[Dict]:
    """Return current CDP tab list from Chrome."""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://localhost:{port}/json/list", timeout=3)
        return json.loads(resp.read())
    except Exception:
        return []


def _cdp_new_tab(port: int) -> Optional[str]:
    """Create a new tab via CDP HTTP endpoint (Chrome 120+ requires PUT)."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/json/new",
            data=b"",  # empty body for PUT
            method="PUT",
            headers={"Content-Length": "0"},
        )
        resp = urllib.request.urlopen(req, timeout=3)
        return json.loads(resp.read()).get("webSocketDebuggerUrl")
    except Exception:
        return None


def _cdp_browser_ws_url(port: int) -> Optional[str]:
    """Get the browser-level WebSocket URL from /json/version (for Target.* commands)."""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=3)
        return json.loads(resp.read()).get("webSocketDebuggerUrl")
    except Exception:
        return None


def _cdp_connect_to_tab(port: int, prefer_url_fragment: str = "", timeout: float = 15.0):
    """
    Connect to a specific CDP tab, polling until one is available.
    If prefer_url_fragment is given, pick the tab whose URL contains it.
    Returns (ws, send_fn, recv_id_fn, ws_url).
    """
    from websockets.sync.client import connect as ws_connect

    def pick_ws_url(tabs_list: List[Dict]) -> Optional[str]:
        if prefer_url_fragment:
            for t in tabs_list:
                if prefer_url_fragment in t.get("url", "") and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        for t in tabs_list:
            u = t.get("url", "")
            if not u.startswith("chrome-extension://") and not u.startswith("devtools://") and t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
        for t in tabs_list:
            if t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
        return None

    deadline = time.time() + timeout
    ws_url = None

    while time.time() < deadline:
        tabs = _cdp_list_tabs(port)
        ws_url = pick_ws_url(tabs)
        if ws_url:
            break
        time.sleep(0.8)

    if not ws_url:
        ws_url = _cdp_new_tab(port)

    if not ws_url:
        raise RuntimeError(f"Could not connect to CDP on port {port}")

    ws = ws_connect(ws_url, open_timeout=8, max_size=50 * 1024 * 1024)
    _mid = [0]

    def send(method: str, params: Optional[Dict] = None) -> int:
        _mid[0] += 1
        _id = _mid[0]
        ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        return _id

    def recv_id(target_id: int, timeout: float = 10.0):
        dl = time.time() + timeout
        while time.time() < dl:
            try:
                msg = json.loads(ws.recv(timeout=min(1.0, dl - time.time())))
                if msg.get("id") == target_id:
                    return msg
            except Exception:
                pass
        return None

    return ws, send, recv_id, ws_url


def _inject_cookies_cdp(send, recv_id, sess: Dict[str, Any]) -> None:
    """Inject all session cookies into Chrome via CDP Network.setCookies."""
    cookies_to_set = []
    skip = {"name", "headline", "linkedin_url"}
    for k, v in sess.items():
        if k in skip or not isinstance(v, str) or not v:
            continue
        if k == "jsessionid":
            cname, cval = "JSESSIONID", f'"{v.strip(chr(34))}"'
        elif k in ("bcookie", "bscookie"):
            cname, cval = k, f'"{v.strip(chr(34))}"'
        else:
            cname, cval = k, v

        for domain in [".linkedin.com", ".www.linkedin.com"]:
            cookies_to_set.append({
                "name": cname, "value": cval,
                "domain": domain, "path": "/",
                "secure": True, "httpOnly": (k == "li_at"),
            })

    recv_id(send("Network.setCookies", {"cookies": cookies_to_set}), timeout=5)
    print(f"[linkedin] cdp: injected {len(cookies_to_set)//2} cookies", flush=True)


def _scrape_search_page_sync(send, recv_id, keywords: str, count: int) -> List[Dict[str, Any]]:
    """
    Fallback: navigate Chrome to the LinkedIn people-search results page
    and extract profile data from the DOM.
    Called when Voyager API endpoints return errors.
    """
    import urllib.parse
    results: List[Dict[str, Any]] = []

    search_url = (
        f"https://www.linkedin.com/search/results/people/"
        f"?keywords={urllib.parse.quote(keywords)}&origin=GLOBAL_SEARCH_HEADER"
    )
    print(f"[linkedin] scrape: navigating to search page for '{keywords}'...", flush=True)

    try:
        nav_id = send("Page.navigate", {"url": search_url})
        recv_id(nav_id, timeout=10)
        time.sleep(5)  # wait for JS-rendered results

        # Extract profile cards from the DOM
        js_scrape = r"""
        (function() {
            const people = [];
            // Try selector for search result cards
            const cards = document.querySelectorAll(
                '.reusable-search__result-container, ' +
                '[data-view-name="search-entity-result-universal-template"], ' +
                '.entity-result'
            );
            cards.forEach(card => {
                try {
                    // Name
                    const nameEl = card.querySelector(
                        '.entity-result__title-text a span[aria-hidden="true"], ' +
                        '.app-aware-link span[aria-hidden="true"], ' +
                        'span.actor-name'
                    );
                    const name = nameEl ? nameEl.textContent.trim() : '';
                    if (!name || name === 'LinkedIn Member') return;

                    // LinkedIn URL
                    const linkEl = card.querySelector(
                        'a.app-aware-link[href*="/in/"], a[href*="/in/"]'
                    );
                    const href = linkEl ? linkEl.getAttribute('href') : '';
                    const match = href.match(/\/in\/([^/?]+)/);
                    const publicId = match ? match[1] : '';
                    if (!publicId) return;

                    // Title/company from subtitle
                    const subEl = card.querySelector(
                        '.entity-result__primary-subtitle, ' +
                        '.linked-area .t-14.t-black--light'
                    );
                    const subtitle = subEl ? subEl.textContent.trim() : '';
                    let title = '', company = '';
                    if (subtitle.includes(' at ')) {
                        const parts = subtitle.split(' at ');
                        title = parts[0].trim();
                        company = parts.slice(1).join(' at ').trim();
                    } else {
                        title = subtitle;
                    }

                    people.push({
                        name: name,
                        title: title,
                        company: company,
                        linkedin_url: 'https://linkedin.com/in/' + publicId,
                        linkedin_public_id: publicId,
                        linkedin_profile_id: '',
                        linkedin_member_id: '',
                        company_size: '',
                        tech_stack: [],
                        description: subtitle,
                    });
                } catch(e) {}
            });
            return JSON.stringify({ok: true, count: people.length, people: people});
        })()
        """

        scrape_msg = recv_id(send("Runtime.evaluate", {
            "expression": js_scrape,
            "returnByValue": True,
        }), timeout=15)

        raw = (scrape_msg or {}).get("result", {}).get("result", {}).get("value", "")
        if raw:
            outer = json.loads(raw)
            if outer.get("ok"):
                results = outer.get("people", [])[:count]
                print(f"[linkedin] scrape: extracted {len(results)} profiles from DOM", flush=True)
                if not results:
                    # Log page title for debugging
                    title_msg = recv_id(send("Runtime.evaluate", {
                        "expression": "document.title",
                        "returnByValue": True,
                    }), 5)
                    title = (title_msg or {}).get("result", {}).get("result", {}).get("value", "?")
                    print(f"[linkedin] scrape: page title='{title}' (0 cards found — selectors may need update)", flush=True)
    except Exception as e:
        print(f"[linkedin] scrape error: {e}", flush=True)

    return results


def _relaunch_browser_for_search_sync() -> bool:
    """
    Relaunch Chrome with the persistent profile so searches work even after
    the browser was closed or the server was restarted.

    Because PERSISTENT_PROFILE_DIR stores LinkedIn cookies from the original login,
    Chrome will auto-authenticate — no cookie injection or new login needed.

    Returns True if Chrome is ready with a usable tab.
    """
    global _browser_proc
    import subprocess

    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome_bin).exists():
        chrome_bin = "/Applications/Chromium.app/Contents/MacOS/Chromium"
    if not Path(chrome_bin).exists():
        print("[linkedin] relaunch: Chrome not found", flush=True)
        return False

    if not PERSISTENT_PROFILE_DIR.exists():
        print("[linkedin] relaunch: no persistent profile — user must sign in via Settings first", flush=True)
        return False

    # Kill any stale process holding the CDP port
    try:
        pids = subprocess.run(
            ["lsof", "-ti", f":{_CDP_PORT}"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        if pids:
            subprocess.run(["kill", "-9"] + pids.split(), timeout=3)
            time.sleep(0.5)
    except Exception:
        pass

    print(f"[linkedin] relaunching Chrome for search (profile={PERSISTENT_PROFILE_DIR})...", flush=True)
    proc = subprocess.Popen(
        [
            chrome_bin,
            f"--remote-debugging-port={_CDP_PORT}",
            f"--user-data-dir={PERSISTENT_PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--new-window",
            "https://www.linkedin.com/feed",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _browser_proc = proc

    # Minimize Chrome window immediately so it's not in the user's way
    time.sleep(2)
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to set miniaturized of every window to true'],
            timeout=4, capture_output=True,
        )
    except Exception:
        pass

    # Wait up to 20s for a LinkedIn tab to load
    deadline = time.time() + 20
    while time.time() < deadline:
        tabs = _cdp_list_tabs(_CDP_PORT)
        if any(
            "linkedin.com" in t.get("url", "")
            and "/login" not in t.get("url", "")
            and "/authwall" not in t.get("url", "")
            for t in tabs
        ):
            print("[linkedin] relaunch: LinkedIn tab ready", flush=True)
            return True
        # Any tab is acceptable — might still be loading
        if tabs:
            print(f"[linkedin] relaunch: tab loading ({tabs[0].get('url','?')[:60]})", flush=True)
        time.sleep(2)

    # Even without a LinkedIn tab confirmed, Chrome is running — search might still work
    tabs = _cdp_list_tabs(_CDP_PORT)
    if tabs:
        print(f"[linkedin] relaunch: Chrome ready ({len(tabs)} tabs)", flush=True)
        return True

    print("[linkedin] relaunch: Chrome did not start in time", flush=True)
    return False


def _search_via_browser_sync(keywords: str, sess: Dict[str, Any], count: int = 25) -> List[Dict[str, Any]]:
    """
    Search LinkedIn Voyager API using the persistent Chrome browser (already logged in).

    The browser was kept alive after the login flow (_browser_proc, port _CDP_PORT).
    We connect to that existing browser, find a LinkedIn tab, and call fetch() from
    within the page context — giving us real Chrome TLS fingerprint + live cookies.
    No cookie injection, no new Chrome process, no fingerprint issues.
    """
    import urllib.parse
    from websockets.sync.client import connect as ws_connect

    port = _CDP_PORT

    # ── Ensure Chrome is running ─────────────────────────────────────────────
    tabs = _cdp_list_tabs(port)
    if not tabs:
        if _browser_proc is not None and _browser_proc.poll() is None:
            time.sleep(2)  # process alive but CDP not ready yet
            tabs = _cdp_list_tabs(port)
        if not tabs:
            # Chrome died or was closed — relaunch with persistent profile (auto-login)
            print("[linkedin] browser-search: Chrome not running — relaunching...", flush=True)
            if not _relaunch_browser_for_search_sync():
                return []
            tabs = _cdp_list_tabs(port)
            if not tabs:
                print("[linkedin] browser-search: Chrome failed to start", flush=True)
                return []

    print(f"[linkedin] browser-search: {len(tabs)} tab(s) in Chrome", flush=True)

    # ── Build Voyager API endpoint URLs ────────────────────────────────────
    encoded_kw = urllib.parse.quote(keywords)
    # Dash clusters endpoint (current LinkedIn API)
    voyager_url = (
        f"/voyager/api/search/dash/clusters"
        f"?decorationId=com.linkedin.voyager.dash.deco.search.SearchClusterCollection-175"
        f"&count={count}&origin=FACETED_SEARCH&q=all"
        f"&query=(keywords:{encoded_kw},flagshipSearchIntent:SEARCH_SRP,"
        f"queryParameters:List((key:resultType,value:List(PEOPLE))),"
        f"includeFiltersInResponse:false)&start=0"
    )
    # Older blended endpoint (fallback)
    blended_url = (
        f"/voyager/api/search/blended"
        f"?count={count}&filters=List(resultType-%3EPEOPLE)"
        f"&keywords={encoded_kw}&origin=GLOBAL_SEARCH_HEADER"
    )
    # Dash clusters with different decorationId versions
    voyager_url2 = (
        f"/voyager/api/search/dash/clusters"
        f"?decorationId=com.linkedin.voyager.dash.deco.search.SearchClusterCollection-176"
        f"&count={count}&origin=GLOBAL_SEARCH_HEADER&q=all"
        f"&query=(keywords:{encoded_kw},flagshipSearchIntent:SEARCH_SRP,"
        f"queryParameters:List((key:resultType,value:List(PEOPLE))),"
        f"includeFiltersInResponse:false)&start=0"
    )

    results: List[Dict[str, Any]] = []
    new_tab_target_id: Optional[str] = None  # track if we opened a tab (must clean up)

    def _close_created_tab() -> None:
        """Close the background tab we created, if any. Idempotent."""
        nonlocal new_tab_target_id
        tid = new_tab_target_id
        if not tid:
            return
        new_tab_target_id = None  # prevent double-close
        try:
            from websockets.sync.client import connect as _ws
            cws = _cdp_browser_ws_url(port)
            if cws:
                with _ws(cws, open_timeout=3, max_size=1024 * 1024) as _w:
                    _w.send(json.dumps({"id": 1, "method": "Target.closeTarget",
                                        "params": {"targetId": tid}}))
                    try: _w.recv(timeout=2)
                    except Exception: pass
        except Exception:
            pass

    try:
        # ── Step 1: Find an authenticated LinkedIn tab ──────────────────────
        tab_ws_url: Optional[str] = None

        for t in tabs:
            url = t.get("url", "")
            ws_dbg = t.get("webSocketDebuggerUrl", "")
            if (
                "linkedin.com" in url
                and "/login" not in url
                and "/authwall" not in url
                and "/uas/" not in url
                and ws_dbg
            ):
                tab_ws_url = ws_dbg
                print(f"[linkedin] browser-search: using tab: {url[:70]}", flush=True)
                break

        # ── Step 2: If no LinkedIn tab, create one via Target.createTarget ──
        if tab_ws_url is None:
            print("[linkedin] browser-search: no LinkedIn tab — creating background tab...", flush=True)

            # Use browser-level WebSocket for Target.createTarget (tab-level WS doesn't expose it)
            browser_ws = _cdp_browser_ws_url(port)
            if not browser_ws:
                # Browser-level WS unavailable — fall back to HTTP PUT /json/new
                browser_ws = None

            if browser_ws:
                try:
                    with ws_connect(browser_ws, open_timeout=5, max_size=10 * 1024 * 1024) as ws_browser:
                        ws_browser.send(json.dumps({
                            "id": 1,
                            "method": "Target.createTarget",
                            "params": {"url": "https://www.linkedin.com/feed"},
                        }))
                        deadline_create = time.time() + 8
                        while time.time() < deadline_create:
                            try:
                                msg = json.loads(ws_browser.recv(timeout=1.5))
                                if msg.get("id") == 1:
                                    new_tab_target_id = msg.get("result", {}).get("targetId")
                                    break
                            except Exception:
                                pass
                except Exception as e:
                    print(f"[linkedin] browser-search: Target.createTarget error: {e}", flush=True)

            if new_tab_target_id:
                print(f"[linkedin] browser-search: created tab {new_tab_target_id}, waiting for LinkedIn...", flush=True)
            else:
                # Fall back: HTTP PUT /json/new → blank tab → navigate it
                new_blank_ws = _cdp_new_tab(port)
                if new_blank_ws:
                    try:
                        with ws_connect(new_blank_ws, open_timeout=5, max_size=10 * 1024 * 1024) as ws_new:
                            ws_new.send(json.dumps({"id": 1, "method": "Page.navigate",
                                                    "params": {"url": "https://www.linkedin.com/feed"}}))
                    except Exception:
                        pass  # WS closes during navigation — expected
                else:
                    print("[linkedin] browser-search: could not create a new tab", flush=True)
                    return []

            # Wait for the tab to load LinkedIn (up to 20 s)
            deadline_load = time.time() + 20
            while time.time() < deadline_load:
                time.sleep(2)
                fresh_tabs = _cdp_list_tabs(port)
                for t in fresh_tabs:
                    url = t.get("url", "")
                    ws_dbg = t.get("webSocketDebuggerUrl", "")
                    if (
                        "linkedin.com" in url
                        and "/login" not in url
                        and "/authwall" not in url
                        and ws_dbg
                    ):
                        tab_ws_url = ws_dbg
                        print(f"[linkedin] browser-search: tab loaded: {url[:70]}", flush=True)
                        break
                if tab_ws_url:
                    break

        if not tab_ws_url:
            print("[linkedin] browser-search: could not obtain a LinkedIn tab", flush=True)
            _close_created_tab()
            return []

        # ── Step 3: Connect and run fetch() from within the LinkedIn page ───
        ws = ws_connect(tab_ws_url, open_timeout=8, max_size=50 * 1024 * 1024)
        _mid = [0]

        def send(method: str, params: Optional[Dict] = None) -> int:
            _mid[0] += 1
            _id = _mid[0]
            ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
            return _id

        def recv_id(tid: int, timeout: float = 10.0):
            dl = time.time() + timeout
            while time.time() < dl:
                try:
                    msg = json.loads(ws.recv(timeout=min(1.0, dl - time.time())))
                    if msg.get("id") == tid:
                        return msg
                except Exception:
                    pass
            return None

        try:
            recv_id(send("Runtime.enable"), 3)

            # Confirm we're actually on LinkedIn (not redirected to login)
            url_result = recv_id(send("Runtime.evaluate", {
                "expression": "window.location.href",
                "returnByValue": True,
            }), 5)
            current_url = (url_result or {}).get("result", {}).get("result", {}).get("value", "")
            print(f"[linkedin] browser-search: page = {current_url[:80]}", flush=True)

            if any(x in current_url for x in ("/login", "/authwall", "/uas/", "about:blank")):
                print("[linkedin] browser-search: page is not LinkedIn — session may be expired", flush=True)
                return []

            # Read JSESSIONID from live browser cookies (most reliable CSRF source)
            csrf_js = r"""(function(){
                var m=document.cookie.match(/JSESSIONID=["']?([^"';]+)["']?/);
                return m?m[1]:'';
            })()"""
            csrf_result = recv_id(send("Runtime.evaluate", {"expression": csrf_js, "returnByValue": True}), 5)
            csrf = (csrf_result or {}).get("result", {}).get("result", {}).get("value", "")
            if not csrf:
                csrf = sess.get("jsessionid", "").strip('"')
            print(f"[linkedin] browser-search: csrf len={len(csrf)}", flush=True)

            if not csrf:
                print("[linkedin] browser-search: no CSRF token — cannot call Voyager API", flush=True)
                return []

            # ── Voyager API call via fetch() from within LinkedIn's page context ──
            # This uses Chrome's real TLS fingerprint and the page's live cookies.
            # LinkedIn cannot distinguish this from a user clicking in the browser.
            js_fetch = f"""
                (async function() {{
                    const endpoints = [
                        '{voyager_url}',
                        '{voyager_url2}',
                        '{blended_url}',
                    ];
                    const errs = [];
                    for (const ep of endpoints) {{
                        try {{
                            const r = await fetch(ep, {{
                                headers: {{
                                    'Accept': 'application/vnd.linkedin.normalized+json+2.1',
                                    'csrf-token': '{csrf}',
                                    'x-restli-protocol-version': '2.0.0',
                                    'x-li-lang': 'en_US',
                                    'x-li-track': JSON.stringify({{clientVersion:'1.13.6325',mpVersion:'1.13.6325',osName:'web',timezoneOffset:-7,timezone:'America/Los_Angeles',deviceFormFactor:'DESKTOP',mpName:'voyager-web'}}),
                                }},
                                credentials: 'include',
                            }});
                            console.log('EP:', ep.substring(0,60), 'Status:', r.status);
                            if (r.ok) {{
                                const d = await r.json();
                                return JSON.stringify({{ok:true, status:r.status, ep:ep.substring(0,55), data:d}});
                            }}
                            const body = await r.text().catch(()=>'');
                            errs.push(ep.substring(0,40) + ' HTTP ' + r.status + ' ' + body.substring(0,100));
                        }} catch(e) {{
                            errs.push(ep.substring(0,40) + ' err: ' + e.message);
                        }}
                    }}
                    return JSON.stringify({{ok:false, errors:errs}});
                }})()
            """

            print("[linkedin] browser-search: executing Voyager fetch()...", flush=True)
            fetch_msg = recv_id(send("Runtime.evaluate", {
                "expression": js_fetch,
                "awaitPromise": True,
                "returnByValue": True,
            }), timeout=35)

            raw_val = (fetch_msg or {}).get("result", {}).get("result", {}).get("value", "")
            if raw_val:
                try:
                    outer = json.loads(raw_val)
                    if outer.get("ok") and "data" in outer:
                        parsed = _parse_search_response(outer["data"])
                        results = parsed[:count]
                        print(f"[linkedin] browser-search: ✓ {len(results)} profiles via {outer.get('ep','?')}", flush=True)
                    else:
                        errs = outer.get("errors") or [outer.get("error", "unknown")]
                        print(f"[linkedin] browser-search: Voyager API failed: {errs}", flush=True)
                        # Fallback: navigate to search page and scrape DOM
                        results = _scrape_search_page_sync(send, recv_id, keywords, count)
                except Exception as e:
                    print(f"[linkedin] browser-search: JSON parse error: {e}", flush=True)
                    print(f"[linkedin] browser-search: raw (first 400): {raw_val[:400]}", flush=True)
                    results = _scrape_search_page_sync(send, recv_id, keywords, count)
            else:
                exc_details = (fetch_msg or {}).get("result", {}).get("exceptionDetails")
                print(f"[linkedin] browser-search: empty response; exception={exc_details}", flush=True)
                results = _scrape_search_page_sync(send, recv_id, keywords, count)

        finally:
            try:
                ws.close()
            except Exception:
                pass
            _close_created_tab()

    except Exception as e:
        import traceback
        print(f"[linkedin] browser-search error: {e}", flush=True)
        traceback.print_exc()
        _close_created_tab()

    return results


async def search_people(
    keywords: str,
    li_at: str,
    jsessionid: str = "",
    count: int = 20,
    bcookie: str = "",
    bscookie: str = "",
    extra_cookies: Optional[Dict[str, str]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Search LinkedIn for people using a real Chrome browser via CDP.
    LinkedIn blocks plain httpx calls via TLS fingerprint detection —
    using Chrome gives the correct fingerprint and bypasses bot detection.

    Returns:
        List of people dicts on success (may be empty if no results found).
        Empty list on failure — session is NOT cleared.
    """
    # Build full session dict with all cookies for the browser
    sess_for_search: Dict[str, Any] = {
        "li_at": li_at,
        "jsessionid": jsessionid.strip().strip('"'),
        "bcookie": bcookie,
        "bscookie": bscookie,
    }
    if extra_cookies:
        for k, v in extra_cookies.items():
            if k not in sess_for_search:
                sess_for_search[k] = v

    # Run browser search in thread pool (it's synchronous/blocking)
    print(f"[linkedin] search: launching browser search for '{keywords}'", flush=True)
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(
            _pw_executor,
            _search_via_browser_sync,
            keywords,
            sess_for_search,
            count,
        )
    except Exception as e:
        print(f"[linkedin] search_people error: {e}", flush=True)
        results = []

    print(f"[linkedin] search: returning {len(results)} profiles", flush=True)
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Profile lookup (resolve public URL → internal profile/member IDs)
# ──────────────────────────────────────────────────────────────────────────────

def _extract_public_id(linkedin_url: str) -> Optional[str]:
    """
    Extract the public identifier from a LinkedIn profile URL.
    e.g. 'https://linkedin.com/in/john-smith' → 'john-smith'
    """
    if not linkedin_url:
        return None
    # Strip trailing slashes and query params
    url = linkedin_url.strip().split("?")[0].rstrip("/")
    if "/in/" in url:
        return url.split("/in/")[-1].strip("/")
    return None


async def lookup_profile(
    public_id: str,
    li_at: str,
    jsessionid: str,
    bcookie: str = "",
    bscookie: str = "",
) -> Optional[Dict[str, str]]:
    """
    Look up a LinkedIn profile by public identifier.
    Tries the legacy Voyager endpoint first, then the newer dash endpoint as fallback.
    Returns {"linkedin_profile_id": "ACoAAA...", "linkedin_member_id": "12345"}
    or None if not found.
    """
    def _parse_ids(data: dict) -> Optional[Dict[str, str]]:
        """Extract profile_id and member_id from a Voyager API response."""
        entity_urn = data.get("entityUrn", "")
        profile_id = entity_urn.split(":")[-1] if entity_urn else ""
        object_urn = data.get("objectUrn", "")
        member_id = object_urn.split(":")[-1] if object_urn else ""

        if not profile_id:
            mini = data.get("miniProfile") or {}
            entity_urn = mini.get("entityUrn", "")
            profile_id = entity_urn.split(":")[-1] if entity_urn else ""
            object_urn = mini.get("objectUrn", "")
            member_id = object_urn.split(":")[-1] if object_urn else ""

        if not profile_id:
            # Dash endpoint wraps in "elements"
            for el in data.get("elements", []):
                urn = el.get("entityUrn", "") or el.get("*profileView", "")
                if "ACoA" in urn or "fs_profile" in urn:
                    profile_id = urn.split(":")[-1]
                    member_id = ""
                    break

        return {"linkedin_profile_id": profile_id, "linkedin_member_id": member_id} if profile_id else None

    api_endpoints = [
        ("legacy", f"{BASE_URL}/voyager/api/identity/profiles/{public_id}"),
        # Newer dash endpoint — works for profiles that return 410 on old endpoint
        ("dash", f"{BASE_URL}/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={public_id}&decorationId=com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93"),
    ]

    try:
        async with _client(li_at, jsessionid, bcookie, bscookie) as c:
            # ── Try API endpoints first ───────────────────────────────────────
            auth_failed = False
            for label, url in api_endpoints:
                resp = await c.get(url)

                if resp.is_redirect:
                    print(f"[linkedin] profile lookup ({label}) redirected — session expired", flush=True)
                    auth_failed = True
                    break
                if resp.status_code in (401, 403):
                    print(f"[linkedin] profile lookup ({label}) {resp.status_code} — auth issue", flush=True)
                    auth_failed = True
                    break
                if resp.status_code == 410:
                    print(f"[linkedin] profile lookup ({label}) 410 for {public_id!r} — trying next", flush=True)
                    continue
                if resp.status_code != 200:
                    print(f"[linkedin] profile lookup ({label}) {public_id!r} → HTTP {resp.status_code}", flush=True)
                    continue

                ids = _parse_ids(resp.json())
                if ids:
                    print(f"[linkedin] resolved {public_id!r} via {label} → {ids['linkedin_profile_id']}", flush=True)
                    return ids

                print(f"[linkedin] {label} response had no IDs for {public_id!r}", flush=True)

            if auth_failed:
                return None

            # ── Fallback: scrape profile ID from the profile page HTML ────────
            # LinkedIn embeds profile data as JSON in the page — extract from there.
            # This works for profiles that return 410 via Voyager but are live publicly.
            print(f"[linkedin] API endpoints failed — scraping profile page for {public_id!r}", flush=True)
            page_resp = await c.get(
                f"{BASE_URL}/in/{public_id}",
                headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
                follow_redirects=True,
            )
            if page_resp.status_code == 200:
                html = page_resp.text
                # LinkedIn embeds profile URN in the page as "urn:li:fs_profile:ACoAAA..."
                import re as _re
                urn_match = _re.search(r'urn:li:fs_profile:(ACoA[A-Za-z0-9_-]+)', html)
                if urn_match:
                    profile_id = urn_match.group(1)
                    # Also try to find member ID: "urn:li:member:12345"
                    member_match = _re.search(r'urn:li:member:(\d+)', html)
                    member_id = member_match.group(1) if member_match else ""
                    print(f"[linkedin] scraped {public_id!r} from page → {profile_id}", flush=True)
                    return {"linkedin_profile_id": profile_id, "linkedin_member_id": member_id}

                # Also try the fsd_profile format
                fsd_match = _re.search(r'urn:li:fsd_profile:(ACoA[A-Za-z0-9_-]+)', html)
                if fsd_match:
                    profile_id = fsd_match.group(1)
                    member_match = _re.search(r'urn:li:member:(\d+)', html)
                    member_id = member_match.group(1) if member_match else ""
                    print(f"[linkedin] scraped (fsd) {public_id!r} from page → {profile_id}", flush=True)
                    return {"linkedin_profile_id": profile_id, "linkedin_member_id": member_id}

                print(f"[linkedin] profile page loaded but no URN found for {public_id!r}", flush=True)
            else:
                print(f"[linkedin] profile page HTTP {page_resp.status_code} for {public_id!r}", flush=True)

        print(f"[linkedin] all methods failed for {public_id!r}", flush=True)
        return None

    except Exception as e:
        print(f"[linkedin] lookup_profile error for {public_id!r}: {e}", flush=True)
        return None


async def resolve_lead_ids(
    linkedin_url: str,
    li_at: str,
    jsessionid: str,
    bcookie: str = "",
    bscookie: str = "",
) -> Optional[Dict[str, str]]:
    """
    Given a LinkedIn profile URL, resolve it to internal profile/member IDs.
    Returns None if resolution fails.
    """
    public_id = _extract_public_id(linkedin_url)
    if not public_id:
        return None
    return await lookup_profile(public_id, li_at, jsessionid, bcookie, bscookie)


# ──────────────────────────────────────────────────────────────────────────────
# Connection requests
# ──────────────────────────────────────────────────────────────────────────────

async def send_connection_request(
    profile_id: str,
    note: str,
    li_at: str,
    jsessionid: str,
    bcookie: str = "",
    bscookie: str = "",
    extra_cookies: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Send a LinkedIn connection request with a personalised note.
    profile_id: the ACoAAA... part from the miniProfile entityUrn.
    note: ≤300 characters.
    """
    tracking_id = base64.b64encode(os.urandom(16)).decode("utf-8")
    payload = {
        "trackingId": tracking_id,
        "invitations": [],
        "excludeInvitations": [],
        "invitee": {
            "com.linkedin.voyager.growth.invitation.InviteeProfile": {
                "profileId": profile_id
            }
        },
        "message": note[:300],
    }

    hdrs = _headers(jsessionid)
    hdrs["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=hdrs,
            cookies=_cookies(li_at, jsessionid, bcookie, bscookie, extra_cookies),
            follow_redirects=False,
        ) as c:
            resp = await c.post(
                f"{BASE_URL}/voyager/api/growth/normInvitations",
                json=payload,
            )

        print(f"[linkedin] connection request → HTTP {resp.status_code}", flush=True)

        if resp.is_redirect:
            return {"success": False, "error": "Session expired — reconnect LinkedIn in Settings"}
        if resp.status_code in (200, 201):
            return {"success": True}
        if resp.status_code == 429:
            return {"success": False, "error": "Rate limited by LinkedIn — slow down and retry later"}
        if resp.status_code == 403:
            body = resp.text[:200]
            if "FUSE" in body or "limit" in body.lower():
                return {"success": False, "error": "LinkedIn weekly connection limit reached"}
            return {
                "success": False,
                "error": "Auth error (403) — disconnect and use Sign in with LinkedIn in Settings",
            }
        if resp.status_code == 400:
            detail = resp.text[:300]
            if "CUSTOM_MESSAGE_TOO_LONG" in detail:
                return {"success": False, "error": "Connection note too long (max 300 chars)"}
            if "INVITATION_ALREADY_SENT" in detail or "already" in detail.lower():
                return {"success": False, "error": "Connection request already sent to this person"}
            return {"success": False, "error": f"Bad request: {detail[:120]}"}
        return {"success": False, "error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_connection_request_from_session(
    sess: Dict[str, Any], profile_id: str, note: str
) -> Dict[str, Any]:
    """Send connection request using full saved session (all cookies)."""
    return await send_connection_request(
        profile_id=profile_id,
        note=note,
        li_at=sess["li_at"],
        jsessionid=sess.get("jsessionid", "ajax:0"),
        bcookie=sess.get("bcookie", ""),
        bscookie=sess.get("bscookie", ""),
        extra_cookies=_extra_cookies_from_session(sess),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Messaging
# ──────────────────────────────────────────────────────────────────────────────

async def send_message(
    member_id: str,
    message: str,
    li_at: str,
    jsessionid: str,
    bcookie: str = "",
    bscookie: str = "",
    extra_cookies: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Send a LinkedIn direct message to an existing connection.
    member_id: the numeric ID from urn:li:member:<id>.
    """
    payload = {
        "keyVersion": "LEGACY_INBOX",
        "conversationCreate": {
            "eventCreate": {
                "value": {
                    "com.linkedin.voyager.messaging.create.MessageCreate": {
                        "attributedBody": {
                            "text": message,
                            "attributes": [],
                        },
                        "attachments": [],
                    }
                }
            },
            "recipients": [f"urn:li:member:{member_id}"],
            "subtype": "MEMBER_TO_MEMBER",
        },
    }

    hdrs = _headers(jsessionid)
    hdrs["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=hdrs,
            cookies=_cookies(li_at, jsessionid, bcookie, bscookie, extra_cookies),
            follow_redirects=False,
        ) as c:
            resp = await c.post(
                f"{BASE_URL}/voyager/api/messaging/conversations",
                params={"action": "create"},
                json=payload,
            )

        print(f"[linkedin] send message → HTTP {resp.status_code}", flush=True)

        if resp.is_redirect:
            return {"success": False, "error": "Session expired — reconnect LinkedIn in Settings"}
        if resp.status_code in (200, 201):
            return {"success": True}
        if resp.status_code == 429:
            return {"success": False, "error": "Rate limited — slow down and retry later"}
        if resp.status_code == 403:
            return {
                "success": False,
                "error": "Cannot message (403) — must be connected first, or reconnect in Settings",
            }
        return {"success": False, "error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_message_from_session(
    sess: Dict[str, Any], member_id: str, message: str
) -> Dict[str, Any]:
    return await send_message(
        member_id=member_id,
        message=message,
        li_at=sess["li_at"],
        jsessionid=sess.get("jsessionid", "ajax:0"),
        bcookie=sess.get("bcookie", ""),
        bscookie=sess.get("bscookie", ""),
        extra_cookies=_extra_cookies_from_session(sess),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Human-paced delay to avoid LinkedIn rate limiting
# ──────────────────────────────────────────────────────────────────────────────

async def human_delay(min_s: float = 3.0, max_s: float = 8.0) -> None:
    """Sleep a random human-paced interval to avoid rate limits."""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def check_connection_accepted(
    member_id: str,
    li_at: str,
    jsessionid: str,
    bcookie: str = "",
    bscookie: str = "",
) -> bool:
    """
    Return True if we appear to be 1st-degree connected (can message).
    Uses the messaging conversations endpoint — a thread existing implies connection.
    """
    if not member_id:
        return False
    url = (
        f"{BASE_URL}/voyager/api/messaging/conversations"
        f"?q=participants&recipients=urn:li:member:{member_id}"
    )
    try:
        async with httpx.AsyncClient(
            timeout=12.0,
            headers=_headers(jsessionid),
            cookies=_cookies(li_at, jsessionid, bcookie, bscookie),
            follow_redirects=False,
        ) as c:
            resp = await c.get(url)
        if resp.is_redirect or resp.status_code in (401, 403):
            return False
        if resp.status_code != 200:
            return False
        data = resp.json()
        elements = data.get("elements") or data.get("data", {}).get("*elements") or []
        if elements:
            return True
        # Fallback: included conversations
        included = data.get("included") or []
        for item in included:
            if item.get("$type", "").endswith("Conversation") or "conversation" in str(item.get("entityUrn", "")).lower():
                return True
        return False
    except Exception:
        return False
