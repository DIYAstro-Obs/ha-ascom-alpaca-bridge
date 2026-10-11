"""Scenarios of live_check.py for the controls that live_scenarios.py does not operate: the buttons, target numbers,
selects, switches and services of the telescope, dome, focuser, rotator and camera, each verified at the device.

Same rules: everything goes through Ha.service (guard), what is changed is put back.
"""
import time

from live_check import DOMAIN
from live_scenarios import attr, find, find_position, number


def decimal(ha, sensor):
    value = attr(ha, sensor, "decimal")
    return None if value is None else float(value)


def near(a, b, tolerance):
    return a is not None and abs(a - b) <= tolerance


def settle(ha, entity, state="off", timeout=90):
    return ha.wait(lambda: ha.value(entity) == state, timeout, 1)


def device_id_of(ha, entity):
    return ha.template("{{ device_id('%s') }}" % entity)


# --- telescope -----------------------------------------------------------------------------------------------------
def telescope_controls(ha, entities, report):
    f = lambda domain, *words: find(entities, domain, "telescope", *words)  # noqa: E731
    tracking, parked = f("switch", "tracking"), f("binary_sensor", "parked")
    slewing, athome = f("binary_sensor", "slewing"), f("binary_sensor", "at_home")
    ra_sensor, dec_sensor = f("sensor", "right_ascension"), f("sensor", "declination")
    alt_sensor, az_sensor = f("sensor", "altitude"), f("sensor", "azimuth")
    park, unpark, find_home, abort = f("button", "park"), f("button", "unpark"), f("button", "find_home"), f("button", "abort_slew")
    t_ra, t_dec, t_alt, t_az = f("number", "target_ra"), f("number", "target_dec"), f("number", "target_alt"), f("number", "target_az")
    slew_radec, slew_altaz = f("button", "slew_to_ra_dec"), f("button", "slew_to_alt_az")
    rate_select, apply_settings = f("select", "tracking_rate"), f("button", "apply_telescope_settings")
    refraction, elevation = f("switch", "does_refraction"), f("number", "site_elevation")
    needed = [tracking, parked, slewing, ra_sensor, dec_sensor, alt_sensor, az_sensor, park, unpark, abort,
              t_ra, t_dec, t_alt, t_az, slew_radec, slew_altaz]
    if not all(needed):
        return report.add("telescope controls", "entities present", False)
    print("Telescope controls:")
    device_id = device_id_of(ha, ra_sensor)
    original_parked, original_tracking = ha.value(parked), ha.value(tracking)
    try:
        if ha.value(parked) == "on":
            ha.service("button", "press", entity_id=unpark)
            settle(ha, parked)
        ha.service("switch", "turn_on", entity_id=tracking)
        settle(ha, tracking, "on", 20)

        # targets are entered, survive the polls, the button slews
        ha.service("number", "set_value", entity_id=t_ra, value=7.0)
        ha.service("number", "set_value", entity_id=t_dec, value=15.0)
        time.sleep(12)
        report.add("telescope controls", "RA/Dec targets survive the polls", number(ha, t_ra) == 7.0 and number(ha, t_dec) == 15.0, f"{ha.value(t_ra)} / {ha.value(t_dec)}")
        ha.service("button", "press", entity_id=slew_radec)
        time.sleep(3)
        settle(ha, slewing)
        ra, dec = decimal(ha, ra_sensor), decimal(ha, dec_sensor)
        report.add("telescope controls", "button 'Slew to RA/Dec' reaches the target", near(ra, 7.0, 0.05) and near(dec, 15.0, 0.5), f"RA {ra}, Dec {dec}")

        ha.service("number", "set_value", entity_id=t_alt, value=50.0)
        ha.service("number", "set_value", entity_id=t_az, value=200.0)
        time.sleep(12)
        report.add("telescope controls", "Alt/Az targets survive the polls", number(ha, t_alt) == 50.0 and number(ha, t_az) == 200.0, f"{ha.value(t_alt)} / {ha.value(t_az)}")
        ha.service("button", "press", entity_id=slew_altaz)
        time.sleep(3)
        settle(ha, slewing)
        alt, az = decimal(ha, alt_sensor), decimal(ha, az_sensor)
        report.add("telescope controls", "button 'Slew to Alt/Az' reaches the target", near(alt, 50.0, 0.5) and near(az, 200.0, 0.5), f"alt {alt}, az {az}")
        report.add("telescope controls", "tracking is off after the Alt/Az slew", ha.value(tracking) == "off", ha.value(tracking))

        # abort a long slew
        ha.service("switch", "turn_on", entity_id=tracking)
        settle(ha, tracking, "on", 20)
        start_ra = decimal(ha, ra_sensor)
        target = (start_ra + 8.0) % 24
        ha.service("number", "set_value", entity_id=t_ra, value=round(target, 3))
        ha.service("number", "set_value", entity_id=t_dec, value=-30.0)
        ha.service("button", "press", entity_id=slew_radec)
        time.sleep(1.5)
        was_slewing = ha.value(slewing) == "on"
        ha.service("button", "press", entity_id=abort)
        stopped = settle(ha, slewing, "off", 30)
        ra_now = decimal(ha, ra_sensor)
        report.add(
            "telescope controls", "abort stops the slew before the target",
            bool(stopped) and (not was_slewing or not near(ra_now, target, 0.05)),
            f"was slewing {was_slewing}, RA {ra_now} of target {target:.3f}",
        )

        # pulse guide through the service
        status, body = ha.service(DOMAIN, "telescope_pulseguide", device_id=device_id, direction=0, duration=500)
        report.add("telescope controls", "telescope_pulseguide is accepted", status == 200, f"HTTP {status} {str(body)[:80] if status != 200 else ''}")

        # tracking rate and settings go together through 'Apply Telescope Settings'
        if rate_select and apply_settings:
            ha.service("switch", "turn_on", entity_id=tracking)
            settle(ha, tracking, "on", 20)
            original_rate = ha.value(rate_select)
            wanted = "Lunar" if original_rate != "Lunar" else "Sidereal"
            ha.service("select", "select_option", entity_id=rate_select, option=wanted)
            time.sleep(12)
            report.add("telescope controls", "tracking rate selection survives the polls", ha.value(rate_select) == wanted, ha.value(rate_select))
            ha.service("button", "press", entity_id=apply_settings)
            applied = ha.wait(lambda: ha.value(rate_select) == wanted, 20, 1)
            report.add("telescope controls", "tracking rate applied", bool(applied), ha.value(rate_select))
            ha.service("select", "select_option", entity_id=rate_select, option=original_rate)
            ha.service("button", "press", entity_id=apply_settings)
            ha.wait(lambda: ha.value(rate_select) == original_rate, 20, 1)
        if refraction:
            original = ha.value(refraction)
            flipped = "off" if original == "on" else "on"
            ha.service("switch", f"turn_{flipped}", entity_id=refraction)
            changed = ha.wait(lambda: ha.value(refraction) == flipped, 20, 1)
            report.add("telescope controls", "'Does Refraction' switches", bool(changed))
            ha.service("switch", f"turn_{original}", entity_id=refraction)
            ha.wait(lambda: ha.value(refraction) == original, 20, 1)
        if elevation and apply_settings:
            original = number(ha, elevation)
            ha.service("number", "set_value", entity_id=elevation, value=original + 5)
            ha.service("button", "press", entity_id=apply_settings)
            changed = ha.wait(lambda: abs(number(ha, elevation) - (original + 5)) < 0.01, 20, 1)
            report.add("telescope controls", "site elevation applied by the settings button", bool(changed), ha.value(elevation))
            ha.service("number", "set_value", entity_id=elevation, value=original)
            ha.service("button", "press", entity_id=apply_settings)
            ha.wait(lambda: abs(number(ha, elevation) - original) < 0.01, 20, 1)

        # find home
        if find_home and athome:
            ha.service("button", "press", entity_id=find_home)
            home = ha.wait(lambda: ha.value(athome) == "on", 120, 1)
            report.add("telescope controls", "'Find Home' reaches home", bool(home), ha.value(athome))
    finally:
        if ha.value(parked) == "on" and original_parked == "off":
            ha.service("button", "press", entity_id=unpark)
            settle(ha, parked, "off", 30)
        if original_parked == "on" and ha.value(parked) == "off":
            ha.service("button", "press", entity_id=park)
            settle(ha, parked, "on", 120)
        ha.service("switch", f"turn_{'on' if original_tracking == 'on' else 'off'}", entity_id=tracking)


