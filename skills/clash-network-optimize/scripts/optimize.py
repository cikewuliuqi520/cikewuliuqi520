#!/usr/bin/env python3
"""Select a verified OpenAI route in mihomo within a 20-second deadline."""

import argparse
import concurrent.futures
import glob
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path


TARGETS = {"chat": "https://chatgpt.com", "api": "https://api.openai.com/v1/models"}
DELAY_URL = "https://chatgpt.com/cdn-cgi/trace"
WORK_SECONDS = 16.0
CACHE_AGE_SECONDS = 24 * 3600


def expected_status(kind, status):
    return status == (200 if kind == "chat" else 401)


def choose_best(results):
    complete = {
        name: values for name, values in results.items()
        if all(len(values.get(kind, [])) >= 2 and all(v is not None for v in values[kind]) for kind in TARGETS)
    }
    if not complete:
        raise RuntimeError("No candidate passed two real requests to both OpenAI targets")
    return min(complete, key=lambda name: (
        sum(max(complete[name][kind]) for kind in TARGETS),
        sum(statistics.median(complete[name][kind]) for kind in TARGETS),
    ))


def shortlist_candidates(ordered, count, original):
    chosen = ordered[:1]
    for region in ("US", "JP", "SG", "HK"):
        for name in ordered:
            label = name.strip().upper()
            if (label.startswith(region + " -") or label.endswith(" - " + region)) and name not in chosen:
                chosen.append(name)
                break
        if len(chosen) >= count:
            break
    for name in ordered:
        if len(chosen) >= count:
            break
        if name not in chosen:
            chosen.append(name)
    if original not in chosen:
        chosen.append(original)
    return chosen


def cached_candidates(ordered, original, table):
    good = [n for n in ordered if table.get(n, {}).get("ok")]
    good.sort(key=lambda n: table[n].get("worst", 999))
    chosen = good[:2]
    if original not in chosen:
        chosen.append(original)
    for name in ordered:
        if len(chosen) >= 3:
            break
        if name not in chosen and not table.get(name, {}).get("ok") is False:
            chosen.append(name)
    return chosen


def apply_with_rollback(new, original, select, check, current=None):
    if current is not None and current() != original:
        raise RuntimeError("Selection changed before apply; leaving it untouched")
    try:
        select(new)
        if not check():
            raise RuntimeError("Final selection check failed")
    except BaseException:
        if current is None or current() in (new, original):
            select(original)
        raise


class Budget:
    def __init__(self):
        self.start = time.monotonic()
        self.deadline = self.start + WORK_SECONDS
        self.hard_deadline = self.start + 19.0

    def left(self):
        return self.deadline - time.monotonic()

    def limit(self, cap, reserve=1.2):
        available = self.left() - reserve
        if available < 0.3:
            raise RuntimeError("20-second budget nearly exhausted")
        return min(cap, available)

    def finish_limit(self):
        available = self.hard_deadline - time.monotonic() - 0.3
        if available < 0.2:
            raise RuntimeError("20-second hard deadline reached")
        return min(0.6, available)


def curl(args, timeout):
    executable = "curl.exe" if platform.system() == "Windows" else "curl"
    if not shutil.which(executable):
        raise RuntimeError(executable + " is required")
    return subprocess.run(
        [executable, "-sS", "--max-time", "%.2f" % timeout] + args,
        capture_output=True, text=True, timeout=timeout + 0.3,
    )


class Core:
    def __init__(self, endpoint, budget, secret=""):
        self.endpoint, self.budget, self.secret = endpoint, budget, secret

    def request(self, method, path, payload=None, restore=False, timeout_cap=0.8):
        timeout = self.budget.finish_limit() if restore else self.budget.limit(timeout_cap)
        if self.endpoint.startswith("http://"):
            data = json.dumps(payload).encode() if payload is not None else None
            headers = {"Content-Type": "application/json"}
            if self.secret:
                headers["Authorization"] = "Bearer " + self.secret
            request = urllib.request.Request(self.endpoint + path, data=data,
                                             headers=headers, method=method)
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                        request, timeout=timeout) as response:
                    body = response.read()
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as exc:
                raise RuntimeError("Clash core API returned HTTP %s" % exc.code) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise RuntimeError("Clash core API unavailable") from exc
        args = ["--unix-socket", self.endpoint, "-X", method]
        if payload is not None:
            args += ["-H", "Content-Type: application/json", "--data", json.dumps(payload)]
        args += ["-w", "\n%{http_code}", "http://localhost" + path]
        result = curl(args, timeout)
        if result.returncode:
            raise RuntimeError("Clash core API unavailable")
        body, status = result.stdout.rsplit("\n", 1)
        if not status.startswith("2"):
            raise RuntimeError("Clash core API returned HTTP " + status)
        return json.loads(body) if body else None

    def get(self, path, restore=False):
        return self.request("GET", path, restore=restore)

    def current(self, group, restore=False):
        return self.get("/proxies/" + urllib.parse.quote(group, safe=""), restore=restore)["now"]

    def select(self, group, name, restore=False):
        path = "/proxies/" + urllib.parse.quote(group, safe="")
        self.request("PUT", path, {"name": name}, restore=restore)
        if self.current(group, restore=restore) != name:
            raise RuntimeError("Selection verification failed")

    def delay(self, name):
        try:
            path = "/proxies/" + urllib.parse.quote(name, safe="")
            query = urllib.parse.urlencode({"timeout": 900, "url": DELAY_URL})
            data = self.request("GET", path + "/delay?" + query, timeout_cap=1.15)
            return data.get("delay") if isinstance(data.get("delay"), int) else None
        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
            return None


