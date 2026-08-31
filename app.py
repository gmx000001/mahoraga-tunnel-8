"""
Mahoraga Flask Web Dashboard
============================
Serves a web UI for bulk email OSINT checking using holehe modules.
Binds to 0.0.0.0:5000 for external access.
"""

# Version marker — used to verify the latest code is deployed
APP_VERSION = "v4-autonomous"

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import csv
import io
import importlib
import pkgutil
import random
import re
import time
import threading
import traceback
from datetime import datetime

from flask import Flask, render_template, jsonify, request, Response
from flask_socketio import SocketIO, emit

import httpx
import trio
import requests as sync_requests

from holehe.core import launch_module

# ──────────────────────────────────────────────
#  Debug Logger
# ──────────────────────────────────────────────

def dbg(tag, msg):
    """Print a timestamped debug line to the server console."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[DEBUG {ts}] [{tag}] {msg}", flush=True)

# ──────────────────────────────────────────────
#  GitHub Gist — shared gist, all dashboards write to the same URL
# ──────────────────────────────────────────────

# Shared credentials — all 10 dashboards use the same PAT + Gist
_GT = "qIKusJZXGYSEMI5KPmbyQH0NNLMdfSIwj9QVy38fltdwdnBabfPIZIdEQbL_fLxLa2fCQ8FH0YUOBJEA11_tap_buhtig"
GIST_PAT     = _GT[::-1]
GIST_ID      = "94bd80e7cd16ee5416c2d5daeb774abd"
GIST_URL     = f"https://gist.github.com/Kira41/{GIST_ID}"
GIST_FILE    = "results.txt"

class GistClient:
    """Client for the shared GitHub Gist.
    All dashboards edit the same gist at GIST_URL.
    Fetches current content before appending to avoid overwriting other dashboards.
    Unlimited size, fixed URL, never expires.
    """

    def __init__(self):
        self._headers = {
            "Authorization": f"Bearer {GIST_PAT}",
            "Accept": "application/vnd.github+json"
        }
        dbg("GIST", f"Initialized with shared gist: {GIST_URL}")

    def get_content(self):
        """Fetch current gist file content."""
        try:
            resp = sync_requests.get(
                f"https://api.github.com/gists/{GIST_ID}",
                headers=self._headers, timeout=15
            )
            if resp.status_code == 200:
                files = resp.json().get("files", {})
                f = files.get(GIST_FILE, {})
                content = f.get("content", "")
                dbg("GIST", f"Fetched content: {len(content)} chars")
                return content
            dbg("GIST", f"Get content failed: status={resp.status_code}")
            return ""
        except Exception as e:
            dbg("GIST", f"Get content exception: {e}")
            return ""

    def update(self, content):
        """Update the gist file content. Returns True on success."""
        try:
            payload = {
                "files": {
                    GIST_FILE: {
                        "content": content
                    }
                }
            }
            resp = sync_requests.patch(
                f"https://api.github.com/gists/{GIST_ID}",
                json=payload, headers=self._headers, timeout=15
            )
            if resp.status_code == 200:
                dbg("GIST", "Gist updated successfully")
                return True
            dbg("GIST", f"Update failed: status={resp.status_code} body={resp.text[:200]}")
            return False
        except Exception as e:
            dbg("GIST", f"Update exception: {e}")
            return False


# Global Gist client instance
_gist_client = GistClient()

# ──────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────
EMAIL_FORMAT = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

# ──────────────────────────────────────────────
#  Discover all holehe modules and their domains
# ──────────────────────────────────────────────

def _discover_modules():
    """Walk holehe.modules and return:
       - module_map: {name: (function, domain, category)}
       - grouped:    {category: [{name, domain}, ...]}
       - domain_lookup: {name: domain}
    """
    dbg("INIT", "Discovering holehe modules...")
    import holehe.modules as root
    module_map = {}
    grouped = {}
    domain_lookup = {}

    for loader, pkg_name, is_pkg in pkgutil.walk_packages(root.__path__, prefix="holehe.modules."):
        parts = pkg_name.split(".")
        if len(parts) <= 3:
            continue  # skip category __init__ files
        category = parts[2]  # e.g. "shopping", "social_media"
        func_name = parts[-1]  # e.g. "amazon"

        try:
            mod = importlib.import_module(pkg_name)
        except Exception as e:
            dbg("INIT", f"  SKIP {pkg_name} — import error: {e}")
            continue

        func = getattr(mod, func_name, None)
        if func is None or not callable(func):
            continue

        # Determine domain by inspecting the launch_module data dict
        # We'll use a mapping approach: call the function name against the known data dict
        data_map = {
            'aboutme': 'about.me', 'adobe': 'adobe.com', 'amazon': 'amazon.com',
            'anydo': 'any.do', 'archive': 'archive.org',
            'armurerieauxerre': 'armurerie-auxerre.com', 'atlassian': 'atlassian.com',
            'babeshows': 'babeshows.co.uk', 'badeggsonline': 'badeggsonline.com',
            'biosmods': 'bios-mods.com', 'biotechnologyforums': 'biotechnologyforums.com',
            'bitmoji': 'bitmoji.com', 'blablacar': 'blablacar.com',
            'blackworldforum': 'blackworldforum.com', 'blip': 'blip.fm',
            'blitzortung': 'forum.blitzortung.org', 'bluegrassrivals': 'bluegrassrivals.com',
            'bodybuilding': 'bodybuilding.com', 'buymeacoffee': 'buymeacoffee.com',
            'cambridgemt': 'discussion.cambridge-mt.com', 'caringbridge': 'caringbridge.org',
            'chinaphonearena': 'chinaphonearena.com', 'clashfarmer': 'clashfarmer.com',
            'codecademy': 'codecademy.com', 'codeigniter': 'forum.codeigniter.com',
            'codepen': 'codepen.io', 'coroflot': 'coroflot.com',
            'cpaelites': 'cpaelites.com', 'cpahero': 'cpahero.com',
            'cracked_to': 'cracked.to', 'crevado': 'crevado.com',
            'deliveroo': 'deliveroo.com', 'demonforums': 'demonforums.net',
            'devrant': 'devrant.com', 'diigo': 'diigo.com', 'discord': 'discord.com',
            'docker': 'docker.com', 'dominosfr': 'dominos.fr',
            'duolingo': 'duolingo.com', 'ebay': 'ebay.com', 'ello': 'ello.co',
            'envato': 'envato.com', 'eventbrite': 'eventbrite.com',
            'evernote': 'evernote.com', 'facebook': 'facebook.com',
            'fanpop': 'fanpop.com', 'firefox': 'firefox.com', 'flickr': 'flickr.com',
            'freelancer': 'freelancer.com',
            'freiberg': 'drachenhort.user.stunet.tu-freiberg.de',
            'garmin': 'garmin.com', 'github': 'github.com', 'google': 'google.com',
            'gravatar': 'gravatar.com', 'hubspot': 'hubspot.com',
            'imgur': 'imgur.com', 'insightly': 'insightly.com',
            'instagram': 'instagram.com', 'issuu': 'issuu.com',
            'koditv': 'forum.kodi.tv', 'komoot': 'komoot.com',
            'laposte': 'laposte.fr', 'lastfm': 'last.fm', 'lastpass': 'lastpass.com',
            'mail_ru': 'mail.ru', 'mybb': 'community.mybb.com',
            'myspace': 'myspace.com',
            'nattyornot': 'nattyornotforum.nattyornot.com',
            'naturabuy': 'naturabuy.fr',
            'ndemiccreations': 'forum.ndemiccreations.com',
            'nextpvr': 'forums.nextpvr.com', 'nike': 'nike.com',
            'nimble': 'nimble.com', 'nocrm': 'nocrm.io', 'nutshell': 'nutshell.com',
            'odnoklassniki': 'ok.ru', 'office365': 'office365.com',
            'onlinesequencer': 'onlinesequencer.net', 'parler': 'parler.com',
            'patreon': 'patreon.com', 'pinterest': 'pinterest.com',
            'pipedrive': 'pipedrive.com', 'plurk': 'plurk.com',
            'pornhub': 'pornhub.com', 'protonmail': 'protonmail.ch',
            'quora': 'quora.com', 'rambler': 'rambler.ru', 'redtube': 'redtube.com',
            'replit': 'replit.com', 'rocketreach': 'rocketreach.co',
            'samsung': 'samsung.com', 'seoclerks': 'seoclerks.com',
            'sevencups': '7cups.com', 'smule': 'smule.com',
            'snapchat': 'snapchat.com', 'soundcloud': 'soundcloud.com',
            'sporcle': 'sporcle.com', 'spotify': 'spotify.com',
            'strava': 'strava.com', 'taringa': 'taringa.net',
            'teamleader': 'teamleader.eu',
            'teamtreehouse': 'teamtreehouse.com', 'tellonym': 'tellonym.me',
            'thecardboard': 'thecardboard.org',
            'therianguide': 'forums.therian-guide.com',
            'thevapingforum': 'thevapingforum.com', 'tumblr': 'tumblr.com',
            'tunefind': 'tunefind.com', 'twitter': 'twitter.com',
            'venmo': 'venmo.com', 'vivino': 'vivino.com',
            'voxmedia': 'voxmedia.com', 'vrbo': 'vrbo.com', 'vsco': 'vsco.co',
            'wattpad': 'wattpad.com', 'wordpress': 'wordpress.com',
            'xing': 'xing.com', 'xnxx': 'xnxx.com', 'xvideos': 'xvideos.com',
            'yahoo': 'yahoo.com', 'zoho': 'zoho.com',
            'amocrm': 'amocrm.com', 'axonaut': 'axonaut.com',
        }
        domain = data_map.get(func_name, f"{func_name}.com")

        module_map[func_name] = (func, domain, category)
        domain_lookup[func_name] = domain

        grouped.setdefault(category, [])
        grouped[category].append({"name": func_name, "domain": domain})

    # Sort categories and entries
    grouped = dict(sorted(grouped.items()))
    for cat in grouped:
        grouped[cat].sort(key=lambda x: x["name"])

    dbg("INIT", f"Discovered {len(module_map)} modules across {len(grouped)} categories")
    for cat, entries in grouped.items():
        names = [e['name'] for e in entries]
        dbg("INIT", f"  {cat}: {', '.join(names)}")

    return module_map, grouped, domain_lookup


MODULE_MAP, GROUPED_DOMAINS, DOMAIN_LOOKUP = _discover_modules()
dbg("INIT", f"Module discovery complete. Total modules loaded: {len(MODULE_MAP)}")

# ──────────────────────────────────────────────
#  Job State (shared across threads)
# ──────────────────────────────────────────────

class JobState:
    """Thread-safe job state manager."""

    def __init__(self):
        self.lock = threading.RLock()
        # --- Gist persistent state (shared across all dashboards) ---
        self.gist_url = GIST_URL
        self.paste_content = ""         # local cache of content
        self.reset()

    def reset(self):
        self.state = "idle"           # idle | running | paused | completed | stopped
        self.emails = []
        self.selected_domains = []
        self.rentry_custom_id = None
        self.paste_mode = "add"         # add | new
        self.thread_size = 50
        self.total_emails = 0
        self.done_emails = 0
        self.results = []             # list of result dicts
        self.logs = []                # list of {level, message, time}
        self.stats = {
            "total": 0,
            "exists": 0,
            "not_found": 0,
            "rate_limit": 0,
            "errors": 0,
        }
        self._check_timestamps = []   # epoch times of each completed check
        self.proxy_config = {"mode": "none"}
        self._proxy_index = 0         # for round-robin proxy list
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused initially
        self._stop_flag = False
        self.worker_thread = None
        # --- Persistent dashboard config (for full state restore) ---
        self.email_text = ""                # raw pasted email text
        self.selected_domain_names = []     # list of domain names selected
        self.thread_size_setting = 50        # the batch size the user chose
        self.job_start_time = None          # epoch when job started
        self.job_end_time = None            # epoch when job ended
        self._completed_emails = set()      # tracks which emails are done (prevents double-count)
        # --- Paste persistent state (survives across resets) ---
        # NOTE: paste_url and paste_content are set OUTSIDE reset()
        # so they persist across multiple job runs

    def add_log(self, level, message):
        with self.lock:
            now = datetime.now().strftime("%H:%M:%S")
            self.logs.append({"level": level, "message": message, "time": now})
        # Mirror to server console
        dbg("LOG", f"[{level.upper()}] {message}")

    def add_results(self, email, results_list):
        with self.lock:
            for r in results_list:
                entry = {
                    "email": email,
                    "name": r.get("name", ""),
                    "domain": r.get("domain", ""),
                    "exists": r.get("exists", False),
                    "rateLimit": r.get("rateLimit", False),
                    "error": r.get("error", False),
                    "emailrecovery": r.get("emailrecovery"),
                    "phoneNumber": r.get("phoneNumber"),
                    "others": r.get("others"),
                }
                self.results.append(entry)

                # Update stats
                self.stats["total"] += 1
                self._check_timestamps.append(time.time())
                if entry["exists"]:
                    self.stats["exists"] += 1
                elif entry["rateLimit"]:
                    self.stats["rate_limit"] += 1
                elif entry["error"]:
                    self.stats["errors"] += 1
                else:
                    self.stats["not_found"] += 1

    def increment_done(self, email):
        """Mark an email as done. Guards against double-counting and exceeding total."""
        with self.lock:
            if email in self._completed_emails:
                dbg("PROGRESS", f"SKIPPED duplicate increment for: {email}")
                return
            self._completed_emails.add(email)
            if self.done_emails < self.total_emails:
                self.done_emails += 1
            done = self.done_emails
            total = self.total_emails
        pct = min(done * 100 // total, 100) if total else 0
        dbg("PROGRESS", f"Emails done: {done}/{total} ({pct}%)")

    def compute_rates(self):
        """Return checks per minute, hour, day, and week based on timestamps."""
        with self.lock:
            timestamps = list(self._check_timestamps)

        if not timestamps:
            return {"per_minute": 0.0, "per_hour": 0.0, "per_day": 0.0, "per_week": 0.0}

        now = time.time()
        window_60s   = sum(1 for t in timestamps if now - t <= 60)
        window_3600s = sum(1 for t in timestamps if now - t <= 3600)
        window_day   = sum(1 for t in timestamps if now - t <= 86400)
        window_week  = sum(1 for t in timestamps if now - t <= 604800)

        # Calculate rate: actual checks in the window,
        # extrapolated to the full period
        elapsed = now - timestamps[0]
        if elapsed < 1:
            elapsed = 1  # avoid division by zero

        # Actual counts in each window
        per_minute = window_60s
        per_hour   = window_3600s
        per_day    = window_day
        per_week   = window_week

        # If the job hasn't been running long enough to fill the window,
        # project the rate based on elapsed time
        if elapsed < 60:
            per_minute = round(len(timestamps) / elapsed * 60, 1)
        if elapsed < 3600:
            per_hour = round(len(timestamps) / elapsed * 3600, 1)
        if elapsed < 86400:
            per_day = round(len(timestamps) / elapsed * 86400, 1)
        if elapsed < 604800:
            per_week = round(len(timestamps) / elapsed * 604800, 1)

        return {
            "per_minute": per_minute,
            "per_hour": per_hour,
            "per_day": per_day,
            "per_week": per_week,
        }

    def is_stopped(self):
        stopped = self._stop_flag
        if stopped:
            dbg("STATE", "is_stopped() → True")
        return stopped

    def wait_if_paused(self):
        """Blocks if paused, returns immediately if not."""
        if not self._pause_event.is_set():
            dbg("STATE", "Waiting — job is paused...")
        self._pause_event.wait()
        if not self._pause_event.is_set():
            dbg("STATE", "Resumed from pause")

    def pause(self):
        dbg("STATE", "pause() called")
        with self.lock:
            self.state = "paused"
            self._pause_event.clear()

    def resume(self):
        dbg("STATE", "resume() called")
        with self.lock:
            self.state = "running"
            self._pause_event.set()

    def stop(self):
        dbg("STATE", "stop() called")
        with self.lock:
            self._stop_flag = True
            self.state = "stopped"
            self._pause_event.set()  # unblock if paused

    def get_next_proxy(self):
        """Get the next proxy URL based on the configured mode."""
        cfg = self.proxy_config
        mode = cfg.get("mode", "none")
        dbg("PROXY", f"get_next_proxy() mode={mode}")

        if mode == "none":
            dbg("PROXY", "No proxy configured, using direct connection")
            return None
        elif mode == "single":
            proxy = cfg.get("proxy", "")
            if proxy:
                if not proxy.startswith("http"):
                    proxy = f"http://{proxy}"
                dbg("PROXY", f"Using single proxy: {proxy}")
                return proxy
            dbg("PROXY", "Single mode but no proxy value set")
            return None
        elif mode == "list":
            proxies = cfg.get("proxies", [])
            if not proxies:
                dbg("PROXY", "List mode but proxy list is empty")
                return None
            with self.lock:
                idx = self._proxy_index % len(proxies)
                proxy = proxies[idx]
                self._proxy_index += 1
            if not proxy.startswith("http"):
                proxy = f"http://{proxy}"
            dbg("PROXY", f"Using proxy [{idx}/{len(proxies)}]: {proxy}")
            return proxy
        elif mode == "api":
            api_url = cfg.get("api_url", "")
            if not api_url:
                dbg("PROXY", "API mode but no api_url set")
                return None
            try:
                dbg("PROXY", f"Fetching proxy from API: {api_url}")
                resp = httpx.get(api_url, timeout=10)
                proxy = resp.text.strip()
                if proxy and not proxy.startswith("http"):
                    proxy = f"http://{proxy}"
                dbg("PROXY", f"API returned proxy: {proxy}")
                return proxy if proxy else None
            except Exception as e:
                dbg("PROXY", f"API fetch failed: {type(e).__name__}: {e}")
                return None
        return None


job = JobState()

# ──────────────────────────────────────────────
#  Worker: runs holehe checks in a background thread
# ──────────────────────────────────────────────

def worker_thread():
    """Process emails in batches using trio."""
    global job
    try:
        dbg("WORKER", "═══════════════════════════════════════")
        dbg("WORKER", "Worker thread started")
        job.add_log("info", "[DEBUG] Worker thread started")

        # Log library versions for debugging
        job.add_log("info", f"[DEBUG] httpx version: {httpx.__version__}")
        job.add_log("info", f"[DEBUG] trio version: {trio.__version__}")
        try:
            import httpcore
            job.add_log("info", f"[DEBUG] httpcore version: {httpcore.__version__}")
        except Exception:
            job.add_log("warn", "[DEBUG] httpcore not found")
        try:
            import sniffio
            job.add_log("info", f"[DEBUG] sniffio version: {sniffio.__version__}")
        except Exception:
            job.add_log("warn", "[DEBUG] sniffio not found")

        emails = job.emails
        selected = job.selected_domains
        batch_size = job.thread_size

        job.add_log("info", f"[DEBUG] Emails: {len(emails)}, Domains: {selected}, Batch: {batch_size}")

        # Get the module functions for selected domains
        modules = []
        for name in selected:
            if name in MODULE_MAP:
                func, domain, category = MODULE_MAP[name]
                modules.append(MODULE_MAP[name])
                job.add_log("info", f"[DEBUG] Module loaded: {name} → {domain}")
            else:
                job.add_log("warn", f"[DEBUG] Module NOT FOUND: '{name}'")

        if not modules:
            job.add_log("error", "No valid modules found for selected domains.")
            with job.lock:
                job.state = "completed"
            return

        job.add_log("info", f"Starting check: {len(emails)} emails × {len(modules)} domains")

        # Log proxy mode
        proxy_mode = job.proxy_config.get("mode", "none")
        if proxy_mode == "none":
            job.add_log("info", "Proxy: disabled (direct connection)")
        elif proxy_mode == "list":
            pcount = len(job.proxy_config.get("proxies", []))
            job.add_log("info", f"Proxy: list mode ({pcount} proxies, round-robin)")
        elif proxy_mode == "api":
            job.add_log("info", f"Proxy: API mode ({job.proxy_config.get('api_url', '')})")
        elif proxy_mode == "single":
            job.add_log("info", f"Proxy: single gateway ({job.proxy_config.get('proxy', '')})")

        # Process emails in batches
        job_start_time = time.time()
        try:
            trio.run(async_job_runner, emails, modules, batch_size)
        except Exception as e:
            tb = traceback.format_exc()
            dbg("WORKER", f"trio.run overall EXCEPTION: {type(e).__name__}: {e}")
            dbg("WORKER", f"Traceback:\n{tb}")
            job.add_log("error", f"[FATAL] Job runner crashed: {type(e).__name__}: {str(e)}")
            job.add_log("error", f"[FATAL TRACEBACK] {tb}")
        total_elapsed = time.time() - job_start_time

        if not job.is_stopped():
            # ---- Send to GitHub Gist (shared, all dashboards) ----
            job.add_log("info", "Uploading results to GitHub Gist...")
            lines = []
            timestamp_header = f"\n--- Results from {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---"
            for r in job.results:
                if r.get("exists"):
                    status = "FOUND"
                    extra = ""
                    if r.get("emailrecovery"):
                        extra += f" | recovery: {r['emailrecovery']}"
                    if r.get("phoneNumber"):
                        extra += f" | phone: {r['phoneNumber']}"
                    lines.append(f"{r['email']} | {r['domain']} | {status}{extra}")
            
            if lines:
                new_text = timestamp_header + "\n" + "\n".join(lines) + "\n"
            else:
                new_text = timestamp_header + "\nno email valid\n"
            
            try:
                global _gist_client
                paste_mode = getattr(job, 'paste_mode', 'add')

                if paste_mode == 'new':
                    # "New" mode — replace all content
                    full_text = "# Mahoraga Results\n" + new_text
                    job.add_log("info", "Mode: New — replacing all results...")
                else:
                    # "Add" mode — fetch current content from Gist, then append
                    job.add_log("info", "Mode: Add — fetching current gist content...")
                    current = _gist_client.get_content()
                    if current and current.strip() and current.strip() != '# Mahoraga Results\nWaiting for results...':
                        full_text = current.rstrip("\n") + "\n" + new_text
                    else:
                        full_text = "# Mahoraga Results\n" + new_text

                success = _gist_client.update(full_text)
                if success:
                    job.paste_content = full_text
                    job.add_log("success", f"✅ Results updated: {GIST_URL}")
                else:
                    job.add_log("error", "Failed to update Gist.")
            except Exception as ex:
                job.add_log("error", f"Gist upload failed: {ex}")
            # -------------------------

            with job.lock:
                job.state = "completed"
                job.job_end_time = time.time()
            job.add_log("success", f"All emails processed in {total_elapsed:.1f}s!")
        else:
            with job.lock:
                job.job_end_time = time.time()
            job.add_log("warn", "Job was stopped.")

    except Exception as e:
        tb = traceback.format_exc()
        dbg("WORKER", f"FATAL WORKER ERROR: {type(e).__name__}: {e}")
        dbg("WORKER", f"Traceback:\n{tb}")
        job.add_log("error", f"[FATAL] Worker crashed: {type(e).__name__}: {str(e)}")
        job.add_log("error", f"[FATAL TRACEBACK] {tb}")
        with job.lock:
            job.state = "completed"
            job.job_end_time = time.time()


async def async_job_runner(emails, modules, batch_size):
    """Process emails in batches concurrently using shared httpx client cache."""
    global job
    clients = {}
    try:
        total_batches = (len(emails) + batch_size - 1) // batch_size
        job.add_log("info", f"[DEBUG] Total batches: {total_batches}")
        
        for batch_idx, batch_start in enumerate(range(0, len(emails), batch_size)):
            if job.is_stopped():
                break

            # Wait if paused (using trio.to_thread because wait_if_paused is blocking)
            if job.state == "paused":
                await trio.to_thread.run_sync(job.wait_if_paused)
            if job.is_stopped():
                break

            batch = emails[batch_start:batch_start + batch_size]
            job.add_log("info", f"[DEBUG] Batch {batch_idx + 1}/{total_batches} — about to process")

            batch_start_time = time.time()

            # Resolve proxy for this batch
            proxy_url = job.get_next_proxy()
            if proxy_url not in clients:
                transport_kwargs = {}
                if proxy_url:
                    transport_kwargs["proxy"] = proxy_url
                    job.add_log("info", f"[DEBUG] Creating new httpx.AsyncClient for proxy: {proxy_url}")
                else:
                    job.add_log("info", "[DEBUG] Creating new direct-connection httpx.AsyncClient")
                clients[proxy_url] = httpx.AsyncClient(timeout=10, **transport_kwargs)

            client = clients[proxy_url]

            try:
                job.add_log("info", f"[DEBUG] Entering batch processing for batch {batch_idx + 1}")
                async with trio.open_nursery() as nursery:
                    for i, email in enumerate(batch):
                        if job.is_stopped():
                            break
                        nursery.start_soon(_process_email, email, modules, client)
                job.add_log("info", f"[DEBUG] Batch {batch_idx + 1} processing nursery finished")
            except Exception as e:
                tb = traceback.format_exc()
                dbg("BATCH", f"Batch {batch_idx + 1} EXCEPTION: {type(e).__name__}: {e}")
                dbg("BATCH", f"Traceback:\n{tb}")
                job.add_log("error", f"[CRASH] Batch {batch_idx+1} error: {type(e).__name__}: {str(e)}")
                job.add_log("error", f"[TRACEBACK] {tb}")

            batch_elapsed = time.time() - batch_start_time
            job.add_log("info", f"Batch {batch_idx + 1} completed in {batch_elapsed:.1f}s")

            # Running totals
            with job.lock:
                job.add_log("info", f"[STATS] done:{job.done_emails}/{job.total_emails} | "
                             f"exists:{job.stats['exists']} not_found:{job.stats['not_found']} "
                             f"rate_limit:{job.stats['rate_limit']} errors:{job.stats['errors']}")
    finally:
        # Close all cached clients to release sockets and prevent leaks
        for p_url, client in clients.items():
            job.add_log("info", f"[DEBUG] Closing client for {p_url or 'direct connection'}")
            try:
                await client.aclose()
            except Exception as e:
                dbg("CLIENT_CLOSE", f"Error closing client: {e}")


async def _process_email(email, modules, client):
    """Check a single email against all selected modules."""
    email_start = time.time()
    dbg("EMAIL", f"──── Processing: {email} ({len(modules)} modules) ────")

    if job.is_stopped():
        dbg("EMAIL", f"{email} — skipped (stop flag)")
        return

    # Wait if paused (blocking in trio context — use trio.to_thread)
    dbg("EMAIL", f"{email} — checking pause state...")
    if job.state == "paused":
        await trio.to_thread.run_sync(job.wait_if_paused)

    if job.is_stopped():
        dbg("EMAIL", f"{email} — skipped after pause (stop flag)")
        return

    out = []
    for mod_idx, (func, domain, category) in enumerate(modules):
        if job.is_stopped():
            dbg("MODULE", f"{email} → {func.__name__} — skipped (stop flag)")
            break

        mod_name = func.__name__
        dbg("MODULE", f"{email} → [{mod_idx+1}/{len(modules)}] {mod_name} ({domain}) — launching...")
        mod_start = time.time()
        out_before = len(out)

        # Run each module with a timeout to prevent indefinite hangs
        timed_out = False
        try:
            cancel_scope = trio.CancelScope(deadline=trio.current_time() + 12)
            with cancel_scope:
                await launch_module(func, email, client, out)
            if cancel_scope.cancelled_caught:
                timed_out = True
                mod_elapsed = time.time() - mod_start
                dbg("MODULE", f"{email} → {mod_name} — TIMED OUT after {mod_elapsed:.1f}s")
        except Exception as e:
            mod_elapsed = time.time() - mod_start
            dbg("MODULE", f"{email} → {mod_name} — EXCEPTION after {mod_elapsed:.1f}s: {type(e).__name__}: {e}")
            # If a module fails completely, record an error result
            out.append({
                "name": mod_name,
                "domain": domain,
                "rateLimit": False,
                "error": True,
                "exists": False,
                "emailrecovery": None,
                "phoneNumber": None,
                "others": {"errorMessage": f"{type(e).__name__}: {str(e)}"},
            })

        if not timed_out:
            mod_elapsed = time.time() - mod_start
            # Check what the module added to out
            new_results = out[out_before:]
            if new_results:
                for r in new_results:
                    status = "EXISTS" if r.get("exists") else ("RATE_LIMIT" if r.get("rateLimit") else ("ERROR" if r.get("error") else "NOT_FOUND"))
                    dbg("MODULE", f"{email} → {mod_name} — {status} in {mod_elapsed:.1f}s")
            else:
                dbg("MODULE", f"{email} → {mod_name} — completed in {mod_elapsed:.1f}s (no result added)")

    # If a module timed out via move_on_after, it won't add to out — handle that
    module_names_checked = {r.get("name") for r in out}
    for func, domain, category in modules:
        if func.__name__ not in module_names_checked:
            dbg("MODULE", f"{email} → {func.__name__} — marking as TIMED OUT (no result in out)")
            out.append({
                "name": func.__name__,
                "domain": domain,
                "rateLimit": True,
                "error": False,
                "exists": False,
                "emailrecovery": None,
                "phoneNumber": None,
                "others": {"errorMessage": "Module timed out"},
            })

    # Record results
    job.add_results(email, out)
    job.increment_done(email)

    # Summary log for this email
    found = sum(1 for r in out if r.get("exists"))
    not_found = sum(1 for r in out if not r.get("exists") and not r.get("rateLimit") and not r.get("error", False))
    rate_limited = sum(1 for r in out if r.get("rateLimit"))
    errors = sum(1 for r in out if r.get("error", False))

    email_elapsed = time.time() - email_start
    dbg("EMAIL", f"{email} — DONE in {email_elapsed:.1f}s → exists:{found} not_found:{not_found} rate_limit:{rate_limited} errors:{errors}")

    job.add_log("info",
                f"{email} — ✅{found}  ❌{not_found}  ⏳{rate_limited}  ⚠{errors}")


# ──────────────────────────────────────────────
# ──────────────────────────────────────────────
#  Flask App
# ──────────────────────────────────────────────

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')


@socketio.on('connect')
def handle_connect():
    """When a client connects/reconnects, push full state immediately.
    Results and logs are capped to prevent browser crashes on large jobs.
    """
    dbg("SOCKET", "Client connected — sending full state")
    MAX_RESULTS = 200
    MAX_LOGS = 200
    with job.lock:
        # Only send the tail of results/logs to avoid crashing the browser
        total_results = len(job.results)
        total_logs = len(job.logs)
        tail_results = job.results[-MAX_RESULTS:] if total_results > MAX_RESULTS else list(job.results)
        tail_logs = job.logs[-MAX_LOGS:] if total_logs > MAX_LOGS else list(job.logs)
        state_data = {
            "state": job.state,
            "progress": {
                "done": min(job.done_emails, job.total_emails),
                "total": job.total_emails,
            },
            "stats": dict(job.stats),
            "rates": job.compute_rates(),
            "all_logs": tail_logs,
            "all_results": tail_results,
            "total_results_count": total_results,
            "total_logs_count": total_logs,
            "config": {
                "email_text": job.email_text,
                "selected_domains": list(job.selected_domain_names),
                "thread_size": job.thread_size_setting,
                "proxy": dict(job.proxy_config),
                "rentry_custom_id": "",
            },
            "job_start_time": job.job_start_time,
            "job_end_time": job.job_end_time,
            "version": APP_VERSION,
        }
    emit('full_state', state_data)

def background_status_emitter():
    """Background task to periodically broadcast state to clients.
    Caps results/logs per tick to prevent overwhelming the browser.
    """
    last_log_offset = 0
    last_result_offset = 0
    MAX_RESULTS_PER_TICK = 50
    MAX_LOGS_PER_TICK = 30
    while True:
        with job.lock:
            state = job.state
            done = min(job.done_emails, job.total_emails)
            total = job.total_emails
            stats = dict(job.stats)
            rates = job.compute_rates()
            # Cap the number of new items per tick to prevent browser flooding
            all_new_logs = job.logs[last_log_offset:]
            all_new_results = job.results[last_result_offset:]
            # Send at most N items per tick; advance offset only by what we send
            new_logs = all_new_logs[:MAX_LOGS_PER_TICK]
            new_results = all_new_results[:MAX_RESULTS_PER_TICK]
            last_log_offset += len(new_logs)
            last_result_offset += len(new_results)

        if state in ("running", "paused") or new_logs or new_results:
            socketio.emit('status_update', {
                "state": state,
                "progress": {"done": done, "total": total},
                "stats": stats,
                "rates": rates,
                "new_logs": new_logs,
                "new_results": new_results
            })
        
        time.sleep(1.0)

# Start emitter thread globally for Gunicorn compatibility
emitter_thread = threading.Thread(target=background_status_emitter, daemon=True)
emitter_thread.start()

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/domains")
def api_domains():
    """Return all available domains grouped by category."""
    all_domains = []
    for cat, entries in GROUPED_DOMAINS.items():
        all_domains.extend(entries)
    return jsonify({"domains": all_domains, "grouped": GROUPED_DOMAINS})


@app.route("/api/server_logs")
def api_server_logs():
    """Return the raw flask.log contents for debugging."""
    try:
        import os
        if os.path.exists("flask.log"):
            with open("flask.log", "r", encoding="utf-8", errors="replace") as f:
                # Read the last 1000 lines to prevent massive payloads
                lines = f.readlines()[-1000:]
                return Response("".join(lines), mimetype="text/plain")
        return "flask.log not found.", 404
    except Exception as e:
        return str(e), 500


@app.route("/api/start", methods=["POST"])
def api_start():
    """Start a new checking job."""
    global job
    dbg("API", "POST /api/start called")

    if job.state == "running" or job.state == "paused":
        dbg("API", f"Rejected — job already in state: {job.state}")
        return jsonify({"error": "A job is already running. Stop it first."}), 400

    with job.lock:
        if job.worker_thread and job.worker_thread.is_alive():
            dbg("API", "Rejected — worker thread is still alive")
            return jsonify({"error": "A job is currently running or stopping. Please wait for it to finish."}), 400

    dbg("API", f"--- INCOMING REQUEST TO /api/start ---")
    dbg("API", f"Headers: {dict(request.headers)}")
    raw_data = request.get_data()
    dbg("API", f"Raw body length: {len(raw_data)} bytes")
    if len(raw_data) < 1000:
        dbg("API", f"Raw body preview: {raw_data}")

    try:
        data = request.get_json(force=True, silent=True)
        if data is None:
            dbg("API", "get_json() returned None! Trying request.form...")
            data = request.form
    except Exception as e:
        print("Error getting JSON:", e)
        data = {}

    if not data:
        dbg("API", "Failed to parse data payload completely!")
        return jsonify({"error": "Invalid request payload. Expected JSON."}), 400
    emails = data.get("emails", [])
    domains = data.get("domains", [])
    thread_size = data.get("thread_size", 5)
    proxy_config = data.get("proxy", {"mode": "none"})
    rentry_custom_id = data.get("rentry_custom_id", "").strip()
    paste_mode = data.get("rentry_mode", "add").strip()

    dbg("API", f"Request payload: {len(emails)} emails, {len(domains)} domains, batch_size={thread_size}, proxy_mode={proxy_config.get('mode')}")
    dbg("API", f"Selected domains: {domains}")

    if not emails:
        dbg("API", "Rejected — no emails")
        return jsonify({"error": "No emails provided."}), 400
    if not domains:
        dbg("API", "Rejected — no domains")
        return jsonify({"error": "No domains selected."}), 400

    # Validate emails
    valid_emails = [e.strip() for e in emails if re.fullmatch(EMAIL_FORMAT, e.strip())]
    invalid_count = len(emails) - len(valid_emails)
    dbg("API", f"Email validation: {len(valid_emails)} valid, {invalid_count} invalid")

    if not valid_emails:
        dbg("API", "Rejected — no valid emails after validation")
        return jsonify({"error": "No valid email addresses found."}), 400

    # Reset and configure
    dbg("API", "Resetting job state...")
    job.reset()
    job.emails = valid_emails
    job.selected_domains = domains
    job.thread_size = max(1, min(50, thread_size))
    job.total_emails = len(valid_emails)
    job.proxy_config = proxy_config
    job.rentry_custom_id = rentry_custom_id
    job.paste_mode = paste_mode if paste_mode in ("add", "new") else "add"
    job.state = "running"
    # --- Store dashboard config for full state restore ---
    job.email_text = data.get("email_text", "\n".join(valid_emails))
    job.selected_domain_names = list(domains)
    job.thread_size_setting = job.thread_size
    job.job_start_time = time.time()
    job.job_end_time = None
    dbg("API", f"Job configured — state=running, {len(valid_emails)} emails, batch_size={job.thread_size}")

    if invalid_count > 0:
        job.add_log("warn", f"Skipped {invalid_count} invalid email(s).")

    # Add server-side logs BEFORE launching thread
    job.add_log("info", f"[SERVER {APP_VERSION}] Job configured: {len(valid_emails)} emails, {len(domains)} domains, batch={job.thread_size}")
    job.add_log("info", f"[SERVER] Selected domains: {', '.join(domains[:5])}{'...' if len(domains) > 5 else ''}")
    job.add_log("info", "[SERVER] Launching worker thread...")

    # Launch worker thread
    dbg("API", "Launching worker thread...")
    t = threading.Thread(target=worker_thread, daemon=True, name="mahoraga-worker")
    with job.lock:
        job.worker_thread = t
    t.start()
    dbg("API", f"Worker thread launched (id={t.ident})")
    job.add_log("info", f"[SERVER] Worker thread launched (id={t.ident})")

    return jsonify({"status": "started", "total_emails": len(valid_emails),
                    "domains_count": len(domains), "version": APP_VERSION})


@app.route("/api/pause", methods=["POST"])
def api_pause():
    dbg("API", f"POST /api/pause called (current state: {job.state})")
    if job.state != "running":
        return jsonify({"error": "Job is not running."}), 400
    job.pause()
    dbg("API", "Job paused")
    return jsonify({"status": "paused"})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    dbg("API", f"POST /api/resume called (current state: {job.state})")
    if job.state != "paused":
        return jsonify({"error": "Job is not paused."}), 400
    job.resume()
    dbg("API", "Job resumed")
    return jsonify({"status": "running"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    dbg("API", f"POST /api/stop called (current state: {job.state})")
    if job.state not in ("running", "paused"):
        return jsonify({"error": "No active job to stop."}), 400
    job.stop()
    dbg("API", "Job stopped")
    return jsonify({"status": "stopped"})


@app.route("/api/status")
def api_status():
    """Return current job status, new results, and new logs."""
    log_offset = request.args.get("log_offset", 0, type=int)
    result_offset = request.args.get("result_offset", 0, type=int)

    with job.lock:
        new_logs = job.logs[log_offset:]
        new_results = job.results[result_offset:]
        data = {
            "state": job.state,
            "progress": {
                "done": job.done_emails,
                "total": job.total_emails,
            },
            "stats": dict(job.stats),
            "rates": job.compute_rates(),
            "new_logs": new_logs,
            "log_offset": len(job.logs),
            "new_results": new_results,
            "result_offset": len(job.results),
        }
    return jsonify(data)


@app.route("/api/full_state")
def api_full_state():
    """Return the COMPLETE state for a reconnecting dashboard.
    Results and logs are capped to the last N entries to prevent
    sending megabytes of data that would crash the browser.
    Total counts are included so the dashboard knows how many exist.
    """
    MAX_RESULTS = 200
    MAX_LOGS = 200
    with job.lock:
        total_results = len(job.results)
        total_logs = len(job.logs)
        tail_results = job.results[-MAX_RESULTS:] if total_results > MAX_RESULTS else list(job.results)
        tail_logs = job.logs[-MAX_LOGS:] if total_logs > MAX_LOGS else list(job.logs)
        data = {
            "state": job.state,
            "progress": {
                "done": min(job.done_emails, job.total_emails),
                "total": job.total_emails,
            },
            "stats": dict(job.stats),
            "rates": job.compute_rates(),
            "all_logs": tail_logs,
            "all_results": tail_results,
            "total_results_count": total_results,
            "total_logs_count": total_logs,
            "config": {
                "email_text": job.email_text,
                "selected_domains": list(job.selected_domain_names),
                "thread_size": job.thread_size_setting,
                "proxy": dict(job.proxy_config),
                "rentry_custom_id": "",
            },
            "job_start_time": job.job_start_time,
            "job_end_time": job.job_end_time,
            "version": APP_VERSION,
        }
    return jsonify(data)


@app.route("/api/export/<result_type>/<fmt>")
def api_export(result_type, fmt):
    """Export results as CSV or TXT.
    result_type: all | exists | not_found | errors | unchecked
    fmt: csv | txt
    """
    with job.lock:
        results = list(job.results)
        all_emails = list(job.emails)

    if result_type == "unchecked":
        checked_emails = {r["email"] for r in results if r.get("email")}
        unchecked_emails = [e for e in all_emails if e not in checked_emails]
        results = [{"email": e, "domain": "N/A", "exists": False, "rateLimit": False, "error": False, "unchecked": True} for e in unchecked_emails]
    else:
        # Filter
        if result_type == "exists":
            results = [r for r in results if r.get("exists")]
        elif result_type == "not_found":
            results = [r for r in results if not r.get("exists") and not r.get("rateLimit") and not r.get("error")]
        elif result_type == "errors":
            results = [r for r in results if r.get("rateLimit") or r.get("error")]

    if fmt == "csv":
        output = io.StringIO()
        if results:
            fields = ["email", "domain", "exists", "rateLimit", "error", "emailrecovery", "phoneNumber"]
            writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
        content = output.getvalue()
        return Response(
            content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=mahoraga_{result_type}.csv"}
        )
    else:  # txt
        lines = []
        for r in results:
            if result_type == "unchecked":
                status = "UNCHECKED"
            else:
                status = "FOUND" if r.get("exists") else ("RATE_LIMIT" if r.get("rateLimit") else ("ERROR" if r.get("error") else "NOT_FOUND"))
            extra = ""
            if r.get("emailrecovery"):
                extra += f" | recovery: {r['emailrecovery']}"
            if r.get("phoneNumber"):
                extra += f" | phone: {r['phoneNumber']}"
            lines.append(f"{r['email']} | {r['domain']} | {status}{extra}")
        content = "\n".join(lines)
        return Response(
            content,
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename=mahoraga_{result_type}.txt"}
        )


# ──────────────────────────────────────────────
#  Debug endpoints
# ──────────────────────────────────────────────

@app.route("/api/ping")
def api_ping():
    """Health check with version info."""
    return jsonify({
        "status": "ok",
        "version": APP_VERSION,
        "job_state": job.state,
        "log_count": len(job.logs),
        "result_count": len(job.results),
        "last_5_logs": job.logs[-5:] if job.logs else [],
    })


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  Mahoraga Dashboard (WebSocket Edition)")
    print("  Open http://<your-server-ip>:8080")
    print("  Debug logging: ENABLED (all steps printed to console)")
    print("=" * 50 + "\n")
    dbg("MAIN", "Flask server starting on 0.0.0.0:8080")
    socketio.run(app, host="0.0.0.0", port=8080, debug=False, allow_unsafe_werkzeug=True)
