# ReDrive

Remote driver/rider control interface for ReStim-compatible e-stim devices.

The **driver** opens a browser on any device and controls patterns, intensity, electrode position, and more in real time. **Riders** open a browser page that connects directly to their local ReStim - no app install needed.

---

## Features

- **Pattern engine** - Hold, Sine, Ramp, Pulse, Burst, Random, Edge
- **Beta sweep** - smooth oscillation between electrodes with configurable skew
- **Spiral mode** - quadrature beta/alpha sweep that tightens toward centre and auto-resets
- **Intensity ramp** - smooth ramp to target over configurable duration
- **Touch interface** - draw patterns on an anatomy overlay; Y = electrode position, X = intensity
- **Gesture looping** - draw a gesture, release, and it loops indefinitely with a dedicated Touch beta mode
- **Presets** - one-click full state recall (Milking preset included)
- **Poppers overlay** - full-screen rider notification with countdown (Normal, Deep Huff, Double Hit modes)
- **Rider avatars** - riders upload a photo that persists across sessions (stored in browser, no server storage)
- **ReStim Bridge** - rider's browser connects directly to local ReStim via WebSocket

---

## Requirements

```
pip install aiohttp jinja2 aiohttp-jinja2
```

ReStim must be running with its WebSocket server enabled (default `ws://localhost:12346/tcode`).

---

## Usage

### LAN mode (single room, local ReStim)

```
python server.py --local
```

Starts a single-room server that connects directly to your local ReStim. URLs for the driver and rider pages are printed on startup.

| Who | What to open |
|-----|-------------|
| Driver | Open the driver URL printed at startup |
| Rider | Open the rider URL (same machine or any device on the LAN) |

The rider controls their own maximum power via ReStim's master volume slider. ReDrive controls pattern shape and relative intensity within that limit.

### Relay mode (multi-rider, cloud server)

```
python server.py --port 8765
```

Starts the relay server for VPS deployment. Drivers create rooms; riders join via room codes. Each rider's browser connects to their own local ReStim using the built-in ReStim Bridge (gear icon on the rider page).

### Quick deploy (Ubuntu 22.04)

```bash
bash deploy/setup.sh
```

Installs nginx, certbot, Python venv, and systemd service. Obtains a TLS certificate.

### Room codes

- 10 characters from an unambiguous alphabet (no 0/O/1/I/L)
- Each room expires after 24 hours of inactivity
- Driver copies the code via the banner at the top of the driver page

---

## Configuration

On first run, `redrive_config.json` is created with defaults. See `redrive_config.json.example` for reference.

| Key | Default | Description |
|-----|---------|-------------|
| `restim_url` | `ws://localhost:12346/tcode` | ReStim WebSocket address |
| `ctrl_port` | `8765` | Port for the web UI |
| `axis_volume` | `V0` | T-code axis for volume (ReStim VOLUME_API) |
| `axis_beta` | `L1` | T-code axis for electrode position (ReStim POSITION_BETA) |
| `axis_alpha` | `L0` | T-code axis for alpha oscillation (ReStim POSITION_ALPHA) |
| `tcode_floor` | `0` | Minimum T-code value when intensity > 0 |
| `send_interval_ms` | `50` | Command send rate (ms) |
| `touch_images` | (see example) | Touch panel image list (`name` + `filename` in `touch_assets/anatomy/`) |
| `overlay_image` | `overlay.png` | Transparent overlay PNG in `touch_assets/anatomy/` |

---

## Touch panel

The driver's Touch tab shows an anatomy image. Drag to control the signal:

- **Vertical (Y)** = electrode position: top = L+, bottom = R+
- **Horizontal (X)** = intensity within the base power window
- **Base Power slider** = sets the intensity floor (X adds up to 25% on top)

Drawing a gesture and releasing it starts a loop. The "Touch" beta mode plays the recorded gesture. Switch to other modes (Sweep, Auto, etc.) to pause, then switch back or click Resume to re-engage.

---

## Adding presets

Presets live in the `PRESETS` dict in `engine.py`. The driver UI fetches the preset list from the server automatically.

---

## Running tests

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -v
```

---

## Acknowledgements

- [ReStim](https://github.com/diglet48/restim) by diglet48 - the e-stim engine this bridges to
- T-code protocol - standard used across the e-stim/toy ecosystem