def controller_candidates(system, override=None, uid=None):
    if override:
        parsed = urllib.parse.urlparse(override if "://" in override else "http://" + override)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or not parsed.port:
            raise RuntimeError("Controller must be a local HTTP address, such as 127.0.0.1:9090")
        return ["http://127.0.0.1:%d" % parsed.port]
    if system == "Windows":
        return ["http://127.0.0.1:%d" % port for port in (9090, 9097, 9091, 9092)]
    if system == "Darwin":
        return sorted(glob.glob("/tmp/mihomo-party-%s-*.sock" % uid))
    raise RuntimeError("Only macOS and Windows are supported")


def discover_core(budget, controller=None):
    candidates = controller_candidates(platform.system(), controller,
                                       os.getuid() if hasattr(os, "getuid") else None)
    authorization_failed = False
    for endpoint in candidates:
        core = Core(endpoint, budget, os.environ.get("CLASH_API_SECRET", ""))
        try:
            core.get("/version")
            return core
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            authorization_failed |= "HTTP 401" in str(exc)
    if authorization_failed:
        raise RuntimeError("Local mihomo controller requires CLASH_API_SECRET")
    raise RuntimeError("No running local mihomo controller found; set CLASH_CONTROLLER if its port is custom")


def route_counters(core, group):
    rules = core.get("/rules")["rules"]
    counters = {}
    for kind, domain in (("chat", "chatgpt.com"), ("api", "openai.com")):
        matches = [r for r in rules if r.get("type") == "DomainSuffix"
                   and r.get("payload") == domain and r.get("proxy") == group
                   and not r.get("extra", {}).get("disabled", False)]
        if not matches:
            raise RuntimeError("No active %s suffix rule targeting %s" % (domain, group))
        counters[kind] = matches[0].get("extra", {}).get("hitCount", 0)
    return counters


def detect_group(core, proxies, requested=None):
    if requested:
        if requested not in proxies or proxies[requested].get("type") != "Selector":
            raise RuntimeError("Requested selector group not found: " + requested)
        return requested
    rules = core.get("/rules")["rules"]
    groups = []
    for domain in ("chatgpt.com", "openai.com"):
        groups.append({r.get("proxy") for r in rules
                       if r.get("type") == "DomainSuffix" and r.get("payload") == domain
                       and not r.get("extra", {}).get("disabled", False)})
    common = groups[0] & groups[1]
    valid = [name for name in common if proxies.get(name, {}).get("type") == "Selector"]
    if not valid:
        raise RuntimeError("OpenAI rules do not share a selectable group; pass --group after inspecting routes")
    return min(valid, key=lambda name: (name.lower() != "openai", name))


def real_probe(port, kind, budget):
    try:
        timeout = budget.limit(3.7)
        args = ["--noproxy", "", "-x", "http://127.0.0.1:%d" % port,
                "--connect-timeout", "3.2", "-I", "-o", os.devnull,
                "-w", "%{http_code} %{time_starttransfer}", TARGETS[kind]]
        result = curl(args, timeout)
        if result.returncode:
            return None
        status, first = result.stdout.split()
        return float(first) if expected_status(kind, int(status)) else None
    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
        return None


def probe_candidate(port, budget):
    result = {kind: [] for kind in TARGETS}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for _ in range(2):
            futures = {kind: pool.submit(real_probe, port, kind, budget) for kind in TARGETS}
            for kind in TARGETS:
                result[kind].append(futures[kind].result())
    return result


def probe_candidate_once(port, budget):
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {kind: pool.submit(real_probe, port, kind, budget) for kind in TARGETS}
        return {kind: futures[kind].result() for kind in TARGETS}


