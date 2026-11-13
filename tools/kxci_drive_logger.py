#!/usr/bin/env python3
"""KXCI 91.3 FM signal reach, step 3: drive-test logger for an RTL-SDR dongle.

Two commands:

    py tools/kxci_drive_logger.py log --gps COM5
        Runs rtl_power on 91.3 MHz and writes one row a second to
        kxci-signal/drives/drive_<UTC start>.csv, with the position from a USB GPS
        receiver that speaks NMEA on a serial port. Ctrl+C stops it.

    py tools/kxci_drive_logger.py log
        Same, without a GPS: rows carry the UTC time only. Add positions afterwards:

    py tools/kxci_drive_logger.py join drive_20261114T170000Z.csv track.gpx
        Fills in latitude and longitude from any GPX track recorded on the same
        drive (a phone, a bike computer, the 360 camera), matched by time.

Needs rtl_power on the PATH (part of the rtl-sdr tools; on Windows the dongle also
needs the WinUSB driver, installed with Zadig). The GPS option needs pyserial
(py -m pip install pyserial).

What a row means
----------------
chan_db   power in the 200 kHz channel centred on 91.3 MHz, in rtl_power's dB.
floor_db  the quietest tenth of the bins in the same sweep, scaled to 200 kHz:
          a rough noise floor for that moment.
snr_db    chan_db minus floor_db.

A consumer dongle is not calibrated, so chan_db is NOT dBu. Readings are only
comparable with each other, and only if nothing changes between them: same dongle,
same antenna in the same spot on the truck, same --gain for every drive. Automatic
gain would wreck that, so the gain is always fixed. Near the tower a strong signal
can overload the dongle: if chan_db stops rising as you approach, lower --gain and
start again. Keep the PC clock set from the internet before a drive with no GPS,
because the join is by time.
"""
import argparse
import csv
import math
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVES = ROOT / "kxci-signal" / "drives"

CENTRE_HZ = 91.3e6
HALF_CHANNEL_HZ = 100e3       # FM channels are 200 kHz wide
SPAN_HZ = 400e3               # sweep 90.9 to 91.7 MHz
BIN_HZ = 12.5e3
FIELDS = ["utc", "lat", "lon", "gps_age_s", "speed_kmh", "hdop", "sats",
          "chan_db", "floor_db", "snr_db", "gain_db", "bins"]


def utc_now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- rtl_power

