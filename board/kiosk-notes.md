# The screen

## At the demo: a laptop's browser on the Pi's hotspot
The demo screen is a laptop's browser (AGENTS.md: no monitor, no Pi kiosk). The laptop joins the Pi's 5 GHz hotspot and opens http://192.168.77.2:8080/?src=ws. `?src=ws` makes the page read the brain's live WebSocket; without it the page shows its built-in mock states.

How it gets there: the laptop's default route is the Pi (10.42.0.1). The Pi forwards 192.168.77.2 over the Ethernet cable, and its hotspot profile (`ipv4.method shared`, pi/ap.sh) rewrites the laptop's address to the Pi's own on the way, so the board answers over the cable too. The board's Wi-Fi only carries the Pi's frames for the pi5>unoq:wifi reading.

1. Before the laptop joins: the cable is up (`sudo bash pi/eth.sh` on the Pi, `sudo bash board/eth.sh` on the board) and `python3 -m radio.check` on the board has no `FAIL` on Ethernet.
2. Join the laptop to the Pi's hotspot (the SSID and passphrase in the Pi's `.env`; never on GitHub).
3. Open http://192.168.77.2:8080/?src=ws full screen. Works: the page loads and its source badge says LIVE once readings flow.
4. While the model runs, keep the laptop's traffic on the hotspot light: just the page. Never copy files or bundles over it during a demo or a recording: it can starve the sensing link and show SENSOR BLIND.

If the page doesn't load: `ping 10.42.0.1` from the laptop (the hotspot), then `ping 192.168.77.2` (the Pi forwarding to the board). If the first works and the second doesn't, check the cable and `board/eth.sh`.

## Not used at the demo: a kiosk on the Pi
The steps below put the same page full screen on a monitor plugged into the Pi. They're kept for a build-room screen only.

The Pi's screen shows the board's web page, http://192.168.77.2:8080/?src=ws, full screen from boot. These steps are for Raspberry Pi OS with desktop (Bookworm or Trixie) running Wayland with labwc, the default on a Pi 5. Do them once, on the Pi, as the user that logs in to the desktop.

## Before you start
- The Ethernet link is up (`sudo bash pi/eth.sh` on the Pi and `sudo bash board/eth.sh` on the board), and the board is serving: `curl -sI http://192.168.77.2:8080/` answers `200`.
- The desktop runs labwc: in a terminal on the Pi's screen, `echo $XDG_SESSION_TYPE` prints `wayland` and `pgrep -a labwc` shows a process. If it doesn't, run `sudo raspi-config` and pick Advanced Options > Wayland > labwc, then reboot.
- Chromium is installed. It's `chromium` on Trixie and `chromium-browser` on older Bookworm images; the script below finds either one.

## 1. Log in to the desktop without a password
```sh
sudo raspi-config nonint do_boot_behaviour B4
```
B4 is "desktop, logged in automatically".

## 2. Keep the screen on
```sh
sudo raspi-config nonint do_blanking 1
```
1 turns screen blanking off. You can also use `sudo raspi-config` > Display Options > Screen Blanking > No.

## 3. The kiosk command
This writes a small script. It waits until the board's web server answers, then keeps Chromium full screen on the page, starting it again if it closes or crashes. It uses a fresh profile on every start, so you never get a "Restore pages?" bubble or a stale cache.
```sh
mkdir -p ~/.local/bin
cat > ~/.local/bin/radio-sight-kiosk <<'EOF'
#!/bin/sh
BASE=http://192.168.77.2:8080
URL="$BASE/?src=ws"
BROWSER=$(command -v chromium || command -v chromium-browser)
PROFILE="${XDG_RUNTIME_DIR:-/tmp}/radio-sight-kiosk"
until curl -sf -o /dev/null "$BASE/proof.json"; do sleep 2; done
while true; do
    rm -rf "$PROFILE"
    "$BROWSER" --kiosk --ozone-platform-hint=auto --noerrdialogs --disable-infobars \
        --no-first-run --password-store=basic --disable-background-networking \
        --user-data-dir="$PROFILE" "$URL"
    sleep 2
done
EOF
chmod +x ~/.local/bin/radio-sight-kiosk
```
Here's what the flags do:
- `--kiosk`: full screen, with no address bar and no way out with the mouse.
- `--ozone-platform-hint=auto`: native Wayland under labwc.
- `--noerrdialogs`, `--disable-infobars` and `--no-first-run`: no pop-ups over the page.
- `--password-store=basic`: no keyring prompt after an automatic login.
- `--disable-background-networking`: Chromium doesn't phone home. Nothing leaves our network anyway.

To try it by hand, open a terminal on the Pi's screen and run `~/.local/bin/radio-sight-kiosk`.

If you set the kiosk up before `?src=ws` was added, run this step again. It overwrites the script, and the next boot (or `pkill -f radio-sight-kiosk` and a rerun) picks it up.

## 4. Start it with the desktop
labwc runs `~/.config/labwc/autostart` when the desktop starts.
```sh
mkdir -p ~/.config/labwc
echo '"$HOME/.local/bin/radio-sight-kiosk" &' >> ~/.config/labwc/autostart
sudo reboot
```
After the reboot the page should fill the screen within a few seconds of the board's web server coming up. Until then the desktop stays on screen; that's the script waiting, not a failure.

If you had set a screen rotation or resolution in Screen Configuration and it's gone after this change, add `kanshi &` as the first line of `~/.config/labwc/autostart`. On some images the user autostart file replaces the system one instead of adding to it. Losing the desktop panel the same way doesn't matter, since Chromium covers it.

## Stop it, or update it
- Stop the kiosk (over SSH or from a terminal): `pkill -f radio-sight-kiosk`. It starts again on the next boot.
- Reload after a new web build: `board/push-web.sh` does it for you by closing Chromium, which the script reopens 2 s later. By hand: `pkill -f 'user-data-dir=.*radio-sight-kios[k]'` on the Pi. The server sends `Cache-Control: no-cache`, so the reopened page is always the new build.
- Turn it off for good: delete the `radio-sight-kiosk` line from `~/.config/labwc/autostart`.

## Notes
- A plugged-in mouse leaves its pointer on screen. Unplug it for the demo.
- The Pi's own Wi-Fi is the sensing hotspot, so the Pi never needs the venue Wi-Fi to show the page.