def table_path(system=None, environment=None, home=None):
    system = system or platform.system()
    environment = environment if environment is not None else os.environ
    home = Path(home) if home is not None else Path.home()
    if system == "Windows":
        root = Path(environment.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    else:
        root = Path(environment.get("XDG_CACHE_HOME", str(home / ".cache"))).expanduser()
    return root / "clash-network-optimize" / "nodes.json"


def load_table(path, fingerprint):
    try:
        data = json.loads(path.read_text())
        if data.get("fingerprint") == fingerprint and time.time() - data.get("updated", 0) < CACHE_AGE_SECONDS:
            return data.get("nodes", {})
    except (OSError, ValueError, TypeError):
        pass
    return {}


def save_table(path, fingerprint, nodes):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    payload = json.dumps({"fingerprint": fingerprint, "updated": time.time(), "nodes": nodes}, ensure_ascii=False)
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(payload)
    os.replace(str(temp), str(path))


def restore_if_owned(core, group, original, last_selected):
    try:
        current = core.current(group, restore=True)
    except (RuntimeError, subprocess.TimeoutExpired):
        current = last_selected
    if current not in (original, last_selected):
        print("Selection changed externally; left it untouched:", current, file=sys.stderr)
        return
    for attempt in range(2):
        try:
            core.select(group, original, restore=True)
            return
        except (RuntimeError, subprocess.TimeoutExpired):
            if attempt == 1:
                raise


def system_proxy_enabled():
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            with key:
                enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
                server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).lower()
            return bool(enabled) and ("127.0.0.1" in server or "localhost" in server)
        except (OSError, ValueError):
            return False
    try:
        result = subprocess.run(["scutil", "--proxy"], capture_output=True, text=True, timeout=0.5)
        return "HTTPEnable : 1" in result.stdout and "HTTPProxy : 127.0.0.1" in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="OpenAI selector group; auto-detected from rules by default")
    parser.add_argument("--controller", help="Local mihomo API address, e.g. 127.0.0.1:9090")
    parser.add_argument("--apply", action="store_true", help="Keep best fully verified node")
    args = parser.parse_args()
    budget = Budget()
    curl_name = "curl.exe" if platform.system() == "Windows" else "curl"
    if not shutil.which(curl_name):
        raise RuntimeError(curl_name + " is required")
    core = discover_core(budget, args.controller or os.environ.get("CLASH_CONTROLLER"))
    config = core.get("/configs")
    if config.get("mode") != "rule":
        raise RuntimeError("Expected rule mode; inspect routing first")
    port = config.get("mixed-port")
    if not isinstance(port, int) or port <= 0:
        raise RuntimeError("No active mixed-port")
    if not system_proxy_enabled():
        print("Note: system HTTP proxy is not enabled on loopback; TUN or app routing may differ")
    proxies = core.get("/proxies")["proxies"]
    group = detect_group(core, proxies, args.group)
    before_hits = route_counters(core, group)
    group_data = proxies[group]
    original = group_data["now"]
    names = [n for n in group_data["all"] if n not in ("DIRECT", "REJECT")
             and (proxies.get(n, {}).get("type") != "Selector" or n == original)]
    fingerprint = hashlib.sha256((group + "\0" + "\0".join(sorted(names))).encode()).hexdigest()
    path = table_path()
    table = load_table(path, fingerprint)
    if table:
        ordered = sorted(names, key=lambda n: (
            table.get(n, {}).get("delay") is None,
            table.get(n, {}).get("delay") or 99999,
        ))
        candidates = cached_candidates(ordered, original, table)
        print("Using local node table:", len(table), "records", flush=True)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            delays = list(pool.map(core.delay, names))
        table = {name: {"delay": delay} for name, delay in zip(names, delays)}
        ordered = sorted(names, key=lambda n: (table[n]["delay"] is None,
                                              table[n]["delay"] or 99999))
        candidates = [original] + [n for n in shortlist_candidates(ordered, 2, original) if n != original]
        print("Fresh node scan:", len(names), "options", flush=True)
    print("Candidates:", ", ".join(candidates), flush=True)
    results = {}
    last_selected = original
    try:
        for name in candidates:
            if budget.left() < 4.5:
                print("Budget reached; skipping remaining candidates", flush=True)
                break
            if core.current(group) != last_selected:
                raise RuntimeError("Selection changed externally; stop benchmarking")
            last_selected = name
            core.select(group, name)
            values = probe_candidate(port, budget)
            results[name] = values
            good = all(all(v is not None for v in values[kind]) for kind in TARGETS)
            prior = table.get(name, {})
            failures = prior.get("failures", 0) + (0 if good else 1)
            table[name] = {"delay": prior.get("delay"),
                           "ok": good and failures == 0,
                           "worst": sum(max(values[kind]) for kind in TARGETS) if good else None,
                           "failures": failures,
                           "successes": prior.get("successes", 0) + (1 if good else 0)}
            print(name, "chat", values["chat"], "api", values["api"], flush=True)
            if len(results) == 1:
                after_hits = route_counters(core, group)
                if any(after_hits[k] <= before_hits[k] for k in TARGETS):
                    raise RuntimeError("Real requests did not hit the expected OpenAI rules")
    finally:
        restore_if_owned(core, group, original, last_selected)
    save_table(path, fingerprint, table)
    best = choose_best(results)
    print("Recommended:", best, flush=True)
    if args.apply:
        def final_check():
            if core.current(group, restore=True) != best:
                return False
            if budget.left() > 4.5:
                pair = probe_candidate_once(port, budget)
                return all(value is not None for value in pair.values())
            print("Final request repetition skipped to respect 20-second limit", flush=True)
            return True

        apply_with_rollback(best, original,
                            lambda n: core.select(group, n, restore=True),
                            final_check,
                            lambda: core.current(group, restore=True))
        print("Applied:", best, flush=True)
    print("Elapsed: %.2fs" % (time.monotonic() - budget.start), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