# --- dome ------------------------------------------------------------------------------------------------------
def dome_controls(ha, entities, report):
    f = lambda domain, *words: find(entities, domain, "dome", *words)  # noqa: E731
    az_sensor, alt_sensor = f("sensor", "azimuth"), f("sensor", "altitude")
    t_az, t_alt = f("number", "target_azimuth"), f("number", "target_altitude")
    slew_az, slew_alt = f("button", "slew_target_azimuth"), f("button", "slew_target_altitude")
    park, find_home, cover = f("button", "park"), f("button", "find_home"), f("cover")
    parked, moving = f("binary_sensor", "parked"), f("binary_sensor", "moving")
    if not all([az_sensor, t_az, slew_az, park, parked, cover]):
        return report.add("dome controls", "entities present", False)
    print("Dome controls:")
    device_id = device_id_of(ha, az_sensor)
    original_az = number(ha, az_sensor)
    original_alt = number(ha, alt_sensor) if alt_sensor else None
    original_parked = ha.value(parked)
    original_cover = ha.value(cover)
    try:
        target = (original_az + 40) % 360
        ha.service("number", "set_value", entity_id=t_az, value=target)
        time.sleep(12)
        report.add("dome controls", "azimuth target survives the polls", abs(number(ha, t_az) - target) < 0.01, ha.value(t_az))
        ha.service("button", "press", entity_id=slew_az)
        reached = ha.wait(lambda: abs(number(ha, az_sensor) - target) <= 1.5, 90, 1)
        report.add("dome controls", "button 'Slew Target Azimuth' reaches the azimuth", bool(reached), ha.value(az_sensor))

        # the services
        status, body = ha.service(DOMAIN, "dome_slew_az", device_id=device_id, azimuth=270.0)
        reached = ha.wait(lambda: abs(number(ha, az_sensor) - 270.0) <= 1.5, 90, 1)
        report.add("dome controls", "dome_slew_az reaches the azimuth", status == 200 and bool(reached), f"HTTP {status}, az {ha.value(az_sensor)}")
        status, body = ha.service(DOMAIN, "dome_sync_az", device_id=device_id, azimuth=100.0)
        synced = ha.wait(lambda: abs(number(ha, az_sensor) - 100.0) <= 1.5, 30, 1)
        report.add("dome controls", "dome_sync_az sets the reported azimuth", status == 200 and bool(synced), f"HTTP {status}, az {ha.value(az_sensor)}")
        if t_alt and slew_alt and alt_sensor:
            status, body = ha.service(DOMAIN, "dome_slew_alt", device_id=device_id, altitude=30.0)
            reached = ha.wait(lambda: abs(number(ha, alt_sensor) - 30.0) <= 1.5, 90, 1)
            report.add("dome controls", "dome_slew_alt reaches the altitude", status == 200 and bool(reached), f"HTTP {status}, alt {ha.value(alt_sensor)}")

        # stop the shutter while it moves
        if original_cover == "closed":
            ha.service("cover", "open_cover", entity_id=cover)
            seen = ha.wait(lambda: ha.value(cover) == "opening", 20, 0.5)
            ha.service("cover", "stop_cover", entity_id=cover)
            time.sleep(8)
            report.add("dome controls", "stop while the shutter opens (observed, not asserted)", True, f"opening seen {bool(seen)}, state after stop {ha.value(cover)}")
            ha.service("cover", "close_cover", entity_id=cover)
            ha.wait(lambda: ha.value(cover) == "closed", 90, 1)

        # find home, park
        if find_home:
            ha.service("button", "press", entity_id=find_home)
            home = ha.wait(lambda: ha.value(f("binary_sensor", "at_home")) == "on", 120, 1)
            report.add("dome controls", "'Find Home' reaches home", bool(home))
    finally:
        # back to the azimuth and altitude it had (a parked dome is parked again afterwards)
        ha.service(DOMAIN, "dome_slew_az", device_id=device_id, azimuth=original_az)
        ha.wait(lambda: abs(number(ha, az_sensor) - original_az) <= 1.5, 90, 1)
        if original_alt is not None:
            ha.service(DOMAIN, "dome_slew_alt", device_id=device_id, altitude=original_alt)
            ha.wait(lambda: abs(number(ha, alt_sensor) - original_alt) <= 1.5, 90, 1)
        if original_parked == "on":
            ha.service("button", "press", entity_id=park)
            settle(ha, parked, "on", 120)
        report.add("dome controls", "park button / back where it was", ha.value(parked) == original_parked, ha.value(parked))


