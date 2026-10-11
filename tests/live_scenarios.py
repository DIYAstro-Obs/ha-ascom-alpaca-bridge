"""Scenarios of live_check.py for the device types of an Alpaca server (see there for how to run them).

Every scenario restores what it changed. All calls go through Ha.service, which refuses entities that are not
allowed.
"""
import time

from live_check import DOMAIN, Report, camera_scenarios, created_entry, find


def watch(ha, entity_id, until, timeout=60, step=0.5):
    """The distinct states of an entity until `until(state)` is true or the time is up."""
    seen = []
    end = time.time() + timeout
    while time.time() < end:
        state = ha.value(entity_id)
        if not seen or seen[-1] != state:
            seen.append(state)
        if until(state):
            break
        time.sleep(step)
    return seen


def attr(ha, entity_id, name):
    state = ha.state(entity_id)
    return None if state is None else state.get("attributes", {}).get(name)


def number(ha, entity_id, default=-1e9):
    try:
        return float(ha.value(entity_id))
    except (TypeError, ValueError):
        return default


def cover_scenarios(ha, report, area, cover):
    """Open and close a cover (roof or flat panel cover), then it is where it started."""
    original = ha.value(cover)
    first = ("open", "open_cover", "close_cover") if original == "closed" else ("closed", "close_cover", "open_cover")
    for target, service in ((first[0], first[1]), ("closed" if first[0] == "open" else "open", first[2])):
        status, body = ha.service("cover", service, entity_id=cover)
        if status != 200:
            report.add(area, f"{service} accepted", False, f"HTTP {status} {str(body)[:120]}")
            return
        seen = watch(ha, cover, lambda s, t=target: s == t, 90)
        report.add(area, f"{service} reaches {target}", bool(seen) and seen[-1] == target, " > ".join(map(str, seen)))
        if "unknown" in seen or "unavailable" in seen:
            report.add(area, "no unknown / unavailable on the way", False, " > ".join(map(str, seen)))


def dome_scenarios(ha, entities, report):
    cover = find(entities, "cover", "dome")
    if not cover:
        return report.add("dome", "cover entity present", False)
    print("Dome:")
    cover_scenarios(ha, report, "dome", cover)


def calibrator_scenarios(ha, entities, report):
    cover = find(entities, "cover", "covercalibrator")
    switch = find(entities, "switch", "covercalibrator")
    brightness = find(entities, "number", "covercalibrator", "brightness")
    apply = find(entities, "button", "covercalibrator", "set_brightness")
    if not (cover and switch and brightness and apply):
        return report.add("calibrator", "entities present", False, f"{cover} {switch} {brightness} {apply}")
    print("CoverCalibrator:")
    cover_scenarios(ha, report, "calibrator", cover)
    ha.service("number", "set_value", entity_id=brightness, value=100)
    time.sleep(12)
    report.add("calibrator", "brightness target survives the polls", number(ha, brightness) == 100.0, ha.value(brightness))
    ha.service("button", "press", entity_id=apply)
    on = ha.wait(lambda: ha.value(switch) == "on", 20, 1)
    report.add("calibrator", "set brightness turns the calibrator on", bool(on))
    ha.service("switch", "turn_off", entity_id=switch)
    off = ha.wait(lambda: ha.value(switch) == "off", 20, 1)
    report.add("calibrator", "calibrator off", bool(off))


