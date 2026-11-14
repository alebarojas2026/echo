# Kiosk on the Pi

The Pi's screen shows the board's web page, http://192.168.77.2:8080/?src=ws, full screen from boot. `?src=ws` makes the screen read the brain's live WebSocket; without it the screen shows its built-in mock states. These steps are for Raspberry Pi OS with desktop (Bookworm or Trixie) running Wayland with labwc, the default on a Pi 5. Do them once, on the Pi, as the user that logs in to the desktop.

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
