"""Live check of the bridge against a running Home Assistant (the test HA) and Alpaca simulators.

Not a pytest module (the name does not start with test_): it talks to a real system.

  py -3.14 tests/live_check.py baseline              what is there (entries, entities, log); changes nothing
  py -3.14 tests/live_check.py nina                  scenarios on the camera of the "N.I.N.A. Alpaca Server" entry
  py -3.14 tests/live_check.py create HOST:PORT      creates an entry for an Alpaca server (remembered in
                                                     tests/.live_check_state.json)
  py -3.14 tests/live_check.py entities              lists the entities of that entry
  py -3.14 tests/live_check.py run                   scenarios on the devices of that entry (needs live_scenarios.py)
  py -3.14 tests/live_check.py retry                 reload the entry while you have stopped the server, then
                                                     start it: the entry has to retry and load by itself
  py -3.14 tests/live_check.py delete                deletes the entry this script created

The URL and token of Home Assistant come from deployconf.secrets (HA_URL, HA_TOKEN, not in git; another file
with --secrets) and are never printed. Safety: every call that changes something is checked against the entities of the entries that may be
operated (ALLOWED_TITLES plus the entry this script creates); the entry in DENIED_TITLES (real power outputs) is
refused, whatever the call. The original state of what is changed is restored.
"""
import argparse
import ast
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOMAIN = "ascom_alpaca_bridge"
ALLOWED_TITLES = {"N.I.N.A. Alpaca Server"}
DENIED_TITLES = {"SV241 Alpaca Proxy"}
STATE_FILE = ROOT / "tests" / ".live_check_state.json"  # the entry this script created (not in git)


class Refused(Exception):
    """A call that would touch something that is not allowed."""


