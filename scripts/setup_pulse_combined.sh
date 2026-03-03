#!/usr/bin/env bash
# setup_pulse_combined.sh
#
# Creates a PulseAudio virtual sink (combined_io) that mixes the microphone
# and speaker output together into a single monitor source.  This allows
# pawnai-recorder to capture both sides of a conversation in one pass:
#
#   pawnai-recorder record --sink combined_io.monitor --no-upload
#
# Usage:
#   ./scripts/setup_pulse_combined.sh            # auto-detect devices
#   ./scripts/setup_pulse_combined.sh --apply    # also write ~/.config/pulse/default.pa
#   ./scripts/setup_pulse_combined.sh --remove   # tear down combined_io and loopbacks
#   ./scripts/setup_pulse_combined.sh --status   # show current state
#
# Requirements: pulseaudio, pactl (pulseaudio-utils)

set -euo pipefail

# ── colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
success() { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
error()   { echo -e "${RED}[error]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── helpers ─────────────────────────────────────────────────────────────────
require() { command -v "$1" &>/dev/null || die "'$1' not found. Install pulseaudio-utils."; }

pa_module_loaded() {
    pactl list short modules 2>/dev/null | grep -q "$1"
}

pa_sink_exists() {
    pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -qx "$1"
}

# ── detect devices ──────────────────────────────────────────────────────────
detect_devices() {
    SINK=$(pactl list short sinks \
        | awk '{print $2}' \
        | grep -v "combined_io" \
        | head -1)

    SOURCE=$(pactl list short sources \
        | grep -v monitor \
        | awk '{print $2}' \
        | head -1)

    MONITOR="${SINK}.monitor"

    [[ -n "$SINK"   ]] || die "No real output sink found."
    [[ -n "$SOURCE" ]] || die "No real input source (microphone) found."
}

# ── status ──────────────────────────────────────────────────────────────────
cmd_status() {
    echo -e "\n${BOLD}── Sinks ───────────────────────────────────────────${RESET}"
    pactl list short sinks
    echo -e "\n${BOLD}── Sources ─────────────────────────────────────────${RESET}"
    pactl list short sources
    echo -e "\n${BOLD}── Loopback modules ────────────────────────────────${RESET}"
    pactl list short modules | grep -E "loopback|null-sink" || echo "  (none)"
    echo -e "\n${BOLD}── Default devices ─────────────────────────────────${RESET}"
    echo "  Default sink:   $(pactl get-default-sink)"
    echo "  Default source: $(pactl get-default-source)"

    if pa_sink_exists combined_io; then
        echo -e "\n${GREEN}combined_io is ACTIVE${RESET}"
        echo -e "  Record with: ${BOLD}pawnai-recorder record --sink combined_io.monitor${RESET}"
    else
        echo -e "\n${YELLOW}combined_io is NOT loaded${RESET}"
        echo -e "  Run: ${BOLD}$0 --apply${RESET} to set it up."
    fi
}

# ── apply (load modules + optional persistent config) ───────────────────────
cmd_apply() {
    local persistent=${1:-false}
    require pactl

    detect_devices
    echo -e "\n${BOLD}Detected devices${RESET}"
    echo "  Output sink:  $SINK"
    echo "  Input source: $SOURCE"
    echo "  Monitor:      $MONITOR"
    echo ""

    # ── 1. null sink ──────────────────────────────────────────────────────
    if pa_sink_exists combined_io; then
        warn "combined_io already exists — skipping null-sink creation."
    else
        info "Loading module-null-sink (combined_io)…"
        pactl load-module module-null-sink \
            sink_name=combined_io \
            sink_properties=device.description="Combined_Mic_and_Speaker"
        # Mark the auto-created monitor as abstract so browsers skip it as a mic candidate
        pactl update-source-proplist combined_io.monitor device.class=abstract 2>/dev/null || true
        success "combined_io created."
    fi

    # ── 2. loopback: speaker monitor → combined_io ────────────────────────
    if pactl list short modules | grep -q "module-loopback.*source=${MONITOR}"; then
        warn "Loopback from ${MONITOR} already exists — skipping."
    else
        info "Loading loopback: ${MONITOR} → combined_io…"
        pactl load-module module-loopback \
            source="${MONITOR}" \
            sink=combined_io \
            latency_msec=20
        success "Speaker loopback active."
    fi

    # ── 3. loopback: microphone → combined_io ─────────────────────────────
    if pactl list short modules | grep -q "module-loopback.*source=${SOURCE}"; then
        warn "Loopback from ${SOURCE} already exists — skipping."
    else
        info "Loading loopback: ${SOURCE} → combined_io…"
        pactl load-module module-loopback \
            source="${SOURCE}" \
            sink=combined_io \
            latency_msec=20
        success "Mic loopback active."
    fi

    # ── 4. pin default source to real mic ─────────────────────────────────
    info "Pinning default source to ${SOURCE}…"
    pactl set-default-source "${SOURCE}"
    success "Default source set."

    # ── 5. disable auto-suspend ───────────────────────────────────────────
    if ! pactl list short modules | grep -q "module-suspend-on-idle.*timeout=0"; then
        info "Disabling auto-suspend (timeout=0)…"
        # Unload existing suspend-on-idle (it may be loaded by default config)
        SUSPEND_MOD=$(pactl list short modules | awk '/module-suspend-on-idle/{print $1}' | head -1)
        if [[ -n "$SUSPEND_MOD" ]]; then
            pactl unload-module "$SUSPEND_MOD" 2>/dev/null || true
        fi
        pactl load-module module-suspend-on-idle timeout=0
        success "Auto-suspend disabled."
    else
        warn "Auto-suspend already disabled — skipping."
    fi

    echo ""
    success "combined_io.monitor is ready!"
    echo -e "  ${BOLD}pawnai-recorder record --sink combined_io.monitor${RESET}"

    # ── 6. optional: write persistent config ─────────────────────────────
    if [[ "$persistent" == "true" ]]; then
        write_config
    else
        echo ""
        warn "This setup will NOT survive a PulseAudio restart."
        echo -e "  Run ${BOLD}$0 --apply --persist${RESET} or ${BOLD}$0 --apply${RESET} then confirm to make it permanent."
        echo ""
        read -rp "Write to ~/.config/pulse/default.pa now? [y/N] " ans
        if [[ "${ans,,}" == "y" ]]; then
            write_config
        fi
    fi
}

# ── write persistent config ─────────────────────────────────────────────────
write_config() {
    local config_dir="$HOME/.config/pulse"
    local config_file="$config_dir/default.pa"
    local MARKER="# == pawnai-recorder combined_io begin =="
    local MARKER_END="# == pawnai-recorder combined_io end =="

    mkdir -p "$config_dir"

    # Remove any previous pawnai block
    if [[ -f "$config_file" ]]; then
        if grep -q "$MARKER" "$config_file"; then
            info "Replacing existing pawnai-recorder block in $config_file…"
            # Remove lines between markers (inclusive)
            sed -i "/${MARKER}/,/${MARKER_END}/d" "$config_file"
        fi
    fi

    info "Writing persistent config to $config_file…"
    cat >> "$config_file" <<EOF

${MARKER}
# Created by pawnai-recorder/scripts/setup_pulse_combined.sh on $(date '+%Y-%m-%d %H:%M')
# Combined mic + speaker recording bus.
# The monitor source is marked device.class=abstract so browsers skip it as a mic candidate.
load-module module-null-sink sink_name=combined_io sink_properties=device.description="Combined_Mic_and_Speaker"
update-source-proplist combined_io.monitor device.class=abstract
load-module module-loopback source=${MONITOR} sink=combined_io latency_msec=20
load-module module-loopback source=${SOURCE} sink=combined_io latency_msec=20
set-default-source ${SOURCE}
load-module module-suspend-on-idle timeout=0
${MARKER_END}
EOF
    success "Persistent config written to $config_file"
    echo -e "  Changes take effect on next PulseAudio restart: ${BOLD}pulseaudio -k && pulseaudio --start${RESET}"
}

# ── remove ──────────────────────────────────────────────────────────────────
cmd_remove() {
    require pactl
    local config_file="$HOME/.config/pulse/default.pa"
    local MARKER="# == pawnai-recorder combined_io begin =="
    local MARKER_END="# == pawnai-recorder combined_io end =="

    info "Unloading loopback modules connected to combined_io…"
    # Unload loopbacks feeding combined_io
    pactl list short modules \
        | awk '/module-loopback.*combined_io/{print $1}' \
        | xargs -r -I{} pactl unload-module {} 2>/dev/null || true

    info "Unloading module-null-sink (combined_io)…"
    pactl list short modules \
        | awk '/module-null-sink.*combined_io/{print $1}' \
        | xargs -r -I{} pactl unload-module {} 2>/dev/null || true

    success "combined_io torn down."

    # Remove from persistent config if present
    if [[ -f "$config_file" ]] && grep -q "$MARKER" "$config_file"; then
        info "Removing pawnai-recorder block from $config_file…"
        sed -i "/${MARKER}/,/${MARKER_END}/d" "$config_file"
        success "Persistent config cleaned."
    else
        warn "No pawnai-recorder block found in $config_file — nothing to clean."
    fi
}

# ── entry point ─────────────────────────────────────────────────────────────
require pactl

case "${1:-}" in
    --status)  cmd_status ;;
    --remove)  cmd_remove ;;
    --apply)
        if [[ "${2:-}" == "--persist" ]]; then
            cmd_apply true
        else
            cmd_apply false
        fi
        ;;
    "")
        echo -e "${BOLD}PawnAI Recorder — PulseAudio combined sink setup${RESET}"
        echo ""
        echo "Usage:"
        echo "  $0 --status           Show current audio state"
        echo "  $0 --apply            Set up combined_io (interactive persist)"
        echo "  $0 --apply --persist  Set up combined_io + write permanent config"
        echo "  $0 --remove           Tear down combined_io and clean config"
        echo ""
        cmd_status
        ;;
    *)  die "Unknown option: $1. Use --apply, --remove, or --status." ;;
esac