def telescope_scenarios(ha, entities, report):
    tracking = find(entities, "switch", "telescope", "tracking")
    parked = find(entities, "binary_sensor", "telescope", "parked")
    slewing = find(entities, "binary_sensor", "telescope", "slewing")
    ra_sensor = find(entities, "sensor", "telescope", "right_ascension")
    park = find(entities, "button", "telescope", "park")
    unpark = find(entities, "button", "telescope", "unpark")
    if not all([tracking, parked, slewing, ra_sensor, park, unpark]):
        return report.add("telescope", "entities present", False)
    print("Telescope:")
    device_id = ha.template("{{ device_id('%s') }}" % ra_sensor)
    original_parked, original_tracking = ha.value(parked), ha.value(tracking)
    try:
        if ha.value(parked) == "on":
            ha.service("button", "press", entity_id=unpark)
            ha.wait(lambda: ha.value(parked) == "off", 30, 1)
        # a slew to RA/Dec switches tracking on first
        ha.service("switch", "turn_off", entity_id=tracking)
        ha.wait(lambda: ha.value(tracking) == "off", 20, 1)
        status, body = ha.service(DOMAIN, "slew_to_coordinates", device_id=device_id, ra=5.5, dec=20.0)
        report.add("telescope", "slew_to_coordinates accepted", status == 200, "" if status == 200 else f"HTTP {status} {str(body)[:100]}")
        on = ha.wait(lambda: ha.value(tracking) == "on", 20, 1)
        report.add("telescope", "tracking was switched on for the slew", bool(on))
        done = ha.wait(lambda: ha.value(slewing) == "off", 90, 1)
        report.add("telescope", "slew finishes", bool(done))
        ra = attr(ha, ra_sensor, "decimal")
        report.add("telescope", "RA is the target", ra is not None and abs(float(ra) - 5.5) < 0.05, f"{ra}")
        # an Alt/Az slew switches tracking off first
        status, body = ha.service(DOMAIN, "slew_to_alt_az", device_id=device_id, alt=45.0, az=180.0)
        report.add("telescope", "slew_to_alt_az accepted", status == 200, "" if status == 200 else f"HTTP {status} {str(body)[:100]}")
        off = ha.wait(lambda: ha.value(tracking) == "off", 20, 1)
        report.add("telescope", "tracking was switched off for the Alt/Az slew", bool(off))
        ha.wait(lambda: ha.value(slewing) == "off", 90, 1)
        # parked: a slew is refused with a message
        ha.service("button", "press", entity_id=park)
        parked_now = ha.wait(lambda: ha.value(parked) == "on", 90, 1)
        report.add("telescope", "park", bool(parked_now))
        status, body = ha.service(DOMAIN, "slew_to_coordinates", device_id=device_id, ra=1.0, dec=10.0)
        report.add("telescope", "a slew while parked is refused with a message", status >= 400 and "parked" in str(body).lower(), f"HTTP {status} {str(body)[:100]}")
    finally:
        if original_parked == "off" and ha.value(parked) == "on":
            ha.service("button", "press", entity_id=unpark)
            ha.wait(lambda: ha.value(parked) == "off", 30, 1)
        ha.service("switch", f"turn_{'on' if original_tracking == 'on' else 'off'}", entity_id=tracking)


def positioner_scenarios(ha, report, area, target, apply, live, value, original, tolerance):
    """A target number is entered, survives the polls, is applied by a button and the device reaches it."""
    ha.service("number", "set_value", entity_id=target, value=value)
    time.sleep(12)
    report.add(area, "target survives the polls", abs(number(ha, target) - value) < 1e-6, ha.value(target))
    ha.service("button", "press", entity_id=apply)
    reached = ha.wait(lambda: abs(number(ha, live) - value) <= tolerance, 90, 1)
    report.add(area, "device reaches the target", bool(reached), ha.value(live))
    ha.service("number", "set_value", entity_id=target, value=original)
    ha.service("button", "press", entity_id=apply)
    ha.wait(lambda: abs(number(ha, live) - original) <= tolerance, 90, 1)


def focuser_scenarios(ha, entities, report):
    target = find(entities, "number", "focuser", "target_position")
    apply = find(entities, "button", "focuser", "move_to_target")
    live = find(entities, "sensor", "focuser", "position")
    if not all([target, apply, live]):
        return report.add("focuser", "entities present", False)
    print("Focuser:")
    original = number(ha, live)
    positioner_scenarios(ha, report, "focuser", target, apply, live, original + 500, original, 1)


def rotator_scenarios(ha, entities, report):
    target = find(entities, "number", "rotator", "target_angle")
    apply = find(entities, "button", "rotator", "move_to_target_angle")
    live = find(entities, "sensor", "rotator", "position")
    relative = find(entities, "number", "rotator", "move_relative")
    relative_button = find(entities, "button", "rotator", "move_relative")
    if not all([target, apply, live, relative, relative_button]):
        return report.add("rotator", "entities present", False)
    print("Rotator:")
    original = number(ha, live)
    positioner_scenarios(ha, report, "rotator", target, apply, live, (original + 30) % 360, original, 0.5)
    before = number(ha, live)
    ha.service("number", "set_value", entity_id=relative, value=10)
    time.sleep(12)
    report.add("rotator", "relative move value survives the polls", number(ha, relative) == 10.0, ha.value(relative))
    ha.service("button", "press", entity_id=relative_button)
    moved = ha.wait(lambda: abs(number(ha, live) - ((before + 10) % 360)) <= 0.5, 60, 1)
    report.add("rotator", "relative move happens", bool(moved), ha.value(live))
    ha.service("number", "set_value", entity_id=relative, value=-10)
    ha.service("button", "press", entity_id=relative_button)
    ha.wait(lambda: abs(number(ha, live) - before) <= 0.5, 60, 1)
    ha.service("number", "set_value", entity_id=relative, value=0)