# --- focuser -----------------------------------------------------------------------------------------------------
def focuser_controls(ha, entities, report):
    f = lambda domain, *words: find(entities, domain, "focuser", *words)  # noqa: E731
    live, target, move, halt = find_position(entities, "focuser"), f("number", "target_position"), f("button", "move_to_target"), f("button", "halt")
    moving, temp_comp = f("binary_sensor", "moving"), f("switch", "temp_comp")
    if not all([live, target, move, halt, moving]):
        return report.add("focuser controls", "entities present", False)
    print("Focuser controls:")
    device_id = device_id_of(ha, live)
    original = number(ha, live)
    try:
        status, body = ha.service(DOMAIN, "focuser_move", device_id=device_id, position=int(original) + 300)
        reached = ha.wait(lambda: abs(number(ha, live) - (original + 300)) <= 1, 60, 1)
        report.add("focuser controls", "focuser_move reaches the position", status == 200 and bool(reached), f"HTTP {status}, {ha.value(live)}")
        ha.service("number", "set_value", entity_id=target, value=original + 6000)
        ha.service("button", "press", entity_id=move)
        time.sleep(1.5)
        was_moving = ha.value(moving) == "on"
        ha.service("button", "press", entity_id=halt)
        stopped = settle(ha, moving, "off", 30)
        position = number(ha, live)
        report.add(
            "focuser controls", "halt stops the move before the target",
            bool(stopped) and (not was_moving or position < original + 6000 - 1),
            f"was moving {was_moving}, position {position} of {original + 6000}",
        )
        if temp_comp:
            before = ha.value(temp_comp)
            flipped = "off" if before == "on" else "on"
            ha.service("switch", f"turn_{flipped}", entity_id=temp_comp)
            changed = ha.wait(lambda: ha.value(temp_comp) == flipped, 20, 1)
            report.add("focuser controls", "temperature compensation switches", bool(changed))
            ha.service("switch", f"turn_{before}", entity_id=temp_comp)
            ha.wait(lambda: ha.value(temp_comp) == before, 20, 1)
    finally:
        ha.service(DOMAIN, "focuser_move", device_id=device_id, position=int(original))
        ha.wait(lambda: abs(number(ha, live) - original) <= 1, 90, 1)


