"""The eyetracker command."""

from __future__ import annotations

import argparse
import logging
import resource
import threading
import time
import webbrowser
from datetime import date, datetime

from eyetracker import guards, service
from eyetracker.config import Config, Paths, load_config
from eyetracker.report import Report, read_status

STATE_TEXT = {
    "tracking": "tracking",
    "idle": "running, nobody at the screen",
    "paused": "paused",
    "screen-locked": "waiting, screen is locked",
    "mic-in-use": "waiting, microphone is in use (camera released for your call)",
    "camera-unavailable": "waiting, another app has the camera",
    "not-running": "not running",
}


def duration(seconds: float) -> str:
    seconds = round(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def cmd_run(config: Config, paths: Paths, args: argparse.Namespace) -> int:
    from eyetracker import daemon

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    return daemon.run(config, paths)


def cmd_check(config: Config, paths: Paths, args: argparse.Namespace) -> int:
    from eyetracker.camera import Camera
    from eyetracker.lightweight import limit_cpu_use
    from eyetracker.tracker import Tracker
    from eyetracker.vision import FaceAnalyzer

    limit_cpu_use()
    camera = Camera(config.camera_index)
    if not camera.open():
        print("Could not open the camera. If the tracker is running, run `eyetracker pause 1` first.")
        return 1
    print(f"Watching for {args.seconds:.0f}s. Nothing is saved. Blink a few times and count them.\n")
    analyzer = FaceAnalyzer()
    tracker = Tracker(config)
    interval = 1 / config.target_fps
    started = next_frame = next_print = time.monotonic()
    cpu_start = time.process_time()
    grabbed = processed = faces = 0
    try:
        while (mono := time.monotonic()) - started < args.seconds:
            if not camera.grab():
                continue
            grabbed += 1
            if mono < next_frame:
                continue
            next_frame = max(next_frame + interval, mono)
            frame = camera.retrieve_rgb()
            if frame is None:
                continue
            sample = analyzer.analyze(frame, int(mono * 1000))
            processed += 1
            faces += sample is not None
            tracker.update(time.time(), sample)
            if mono >= next_print:
                next_print = mono + 0.5
                ear = f"{sample.ear:.3f}" if sample else "  -  "
                state = "looking at screen" if tracker.on_screen else "away / no face"
                print(f"\r  blinks {tracker.total_blinks:3d}   eye openness {ear}   {state:18s}", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        camera.release()
        analyzer.close()

    elapsed = time.monotonic() - started
    fps = processed / elapsed
    print(f"\n\nCamera    {grabbed / elapsed:.1f} fps delivered, {fps:.1f} fps analysed")
    print(f"Face      found in {100 * faces / max(processed, 1):.0f}% of frames")
    print(f"Blinks    {tracker.total_blinks}")
    print(f"CPU       {100 * (time.process_time() - cpu_start) / elapsed:.0f}% of one core")
    print(f"Memory    {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB")
    if fps < 12:
        print("\nFrame rate is low, so short blinks may be missed. More light on your face helps.")
    if processed and faces == 0:
        print("\nNo face found. Check the camera shutter and that you are in frame.")
    return 0


def cmd_status(config: Config, paths: Paths, args: argparse.Namespace) -> int:
    live = read_status(paths.status, guards.paused_until(paths.pause))
    state = live["state"]
    line = STATE_TEXT.get(state, state)
    if state == "tracking" and live.get("on_screen"):
        line += f", {live.get('blinks_last_minute', 0)} blinks in the last minute"
    if "paused_until" in live:
        line = f"paused until {datetime.fromtimestamp(live['paused_until']):%H:%M}"
    print(f"Eye Tracker: {line}\n")

    s = Report(paths.db).summary(date.today())
    if not s["screen_min"]:
        print("Nothing recorded today yet.")
        return 0
    rate = f"{s['blink_rate']} a minute" if s["blink_rate"] is not None else "not enough data yet"
    print("Today")
    print(f"  Blink rate      {rate}")
    print(f"  Screen time     {duration(s['screen_min'] * 60)}")
    print(f"  Longest stare   {duration(s['longest_gap_s'])}")
    print(f"  Real breaks     {s['breaks']}")
    print(f"  Looked away     {s['look_aways']} times")
    print(f"  Reminders       {s['stare_alerts']} blink, {s['break_alerts']} break")
    if s["fps"] is not None and s["fps"] < 12:
        print(f"\nAverage {s['fps']} fps today, so some short blinks were probably missed.")
    return 0


def cmd_dashboard(config: Config, paths: Paths, args: argparse.Namespace) -> int:
    from eyetracker.dashboard import serve

    try:
        server = serve(paths, args.port)
    except OSError as err:
        print(f"Could not use port {args.port} ({err.strerror}). Try `eyetracker dashboard --port 8766`.")
        return 1
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Dashboard at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.3, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    return 0


def cmd_pause(config: Config, paths: Paths, args: argparse.Namespace) -> int:
    until = time.time() + args.minutes * 60
    paths.pause.write_text(str(until))
    print(f"Paused until {datetime.fromtimestamp(until):%H:%M}. The camera is released within a couple of seconds.")
    return 0


def cmd_resume(config: Config, paths: Paths, args: argparse.Namespace) -> int:
    paths.pause.unlink(missing_ok=True)
    print("Resumed.")
    return 0


def cmd_install(config: Config, paths: Paths, args: argparse.Namespace) -> int:
    service.install()
    print(f"Installed {service.unit_path()}\nIt runs now and starts with every login.")
    return 0


def cmd_uninstall(config: Config, paths: Paths, args: argparse.Namespace) -> int:
    service.uninstall()
    print("Removed the background service. Your recorded stats were kept.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eyetracker", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="track in the foreground")
    run.add_argument("-v", "--verbose", action="store_true")
    run.set_defaults(handler=cmd_run)

    check = commands.add_parser("check", help="test the camera and blink detection, saving nothing")
    check.add_argument("--seconds", type=float, default=20)
    check.set_defaults(handler=cmd_check)

    commands.add_parser("status", help="show the current state and today's numbers").set_defaults(
        handler=cmd_status
    )

    dashboard = commands.add_parser("dashboard", help="open the charts in your browser")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--no-browser", action="store_true")
    dashboard.set_defaults(handler=cmd_dashboard)

    pause = commands.add_parser("pause", help="release the camera for a while")
    pause.add_argument("minutes", nargs="?", type=float, default=30)
    pause.set_defaults(handler=cmd_pause)

    commands.add_parser("resume", help="end a pause").set_defaults(handler=cmd_resume)
    commands.add_parser("install", help="run in the background from every login").set_defaults(
        handler=cmd_install
    )
    commands.add_parser("uninstall", help="remove the background service").set_defaults(
        handler=cmd_uninstall
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = Paths.default()
    paths.ensure()
    return args.handler(load_config(paths.config_file), paths, args)
