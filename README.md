# Eye Tracker

Tracks how often you blink and how long you stare at your screen, using your
laptop's webcam. It runs quietly in the background, shows you the numbers later,
and nudges you when you have gone too long without blinking or without a break.

Everything stays on your computer. Each video frame is reduced to three numbers
and thrown away. No image is ever saved.

## Getting started

Install it once:

```sh
uv tool install --editable --python 3.12 .
```

Then check that it can see you. This saves nothing:

```sh
eyetracker check
```

Blink ten times while it runs and compare the count. If that looks right, turn
on background tracking:

```sh
eyetracker install
```

It starts now and again at every login. To see your numbers:

```sh
eyetracker dashboard   # charts in your browser
eyetracker status      # a quick summary in the terminal
```

## Commands

| Command | What it does |
|---|---|
| `eyetracker check` | Tests the camera and blink detection, saving nothing |
| `eyetracker install` | Runs in the background from every login |
| `eyetracker uninstall` | Removes the background service and keeps your stats |
| `eyetracker status` | Shows the current state and today's numbers |
| `eyetracker dashboard` | Opens the charts in your browser |
| `eyetracker pause [minutes]` | Releases the camera, for 30 minutes by default |
| `eyetracker resume` | Ends a pause |
| `eyetracker run` | Tracks in the foreground |

## What it measures

- **Blink rate.** Blinks a minute while you face the screen.
- **Longest stare.** The longest stretch at the screen without a blink.
- **Screen time.** Time spent facing the screen.
- **Looking away.** Each time you turn away for 2 seconds or more.
- **Real breaks.** Each time you are away from the screen for 20 seconds or more.

People blink about 15 times a minute at rest and about half that at a screen.

## Reminders

You get a desktop notification after 30 seconds without a blink, and after 20
minutes of screen time without a real break. Closing your eyes for a moment
counts as a blink, so following the advice clears the reminder.

## Your camera and your calls

Linux lets only one app stream from a webcam at a time, so the tracker gets out
of the way. It releases the camera within about 5 seconds when your microphone
goes live, when your screen locks, or when you run `eyetracker pause`, and picks
it back up afterwards.

A call app that opens the camera before the microphone may still report the
camera as busy for those few seconds. If so, retry in the app or run
`eyetracker pause` before you join.

## Privacy

- Frames are analysed in memory and discarded. Only per-minute totals are stored.
- The background service runs with no network access, enforced by systemd.
- The dashboard listens only on this computer and loads nothing from the internet.
- Your data is one SQLite file at `~/.local/share/eyetracker/eyetracker.db`.
  Delete that file to erase it.

## Settings

Create `~/.config/eyetracker/config.toml` with anything you want to change, then
run `systemctl --user restart eyetracker`. These are the defaults:

```toml
camera_index = 0
target_fps = 20             # frames analysed per second
idle_fps = 1                # while nobody is at the screen
idle_after_s = 10
pause_when_mic_active = true
pause_when_locked = true
alerts_enabled = true
stare_alert_s = 30          # remind after this long without a blink
stare_alert_cooldown_s = 300
break_alert_min = 20        # remind after this much screen time
break_alert_cooldown_min = 5
break_min_s = 20            # time away that counts as a real break
```

## How much it costs

Measured on an Intel i5-10300H:

| State | CPU | Memory |
|---|---|---|
| Tracking your face at 20 fps | 40% of one core, or 5% of the whole CPU | 185 MB |
| Running with nobody at the screen | 3% of one core | 180 MB |
| Paused, locked or in a call | 0.3% of one core, camera off | 170 MB |

The neural network accounts for nearly all of the tracking cost. Lowering
`target_fps` to 15 saves about 5 points of one core, but counts up to 9% fewer
blinks, so 20 is the default.

## How accurate it is

Tested on about 5 minutes of two public-domain videos of a person speaking to a
camera, framed like a webcam, with blinks labelled by hand from eye crops:

| | Clear blinks caught | Detections that were real | Error in blink count |
|---|---|---|---|
| Video used to tune the detector | 94.6% | 97.3% | -0.9% |
| Video kept back for testing | 93.6% | 94.9% | 0.0% |
| Same, simulating a cheap camera at night | 96.2% | 93.8% | +2.6% |

Treat these as a good sign rather than a guarantee. It is one person, speaking,
in studio light, without glasses. Glasses with strong reflections, very dim light
and a camera far off to the side will all make it less accurate. If `status` warns
about a low frame rate, short blinks are being missed, and more light on your face
is the fix.

Looking away is judged from your head direction, so a glance that moves only your
eyes is not counted. A camera cannot tell how far away you are focusing, so a real
break means turning away from the screen, not necessarily looking into the distance.

These numbers are estimates and not a medical measurement. If your eyes are
often sore or dry, see an eye doctor.

## How it works

```
camera -> face landmarks -> eye openness + head direction -> per-minute totals -> SQLite
          (MediaPipe)        (frame discarded here)            (alerts here)       (dashboard)
```

A blink is a dip in eye openness below your own recent open-eye level, with the
end judged by how far the eye has recovered from the bottom of the dip. This works
for any eye shape and copes with changes in expression and posture.

## Development

```sh
uv sync
uv run pytest
```

The tests need no camera. `tests/test_end_to_end.py` runs generated video through
the real model, and `tests/test_real_blinks.py` replays recorded numbers from real
human blinks.

Supported on Linux with V4L2 webcams. Screen-lock detection needs GNOME, and
microphone detection needs PipeWire or PulseAudio. On other desktops those guards
stay inactive and `eyetracker pause` still works.

## Credits

`src/eyetracker/assets/face_landmarker.task` is the Face Landmarker model from
[Google MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker),
used under the Apache License 2.0. Test data sources are described in
`tests/data/README.md`.