# --- rotator ----------------------------------------------------------------------------------------------------
def rotator_controls(ha, entities, report):
    f = lambda domain, *words: find(entities, domain, "rotator", *words)  # noqa: E731
    live, halt, moving = find_position(entities, "rotator"), f("button", "halt"), f("binary_sensor", "is_moving")
    mechanical = f("sensor", "mechanical_position")
    sync_value, sync_button = f("number", "sync_position"), f("button", "sync")
    absolute, move_abs = f("number", "target_angle"), f("button", "move_to_target_angle")
    reverse = f("switch", "reverse")
    if not all([live, halt, moving, sync_value, sync_button, absolute, move_abs]):
        return report.add("rotator controls", "entities present", False)
    print("Rotator controls:")
    device_id = device_id_of(ha, live)
    original = number(ha, live)
    original_mechanical = number(ha, mechanical)
    try:
        status, body = ha.service(DOMAIN, "rotator_move", device_id=device_id, position=5.0)
        reached = ha.wait(lambda: abs(number(ha, live) - ((original + 5) % 360)) <= 0.5, 60, 1)
        report.add("rotator controls", "rotator_move moves by the amount", status == 200 and bool(reached), f"HTTP {status}, {ha.value(live)}")
        status, body = ha.service(DOMAIN, "rotator_sync", device_id=device_id, position=123.0)
        synced = ha.wait(lambda: abs(number(ha, live) - 123.0) <= 0.5, 30, 1)
        report.add("rotator controls", "rotator_sync sets the reported position", status == 200 and bool(synced), f"HTTP {status}, {ha.value(live)}")
        ha.service("number", "set_value", entity_id=sync_value, value=45.0)
        time.sleep(12)
        report.add("rotator controls", "sync value survives the polls", number(ha, sync_value) == 45.0, ha.value(sync_value))
        ha.service("button", "press", entity_id=sync_button)
        synced = ha.wait(lambda: abs(number(ha, live) - 45.0) <= 0.5, 30, 1)
        report.add("rotator controls", "button 'Sync' sets the position", bool(synced), ha.value(live))
        # halt a long move
        ha.service("number", "set_value", entity_id=absolute, value=(number(ha, live) + 170) % 360)
        ha.service("button", "press", entity_id=move_abs)
        time.sleep(1.5)
        was_moving = ha.value(moving) == "on"
        ha.service("button", "press", entity_id=halt)
        stopped = settle(ha, moving, "off", 30)
        report.add("rotator controls", "halt stops the move", bool(stopped), f"was moving {was_moving}, position {ha.value(live)}")
        if reverse:
            before = ha.value(reverse)
            flipped = "off" if before == "on" else "on"
            ha.service("switch", f"turn_{flipped}", entity_id=reverse)
            changed = ha.wait(lambda: ha.value(reverse) == flipped, 20, 1)
            report.add("rotator controls", "'Reverse' switches", bool(changed))
            ha.service("switch", f"turn_{before}", entity_id=reverse)
            ha.wait(lambda: ha.value(reverse) == before, 20, 1)
    finally:
        # the reported position follows the mechanical one plus the sync offset: remove the offset, move the
        # mechanical position back, then restore the original offset
        ha.service(DOMAIN, "rotator_sync", device_id=device_id, position=number(ha, mechanical))
        ha.service("number", "set_value", entity_id=absolute, value=original_mechanical)
        ha.service("button", "press", entity_id=move_abs)
        ha.wait(lambda: abs(number(ha, mechanical) - original_mechanical) <= 0.5, 90, 1)
        ha.service(DOMAIN, "rotator_sync", device_id=device_id, position=original)
        ha.wait(lambda: abs(number(ha, live) - original) <= 0.5, 30, 1)