def parse_sweep(line):
    """One rtl_power line -> (hz_low, hz_step, [dB per bin]) or None."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 8:
        return None
    try:
        low, step = float(parts[2]), float(parts[4])
        dbs = [float(p) for p in parts[6:] if p]
    except ValueError:
        return None
    dbs = [d for d in dbs if math.isfinite(d)]
    return (low, step, dbs) if dbs else None


def channel_power(low, step, dbs):
    """Channel power and noise floor (both dB, in 200 kHz) from one sweep."""
    lin = [10 ** (d / 10) for d in dbs]
    centres = [low + (i + 0.5) * step for i in range(len(dbs))]
    inside = [p for f, p in zip(centres, lin) if abs(f - CENTRE_HZ) <= HALF_CHANNEL_HZ]
    if not inside:
        return None
    chan = 10 * math.log10(sum(inside))
    quiet = sorted(lin)[:max(1, len(lin) // 10)]
    floor = 10 * math.log10(sum(quiet) / len(quiet) * len(inside))
    return chan, floor, len(inside)


# ---------------------------------------------------------------- GPS (NMEA)

def nmea_ok(sentence):
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, _, check = sentence[1:].partition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(check[:2], 16)
    except ValueError:
        return False


def nmea_degrees(value, hemi):
    if not value:
        return None
    dot = value.index(".")
    deg = float(value[:dot - 2]) + float(value[dot - 2:]) / 60
    return -deg if hemi in ("S", "W") else deg


class Gps:
    """Keeps the latest fix from a serial NMEA receiver."""

    def __init__(self):
        self.fix = None            # dict(lat, lon, speed_kmh, hdop, sats, at)
        self.lock = threading.Lock()

    def feed(self, sentence):
        sentence = sentence.strip()
        if not nmea_ok(sentence):
            return
        f = sentence[1:sentence.index("*")].split(",")
        kind = f[0][2:]
        with self.lock:
            cur = dict(self.fix or {})
            if kind == "RMC" and len(f) > 7 and f[2] == "A":
                cur.update(lat=nmea_degrees(f[3], f[4]), lon=nmea_degrees(f[5], f[6]),
                           speed_kmh=float(f[7]) * 1.852 if f[7] else None, at=time.monotonic())
            elif kind == "GGA" and len(f) > 8 and f[6] not in ("", "0"):
                cur.update(lat=nmea_degrees(f[2], f[3]), lon=nmea_degrees(f[4], f[5]),
                           sats=int(f[7]) if f[7] else None,
                           hdop=float(f[8]) if f[8] else None, at=time.monotonic())
            else:
                return
            self.fix = cur

    def latest(self):
        with self.lock:
            return dict(self.fix) if self.fix else None

    def read_port(self, port, baud):
        import serial
        with serial.Serial(port, baud, timeout=2) as ser:
            while True:
                raw = ser.readline()
                if raw:
                    self.feed(raw.decode("ascii", "ignore"))


# ---------------------------------------------------------------- log

def row_for(sweep, gps, gain):
    got = channel_power(*sweep)
    if got is None:
        return None
    chan, floor, _ = got
    row = dict(utc=utc_now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
               chan_db=f"{chan:.2f}", floor_db=f"{floor:.2f}", snr_db=f"{chan - floor:.2f}",
               gain_db=gain, bins=" ".join(f"{d:.1f}" for d in sweep[2]))
    fix = gps.latest() if gps else None
    if fix and fix.get("lat") is not None:
        row.update(lat=f"{fix['lat']:.6f}", lon=f"{fix['lon']:.6f}",
                   gps_age_s=f"{time.monotonic() - fix['at']:.1f}")
        for key, fmt in (("speed_kmh", "{:.1f}"), ("hdop", "{:.1f}"), ("sats", "{}")):
            if fix.get(key) is not None:
                row[key] = fmt.format(fix[key])
    return row


def cmd_log(args):
    exe = shutil.which("rtl_power")
    if not exe:
        sys.exit("rtl_power is not on the PATH. Install the rtl-sdr tools first.")
    gps = None
    if args.gps:
        try:
            import serial  # noqa: F401
        except ImportError:
            sys.exit("the GPS option needs pyserial: py -m pip install pyserial")
        gps = Gps()
        threading.Thread(target=gps.read_port, args=(args.gps, args.baud), daemon=True).start()
    DRIVES.mkdir(parents=True, exist_ok=True)
    out = DRIVES / f"drive_{utc_now():%Y%m%dT%H%M%SZ}.csv"
    lo, hi = CENTRE_HZ - SPAN_HZ, CENTRE_HZ + SPAN_HZ
    cmd = [exe, "-f", f"{lo:.0f}:{hi:.0f}:{BIN_HZ:.0f}", "-i", str(args.interval),
           "-g", str(args.gain), "-d", str(args.device), "-"]
    print(" ".join(cmd))
    print(f"writing {out}   (Ctrl+C to stop)")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    n = 0
    try:
        with open(out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            for line in proc.stdout:
                sweep = parse_sweep(line)
                row = row_for(sweep, gps, args.gain) if sweep else None
                if not row:
                    continue
                w.writerow(row)
                fh.flush()
                n += 1
                where = f"{row['lat']}, {row['lon']}" if row.get("lat") else "no position"
                print(f"\r{n:6d}  {row['chan_db']:>7} dB  snr {row['snr_db']:>6}  {where}   ",
                      end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    print(f"\n{n} rows in {out}")
    if n == 0:
        print("no readings: is the dongle plugged in, and is its WinUSB driver installed?")


# ---------------------------------------------------------------- join

def read_gpx(path):
    pts = []
    for el in ET.parse(path).iter():
        if el.tag.rsplit("}", 1)[-1] != "trkpt":
            continue
        when = next((c.text for c in el if c.tag.rsplit("}", 1)[-1] == "time"), None)
        if when:
            t = datetime.fromisoformat(when.strip().replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            pts.append((t.timestamp(), float(el.get("lat")), float(el.get("lon"))))
    pts.sort()
    return pts


def cmd_join(args):
    track = read_gpx(args.gpx)
    if len(track) < 2:
        sys.exit("no timed track points in that GPX file")
    src = Path(args.csv)
    if not src.exists():
        src = DRIVES / args.csv
    rows = list(csv.DictReader(open(src, newline="")))
    times = [t for t, _, _ in track]
    filled = skipped = 0
    import bisect
    for row in rows:
        t = datetime.fromisoformat(row["utc"].replace("Z", "+00:00")).timestamp() + args.offset
        i = bisect.bisect_left(times, t)
        if i == 0 or i == len(times):
            skipped += 1
            continue
        (t0, la0, lo0), (t1, la1, lo1) = track[i - 1], track[i]
        if t1 - t0 > args.max_gap:
            skipped += 1                    # the track paused here: do not invent a position
            continue
        k = (t - t0) / (t1 - t0) if t1 > t0 else 0
        row["lat"] = f"{la0 + (la1 - la0) * k:.6f}"
        row["lon"] = f"{lo0 + (lo1 - lo0) * k:.6f}"
        row["gps_age_s"] = f"{min(t - t0, t1 - t):.1f}"
        filled += 1
    out = src.with_name(src.stem + "_gps.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{filled} rows placed, {skipped} outside the track or in a gap over "
          f"{args.max_gap:.0f} s -> {out}")


def selftest():
    sweep = parse_sweep("2026-11-14, 10:00:00, 90900000, 91700000, 12500.00, 4096, "
                        + ", ".join(["-60.0"] * 24 + ["-20.0"] * 16 + ["-60.0"] * 24))
    chan, floor, n = channel_power(*sweep)
    assert n == 16 and abs(chan - (-20 + 10 * math.log10(16))) < 1e-6, (chan, n)
    assert abs(floor - (-60 + 10 * math.log10(16))) < 1e-6, floor
    g = Gps()
    g.feed("$GPRMC,170000.00,A,3213.3000,N,11055.5800,W,25.0,90.0,141126,,,A*" + "00")
    assert g.latest() is None                          # bad checksum is dropped
    body = "GPRMC,170000.00,A,3213.3000,N,11055.5800,W,25.0,90.0,141126,,,A"
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    g.feed(f"${body}*{cs:02X}")
    fix = g.latest()
    assert abs(fix["lat"] - 32.221667) < 1e-5 and abs(fix["lon"] + 110.926333) < 1e-5, fix
    assert abs(fix["speed_kmh"] - 46.3) < 0.01
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    lg = sub.add_parser("log", help="record signal strength")
    lg.add_argument("--gps", help="serial port of an NMEA GPS receiver, e.g. COM5")
    lg.add_argument("--baud", type=int, default=9600)
    lg.add_argument("--gain", type=float, default=20.0,
                    help="fixed tuner gain in dB; keep it the same for every drive")
    lg.add_argument("--interval", type=int, default=1, help="seconds per reading")
    lg.add_argument("--device", type=int, default=0, help="dongle index")
    jn = sub.add_parser("join", help="add positions from a GPX track")
    jn.add_argument("csv")
    jn.add_argument("gpx")
    jn.add_argument("--offset", type=float, default=0.0,
                    help="seconds to add to the log's clock before matching")
    jn.add_argument("--max-gap", type=float, default=10.0)
    sub.add_parser("selftest", help="check the parsers without any hardware")
    args = ap.parse_args()
    if args.cmd == "log":
        cmd_log(args)
    elif args.cmd == "join":
        cmd_join(args)
    elif args.cmd == "selftest":
        selftest()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