def load_secrets(path: pathlib.Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([^#=\s]+)\s*=\s*(.*?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


class Ha:
    def __init__(self, secrets_path: pathlib.Path):
        secrets = load_secrets(secrets_path)
        self.url = secrets["HA_URL"].rstrip("/")
        self._token = secrets["HA_TOKEN"]
        self.allowed: set = set()  # entity ids that may be operated

    # --- plumbing ---------------------------------------------------------------------------------
    def request(self, method, path, body=None, raw=False, timeout=30):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.url + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read()
                status = response.status
        except urllib.error.HTTPError as err:
            payload, status = err.read(), err.code
        if raw:
            return status, payload
        text = payload.decode("utf-8", "replace")
        try:
            return status, json.loads(text)
        except ValueError:
            return status, text

    def template(self, expression):
        status, text = self.request("POST", "/api/template", {"template": expression}, raw=True)
        text = text.decode("utf-8", "replace")
        if status != 200:
            raise RuntimeError(f"template failed: {status} {text[:200]}")
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text

    # --- reading ------------------------------------------------------------------------------------
    def state(self, entity_id):
        status, data = self.request("GET", f"/api/states/{entity_id}")
        return data if status == 200 else None

    def value(self, entity_id):
        state = self.state(entity_id)
        return None if state is None else state["state"]

    def entry_entities(self, title):
        return sorted(self.template("{{ integration_entities('%s') | list }}" % title.replace("'", "")))

    def entries(self):
        status, data = self.request("GET", "/api/config/config_entries/entry")
        return [e for e in data if e["domain"] == DOMAIN]

    def device_entities(self, device_id):
        return self.template("{{ device_entities('%s') | list }}" % device_id)

    def devices_of(self, title):
        """device ids of an entry (via its entities)."""
        ids = {self.template("{{ device_id('%s') }}" % e) for e in self.entry_entities(title)}
        return sorted(i for i in ids if i and i != "None")

    # --- changing, with the guard ------------------------------------------------------------------------
    def allow_title(self, title):
        if title in DENIED_TITLES:
            raise Refused(f"entry {title!r} is on the deny list")
        self.allowed |= set(self.entry_entities(title))

    def _check(self, entity_ids):
        denied = set()
        for title in DENIED_TITLES:
            denied |= set(self.entry_entities(title))
        for entity_id in entity_ids:
            if entity_id in denied or entity_id not in self.allowed:
                raise Refused(f"{entity_id} is not an entity this check may operate")

    def service(self, domain, name, entity_id=None, device_id=None, **data):
        """Call a service on entities / a device of the allowed entries only."""
        entity_ids = [entity_id] if isinstance(entity_id, str) else list(entity_id or [])
        if domain == DOMAIN:
            if not device_id:
                raise Refused("a bridge service needs an explicit device_id")
        if device_id:
            entity_ids += self.device_entities(device_id)
            if not entity_ids:
                raise Refused(f"device {device_id} has no entities")
        if not entity_ids:
            raise Refused("a service call without a target")
        self._check(entity_ids)
        body = dict(data)
        if entity_id:
            body["entity_id"] = entity_id
        if device_id:
            body["device_id"] = device_id
        return self.request("POST", f"/api/services/{domain}/{name}", body)

    def wait(self, predicate, timeout=30, step=1.0):
        end = time.time() + timeout
        while time.time() < end:
            value = predicate()
            if value:
                return value
            time.sleep(step)
        return None

    def log_errors(self, since):
        """Errors and warnings of the bridge in the Home Assistant log since `since` (epoch seconds)."""
        status, text = self.request("GET", "/api/error_log", raw=True)
        if status != 200:
            return None  # not available on this system
        lines = text.decode("utf-8", "replace").splitlines()
        return [l for l in lines if DOMAIN in l and (" ERROR " in l or " WARNING " in l)]


# --- report ------------------------------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.rows = []

    def add(self, area, name, ok, detail=""):
        self.rows.append((area, name, ok, detail))
        print(f"  [{'ok ' if ok else 'FAIL'}] {area}: {name}" + (f"  ({detail})" if detail else ""))

    def finish(self):
        failed = [r for r in self.rows if not r[2]]
        print(f"\n{len(self.rows) - len(failed)} ok, {len(failed)} failed")
        return 1 if failed else 0


def find(entities, domain, *words):
    """The entity of a domain whose id contains all words."""
    for entity_id in entities:
        if entity_id.startswith(domain + ".") and all(w in entity_id for w in words):
            return entity_id
    return None


# --- the test entry ----------------------------------------------------------------------------------------------
def created_entry():
    """(entry_id, title) of the entry this script created, if it still exists."""
    if not STATE_FILE.exists():
        return None
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def create_entry(ha: Ha, hostport: str):
    host, port = hostport.rsplit(":", 1)
    if created_entry():
        raise SystemExit("this script created an entry before and did not delete it: run 'delete' first")
    before = {e["entry_id"] for e in ha.entries()}
    status, flow = ha.request("POST", "/api/config/config_entries/flow", {"handler": DOMAIN, "show_advanced_options": False})
    if status != 200:
        raise SystemExit(f"cannot start the flow: {status} {flow}")
    flow_id = flow["flow_id"]

    def post(data):
        nonlocal flow
        status, flow = ha.request("POST", f"/api/config/config_entries/flow/{flow_id}", data)
        if status != 200:
            raise SystemExit(f"flow step failed: {status} {flow}")

    try:
        if flow.get("step_id") == "user":
            post({"host": "Manual"})
        if flow.get("type") == "form" and flow.get("step_id") == "manual":
            post({"host": host, "port": int(port)})
        if flow.get("type") == "abort":
            raise SystemExit(f"the flow aborted: {flow.get('reason')} (is the server already an entry?)")
        if flow.get("step_id") != "select_devices":
            raise SystemExit(f"unexpected flow step: {flow.get('step_id')} {flow.get('errors')}")
        schema = {f["name"]: f for f in flow["data_schema"]}
        options = schema["devices"].get("options") or []
        keys = [o[0] if isinstance(o, list) else o for o in options]
        post({"devices": keys})
    except BaseException:
        ha.request("DELETE", f"/api/config/config_entries/flow/{flow_id}")
        raise
    if flow.get("type") != "create_entry":
        raise SystemExit(f"entry not created: {flow}")
    new = [e for e in ha.entries() if e["entry_id"] not in before]
    if len(new) != 1:
        raise SystemExit(f"expected one new entry, found {len(new)}")
    STATE_FILE.write_text(
        json.dumps({"entry_id": new[0]["entry_id"], "title": new[0]["title"], "server": hostport}), encoding="utf-8"
    )
    print(f"created entry {new[0]['title']!r} ({new[0]['entry_id'][:8]}), state {new[0]['state']}")
    return new[0]


def delete_entry(ha: Ha):
    state = created_entry()
    if not state:
        print("no entry created by this script")
        return
    status, data = ha.request("DELETE", f"/api/config/config_entries/entry/{state['entry_id']}")
    print(f"deleted entry {state['title']!r}: HTTP {status}")
    if status == 200:
        STATE_FILE.unlink()


def server_reachable(server: str) -> bool:
    try:
        with urllib.request.urlopen(f"http://{server}/management/apiversions", timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def entry_state(ha: Ha, entry_id: str):
    for entry in ha.entries():
        if entry["entry_id"] == entry_id:
            return entry["state"]
    return None


def wait_for(predicate, timeout, step=2.0):
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return None


def run_retry(ha: Ha, server: str = None):
    """The entry of `create` is reloaded while the server is down (you stop it) and has to retry and load by
    itself when the server is back (you start it again). Prints what to do; waits up to 10 minutes per step."""
    state = created_entry()
    if not state:
        print("create the entry first: live_check.py create HOST:PORT")
        return 1
    server = server or state.get("server")
    entry_id, title = state["entry_id"], state["title"]
    ha.allow_title(title)
    report = Report()
    before = ha.entry_entities(title)
    print(f"entry {title!r} loaded with {len(before)} entities; server {server}", flush=True)

    print(">>> STOP the Alpaca server now (waiting up to 10 minutes) ...", flush=True)
    down = wait_for(lambda: not server_reachable(server), 600)
    report.add("retry", "server is down", bool(down))
    if not down:
        return report.finish()

    status, _ = ha.request("POST", f"/api/config/config_entries/entry/{entry_id}/reload")
    retrying = wait_for(lambda: entry_state(ha, entry_id) == "setup_retry", 90, 2)
    report.add("retry", "reload without a server gives setup_retry", bool(retrying), f"state {entry_state(ha, entry_id)}")

    print(">>> START the Alpaca server again (waiting up to 10 minutes) ...", flush=True)
    up = wait_for(lambda: server_reachable(server), 600)
    report.add("retry", "server is back", bool(up))
    if not up:
        return report.finish()
    came_back = time.time()
    loaded = wait_for(lambda: entry_state(ha, entry_id) == "loaded", 600, 5)
    report.add("retry", "the entry loads by itself", bool(loaded), f"after {time.time() - came_back:.0f} s")
    time.sleep(15)
    after = ha.entry_entities(title)
    report.add("retry", "all entities are there again", after == before, f"{len(before)} -> {len(after)}")
    values = [ha.value(e) for e in after]
    unavailable = [e for e, v in zip(after, values) if v == "unavailable"]
    report.add("retry", "no entity unavailable (except the tracking rate select)", len(unavailable) <= 1, str(unavailable[:3]))
    return report.finish()


# --- scenarios -----------------------------------------------------------------------------------------------
def baseline(ha: Ha):
    print("Entries of the bridge:")
    for entry in ha.entries():
        entities = ha.entry_entities(entry["title"])
        states = [ha.value(e) for e in entities]
        bad = sum(1 for s in states if s in ("unavailable", "unknown"))
        print(f"  {entry['title']!r}: {entry['state']}, {len(entities)} entities, {bad} unavailable/unknown")
    errors = ha.log_errors(0)
    print("Log lines of the bridge with ERROR / WARNING:", "n/a" if errors is None else len(errors))
    for line in (errors or [])[:10]:
        print("   ", line[:200])
    return 0


def camera_scenarios(ha: Ha, title: str, report: Report):
    entities = ha.entry_entities(title)
    camera = find(entities, "camera")
    if not camera:
        report.add("camera", "camera entity present", False)
        return
    exposure = find(entities, "number", "target_exposure")
    start = find(entities, "button", "start_exposure")
    light = find(entities, "switch", "light_frame")
    state = find(entities, "sensor", "camera_state")
    ready = find(entities, "binary_sensor", "image_ready")
    report.add("camera", "entities found", all([exposure, start, light, state, ready]), f"{exposure} {start} {light}")
    if not all([exposure, start, light, state, ready]):
        return

    original_exposure = ha.value(exposure)
    original_light = ha.value(light)
    try:
        # A2: a value that was entered survives the polls
        ha.service("number", "set_value", entity_id=exposure, value=1.5)
        time.sleep(13)  # more than two polls at the default interval
        report.add("camera", "target exposure survives the polls", float(ha.value(exposure) or 0) == 1.5, ha.value(exposure))

        # A1: every exposure gives a new picture
        images = []
        for _ in range(2):
            ha.service("button", "press", entity_id=start)
            started = ha.wait(lambda: ha.value(state) in ("Exposing", "Reading", "Download", "Idle"), 10, 0.5)
            done = ha.wait(lambda: ha.value(state) == "Idle" and ha.value(ready) == "on", 30, 1.0)
            status, image = ha.request("GET", f"/api/camera_proxy/{camera}", raw=True)
            images.append(image if status == 200 else b"")
            report.add("camera", "exposure finishes", bool(started and done))
        # (that a new exposure gives a new picture is checked against the simulator in live_scenarios.py: a
        # simulator may make the same picture twice)
        report.add(
            "camera", "the camera entity delivers JPEG pictures",
            len(images) == 2 and all(i[:2] == b"\xff\xd8" for i in images),
            f"{[len(i) for i in images]} bytes",
        )

        # dark frame: the start button still works with the switch off
        ha.service("switch", "turn_off", entity_id=light)
        ha.service("button", "press", entity_id=start)
        done = ha.wait(lambda: ha.value(state) == "Idle" and ha.value(ready) == "on", 30, 1.0)
        report.add("camera", "dark frame exposure finishes", bool(done))
    finally:
        ha.service("number", "set_value", entity_id=exposure, value=float(original_exposure or 1.0))
        ha.service("switch", f"turn_{'on' if original_light == 'on' else 'off'}", entity_id=light)


def run_scenarios_nina(ha: Ha):
    report = Report()
    ha.allow_title("N.I.N.A. Alpaca Server")
    started = time.time()
    print("Scenarios on the camera of 'N.I.N.A. Alpaca Server':")
    camera_scenarios(ha, "N.I.N.A. Alpaca Server", report)
    errors = ha.log_errors(started)
    if errors is not None:
        report.add("log", "no errors or warnings of the bridge during the run", not errors, f"{len(errors)} line(s)")
    return report.finish()


def run_simulators(ha: Ha, server: str = None):
    from live_scenarios import run_all  # needs Ha, Report and camera_scenarios of this module

    state = created_entry()
    if not state:
        print("create the entry first: live_check.py create HOST:PORT")
        return 1
    title = state["title"]
    server = server or state.get("server")
    ha.allow_title(title)
    entities = ha.entry_entities(title)
    report = Report()
    started = time.time()
    print(f"Scenarios on {title!r} ({len(entities)} entities):")
    run_all(ha, title, entities, report, server)
    errors = ha.log_errors(started)
    if errors is not None:
        report.add("log", "no errors or warnings of the bridge during the run", not errors, f"{len(errors)} line(s)")
    return report.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=["baseline", "nina", "create", "entities", "run", "retry", "delete"])
    parser.add_argument("server", nargs="?", help="HOST:PORT of the Alpaca server (simulators)")
    parser.add_argument(
        "--secrets", type=pathlib.Path, default=ROOT / "deployconf.secrets",
        help="file with HA_URL and HA_TOKEN (default: deployconf.secrets of this repository)",
    )
    args = parser.parse_args()
    ha = Ha(args.secrets)
    if args.what == "baseline":
        return baseline(ha)
    if args.what == "nina":
        return run_scenarios_nina(ha)
    if args.what == "run":
        return run_simulators(ha, args.server)
    if args.what == "retry":
        return run_retry(ha, args.server)
    if args.what == "create":
        create_entry(ha, args.server)
        return 0
    if args.what == "delete":
        delete_entry(ha)
        return 0
    if args.what == "entities":
        state = created_entry()
        if not state:
            print("no entry created by this script")
            return 1
        for entity_id in ha.entry_entities(state["title"]):
            print(f"{entity_id} = {ha.value(entity_id)}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