# --- camera ----------------------------------------------------------------------------------------------------
def camera_controls(ha, entities, report):
    f = lambda domain, *words: find(entities, domain, "camera", *words)  # noqa: E731
    apply, start, abort = f("button", "apply_camera_settings"), f("button", "start_exposure"), f("button", "abort_exposure")
    state, exposure = f("sensor", "camera_state"), f("number", "target_exposure")
    bin_x, bin_y = f("number", "bin_x"), f("number", "bin_y")
    numx, numy, startx, starty = f("number", "width_numx"), f("number", "height_numy"), f("number", "start_x"), f("number", "start_y")
    readout, cooler = f("select", "readout_mode"), f("switch", "cooler")
    gain, offset = f("number", "gain"), f("number", "offset")
    if not all([apply, start, state, exposure, bin_x, bin_y, numx, numy, startx, starty]):
        return report.add("camera controls", "entities present", False)
    print("Camera controls:")
    device_id = device_id_of(ha, state)
    keep = {e: ha.value(e) for e in (bin_x, bin_y, numx, numy, startx, starty, exposure, gain, offset) if e}
    original_readout = ha.value(readout) if readout else None
    original_cooler = ha.value(cooler) if cooler else None

    def put_back():
        for entity in (bin_x, bin_y):
            ha.service("number", "set_value", entity_id=entity, value=float(keep[entity]))
        ha.service("button", "press", entity_id=apply)
        time.sleep(5)
        for entity in (numx, numy, startx, starty):
            ha.service("number", "set_value", entity_id=entity, value=float(keep[entity]))
        ha.service("button", "press", entity_id=apply)
        time.sleep(5)

    try:
        # binning, subframe, gain, offset: entered, applied together, read back from the device
        ha.service("number", "set_value", entity_id=numx, value=400.0)
        ha.service("number", "set_value", entity_id=numy, value=300.0)
        ha.service("number", "set_value", entity_id=startx, value=10.0)
        ha.service("number", "set_value", entity_id=starty, value=20.0)
        ha.service("number", "set_value", entity_id=bin_x, value=2.0)
        ha.service("number", "set_value", entity_id=bin_y, value=2.0)
        for entity, value in ((gain, 50.0), (offset, 10.0)):
            if entity:
                ha.service("number", "set_value", entity_id=entity, value=min(value, float(attr(ha, entity, "max") or value)))
        time.sleep(12)
        report.add("camera controls", "entered settings survive the polls", number(ha, numx) == 400.0 and number(ha, bin_x) == 2.0, f"{ha.value(numx)} / {ha.value(bin_x)}")
        ha.service("button", "press", entity_id=apply)
        got = ha.wait(lambda: (number(ha, bin_x), number(ha, numx), number(ha, startx)) == (2.0, 400.0, 10.0), 30, 1)
        report.add("camera controls", "'Apply Camera Settings' applies binning and subframe", bool(got), f"bin {ha.value(bin_x)}, numx {ha.value(numx)}, startx {ha.value(startx)}")
        put_back()
        report.add(
            "camera controls", "settings put back",
            number(ha, bin_x) == float(keep[bin_x]) and number(ha, numx) == float(keep[numx]),
            f"bin {ha.value(bin_x)}, numx {ha.value(numx)}",
        )

        # the subframe through the service
        status, body = ha.service(DOMAIN, "camera_set_roi", device_id=device_id, start_x=5, start_y=6, num_x=200, num_y=100)
        got = ha.wait(lambda: (number(ha, numx), number(ha, numy), number(ha, startx), number(ha, starty)) == (200.0, 100.0, 5.0, 6.0), 30, 1)
        report.add("camera controls", "camera_set_roi sets the four values", status == 200 and bool(got), f"HTTP {status}, {ha.value(numx)}x{ha.value(numy)}+{ha.value(startx)}+{ha.value(starty)}")
        put_back()

        # readout mode
        if readout:
            options = attr(ha, readout, "options") or []
            others = [o for o in options if o != original_readout]
            if others:
                ha.service("select", "select_option", entity_id=readout, option=others[0])
                ha.service("button", "press", entity_id=apply)
                got = ha.wait(lambda: ha.value(readout) == others[0], 30, 1)
                report.add("camera controls", "readout mode applied", bool(got), ha.value(readout))
                ha.service("select", "select_option", entity_id=readout, option=original_readout)
                ha.service("button", "press", entity_id=apply)
                ha.wait(lambda: ha.value(readout) == original_readout, 30, 1)
            else:
                report.add("camera controls", "readout mode (only one mode, nothing to switch)", True, str(options))
        if cooler:
            flipped = "off" if original_cooler == "on" else "on"
            ha.service("switch", f"turn_{flipped}", entity_id=cooler)
            changed = ha.wait(lambda: ha.value(cooler) == flipped, 30, 1)
            report.add("camera controls", "cooler switches", bool(changed))
            ha.service("switch", f"turn_{original_cooler}", entity_id=cooler)
            ha.wait(lambda: ha.value(cooler) == original_cooler, 30, 1)

        # abort a long exposure
        if abort:
            ha.service("number", "set_value", entity_id=exposure, value=20.0)
            ha.service("button", "press", entity_id=start)
            running = ha.wait(lambda: ha.value(state) in ("Exposing", "Waiting"), 15, 0.5)
            started = time.time()
            ha.service("button", "press", entity_id=abort)
            idle = ha.wait(lambda: ha.value(state) == "Idle", 20, 0.5)
            report.add("camera controls", "abort ends a 20 s exposure early", bool(running) and bool(idle) and time.time() - started < 15, f"running {bool(running)}, idle after {time.time() - started:.1f} s")
    finally:
        ha.service("number", "set_value", entity_id=exposure, value=float(keep[exposure]))
        for entity in (gain, offset):
            if entity:
                ha.service("number", "set_value", entity_id=entity, value=float(keep[entity]))
        ha.service("button", "press", entity_id=apply)
        time.sleep(3)


def run_controls(ha, entities, report):
    telescope_controls(ha, entities, report)
    dome_controls(ha, entities, report)
    focuser_controls(ha, entities, report)
    rotator_controls(ha, entities, report)
    camera_controls(ha, entities, report)
