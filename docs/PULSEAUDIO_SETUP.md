# PulseAudio Combined Input/Output Setup

This guide explains how to create a virtual PulseAudio sink that mixes your
**microphone** and **speaker output** together into a single recordable source
(`combined_io.monitor`).  This is useful for capturing both sides of a call,
meeting, or any desktop audio session in one recording.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    combined_io  (null sink)                  │
│                                                             │
│   ┌─────────────────────┐    ┌──────────────────────────┐   │
│   │  alsa_input (mic)   │───▶│  module-loopback (mic)   │   │
│   └─────────────────────┘    └──────────────┬───────────┘   │
│                                             │               │
│   ┌─────────────────────┐    ┌──────────────▼───────────┐   │
│   │ alsa_output.monitor │───▶│ module-loopback (spk)    │   │
│   └─────────────────────┘    └──────────────────────────┘   │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │           combined_io.monitor  ◀── record here         │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**PulseAudio modules used:**

| Module | Role |
|--------|------|
| `module-null-sink` | Virtual mixing bus (`combined_io`) |
| `module-loopback` (×2) | Routes mic and speaker monitor into the bus |
| `module-suspend-on-idle` `timeout=0` | Prevents sinks from suspending |

---

## Quick setup

```bash
# Make the script executable (first time only)
chmod +x scripts/setup_pulse_combined.sh

# View current state
./scripts/setup_pulse_combined.sh --status

# Apply for this session (interactive prompt to persist)
./scripts/setup_pulse_combined.sh --apply

# Apply and write permanent config in one step
./scripts/setup_pulse_combined.sh --apply --persist
```

---

## Recording

### Both sides (mic + speaker)
```bash
pawnai-recorder record --sink combined_io.monitor
```

### Speaker only
```bash
pawnai-recorder record --sink alsa_output.pci-*.analog-stereo.monitor
# or use list-sinks to find the exact name:
pawnai-recorder list-sinks
pawnai-recorder record --sink <monitor-source>
```

### Microphone only (normal input recording)
```bash
pawnai-recorder record        # interactive device selection
pawnai-recorder record --device-id 0
```

---

## How the sink is built manually

If you prefer to set things up by hand without the script:

### Step 1 — Create the null sink (mixing bus)

```bash
pactl load-module module-null-sink \
    sink_name=combined_io \
    sink_properties=device.description="Combined_Mic_and_Speaker" \
    source_properties=device.class=abstract
```

> `device.class=abstract` prevents browsers from auto-selecting
> `combined_io.monitor` as a microphone input.

### Step 2 — Route the speaker monitor into the bus

```bash
pactl load-module module-loopback \
    source=alsa_output.pci-0000_00_1f.3.analog-stereo.monitor \
    sink=combined_io \
    latency_msec=20
```

### Step 3 — Route the microphone into the bus

```bash
pactl load-module module-loopback \
    source=alsa_input.pci-0000_00_1f.3.analog-stereo \
    sink=combined_io \
    latency_msec=20
```

### Step 4 — Pin the default source to the real microphone

```bash
pactl set-default-source alsa_input.pci-0000_00_1f.3.analog-stereo
```

### Step 5 — Disable auto-suspend

```bash
# Unload the default suspend module first
SUSPEND_ID=$(pactl list short modules | awk '/module-suspend-on-idle/{print $1}')
pactl unload-module "$SUSPEND_ID"
pactl load-module module-suspend-on-idle timeout=0
```

### Step 6 — Make it permanent

Add these lines to `~/.config/pulse/default.pa`:

```
load-module module-null-sink sink_name=combined_io sink_properties=device.description="Combined_Mic_and_Speaker" source_properties=device.class=abstract
load-module module-loopback source=alsa_output.pci-0000_00_1f.3.analog-stereo.monitor sink=combined_io latency_msec=20
load-module module-loopback source=alsa_input.pci-0000_00_1f.3.analog-stereo sink=combined_io latency_msec=20
set-default-source alsa_input.pci-0000_00_1f.3.analog-stereo
load-module module-suspend-on-idle timeout=0
```

Then restart PulseAudio:

```bash
pulseaudio -k && pulseaudio --start
```

---

## Troubleshooting

### Sink is SUSPENDED — `parec` returns silence

Sinks auto-suspend when idle.  Wake them or disable auto-suspend:

```bash
# Wake for this session
pactl suspend-sink combined_io 0
pactl suspend-sink alsa_output.pci-0000_00_1f.3.analog-stereo 0

# Permanently disable auto-suspend (already done by the setup script)
./scripts/setup_pulse_combined.sh --apply --persist
```

### Browser / WebRTC app can't access the microphone

The browser may have grabbed `combined_io.monitor` instead of your real mic.
Fix without restarting:

```bash
# 1. Find the browser's source-output ID
pactl list short source-outputs

# 2. Move it back to the real mic (replace 31 with the actual ID)
pactl move-source-output 31 alsa_input.pci-0000_00_1f.3.analog-stereo

# 3. Confirm
pactl list short source-outputs
```

If this keeps happening, ensure `device.class=abstract` is set on
`combined_io.monitor` (the setup script does this automatically).

### combined_io is missing after reboot

The modules were loaded for this session only.  Apply persistently:

```bash
./scripts/setup_pulse_combined.sh --apply --persist
```

### Tear down and start fresh

```bash
./scripts/setup_pulse_combined.sh --remove
./scripts/setup_pulse_combined.sh --apply --persist
```

### Check what is loaded

```bash
./scripts/setup_pulse_combined.sh --status

# Or manually:
pactl list short sinks
pactl list short sources
pactl list short modules | grep -E "loopback|null"
```

---

## Removing the setup

```bash
./scripts/setup_pulse_combined.sh --remove
```

This unloads the loopback modules and the null sink from the running session
and removes the pawnai-recorder block from `~/.config/pulse/default.pa`.

---

## Useful commands reference

```bash
# List all output sinks and their monitor sources
pawnai-recorder list-sinks

# Live level meter for all inputs and outputs
pawnai-recorder monitor

# Record from combined bus
pawnai-recorder record --sink combined_io.monitor --no-upload

# Check default mic/speaker
pactl info | grep Default

# List all source-outputs (which app reads which source)
pactl list short source-outputs

# Forcibly move an app's stream to a specific source
pactl move-source-output <source-output-id> <source-name>
```