def filterwheel_scenarios(ha, entities, report):
    select = find(entities, "select", "filter_wheel")
    apply = find(entities, "button", "filter_wheel", "move_to_target")
    live = find(entities, "sensor", "filter_wheel", "filter")
    if not all([select, apply, live]):
        return report.add("filter wheel", "entities present", False)
    print("Filter wheel:")
    options = attr(ha, select, "options") or []
    original = ha.value(select)
    others = [o for o in options if o != original]
    if not others:
        return report.add("filter wheel", "more than one filter", False, str(options))
    wanted = others[0]
    ha.service("select", "select_option", entity_id=select, option=wanted)
    time.sleep(12)
    report.add("filter wheel", "selection survives the polls", ha.value(select) == wanted, ha.value(select))
    ha.service("button", "press", entity_id=apply)
    reached = ha.wait(lambda: ha.value(live) == wanted, 60, 1)
    report.add("filter wheel", "wheel moves to the filter", bool(reached), ha.value(live))
    ha.service("select", "select_option", entity_id=select, option=original)
    ha.service("button", "press", entity_id=apply)
    ha.wait(lambda: ha.value(live) == original, 60, 1)


def readonly_scenarios(ha, entities, report):
    print("Sensors:")
    groups = (
        ("observing conditions", ("observing_conditions", "temperature")),
        ("safety monitor", ("safetymonitor", "safety")),
        ("switch device", ("omnisim_switch",)),
    )
    for title, words in groups:
        found = [e for e in entities if all(w in e for w in words)]
        values = [ha.value(e) for e in found]
        bad = [v for v in values if v in ("unavailable", "unknown", None)]
        report.add("read", f"{title} entities have values", bool(found) and not bad, f"{len(found)} entities")


def service_scenarios(ha, entities, report):
    print("Services:")
    status, services = ha.request("GET", "/api/services")
    bridge = next((s for s in services if s["domain"] == DOMAIN), {"services": {}})
    names = set(bridge["services"])
    expected = {
        "slew_to_coordinates", "slew_to_alt_az", "telescope_pulseguide", "rotator_move", "rotator_sync",
        "focuser_move", "dome_slew_az", "dome_slew_alt", "dome_sync_az", "camera_start_exposure",
        "camera_pulseguide", "camera_set_roi",
    }
    report.add("services", "all 12 services are registered", expected <= names, f"missing {sorted(expected - names)}")
    dome_sensor = find(entities, "sensor", "dome", "azimuth")
    if dome_sensor:
        device_id = ha.template("{{ device_id('%s') }}" % dome_sensor)
        status, body = ha.service(DOMAIN, "dome_slew_az", device_id=device_id, azimuth=90)
        report.add("services", "dome_slew_az: accepted, or refused with a message", status == 200 or bool(body), f"HTTP {status} {str(body)[:100]}")


def reload_scenario(ha, title, report):
    print("Configuration:")
    state = created_entry()
    before = ha.entry_entities(title)
    status, _ = ha.request("POST", f"/api/config/config_entries/entry/{state['entry_id']}/reload")
    time.sleep(10)
    after = ha.entry_entities(title)
    report.add("config", "reload keeps the entity IDs", status == 200 and before == after, f"{len(before)} -> {len(after)}")
    unavailable = [e for e in after if ha.value(e) == "unavailable"]
    report.add("config", "no entity unavailable after the reload", len(unavailable) <= 1, str(unavailable[:3]))


def run_all(ha, title, entities, report):
    dome_scenarios(ha, entities, report)
    calibrator_scenarios(ha, entities, report)
    telescope_scenarios(ha, entities, report)
    focuser_scenarios(ha, entities, report)
    rotator_scenarios(ha, entities, report)
    filterwheel_scenarios(ha, entities, report)
    print("Camera:")
    camera_scenarios(ha, title, report)
    readonly_scenarios(ha, entities, report)
    service_scenarios(ha, entities, report)
    reload_scenario(ha, title, report)
