# VU meter on the amp's display

With the VU meter turned on in the app (Display tab), the display's two lines become the bars for the left (L) and right
(R) channels **while music is playing**. Since 2026-10-29. Visual proposal: <https://claude.ai/artifact/6Zrty8KCsb3ZRsa7Uh2Ax7>.

## Data path

```
groove-detector ──Unix socket──► sp103-vu-relay ──UDP, Wi-Fi──► Pico (vu.py, proxy.py)
 /tmp/groove-vu.sock              (on the board)                  requests every 2 s
 /tmp/groove-gate.json
```

- **groove-detector** (unchanged): publishes each channel's RMS on a Unix socket and says in the gate file whether music is playing
  (`"state": "programme"` or `"idle"`). Format in its `docs/contracts.md`.
- **sp103-vu-relay** (`relay/`, Go): just one more reader of the socket and the gate. Sends each frame over UDP to whoever requested it in the
  last 6 s, up to 4 requests.
- **Pico** (`firmware/vu.py`): with the VU on, requests the frames every 2 s. It computes the bars, the decay, the peak and the clip,
  and `proxy.py` chooses between the VU and the amp's screen.

The detector does not know the SP103 exists, and the Pico only knows the bridge's IP. If the bridge, the detector or the Wi-Fi go down, the
Pico goes back to the amp's screen on its own within 1 s.

### Protocol (UDP, port 7091)

| Message | From → to | Bytes |
|---|---|---|
| Request | Pico → bridge | `SUB1` (4 bytes); valid for 6 s |
| Frame | bridge → Pico | `VU`, `0x01`, flags, float32 L, float32 R (12 bytes, little-endian, RMS 0 to 1) |

Flags: bit 0 = music playing; bit 1 = the gate file was read. Without the gate file, the bridge says "no music".

## What the display shows

1. **VU off** in the app: everything as before. The Pico does not even request the frames.
2. **VU on, with music and frames arriving**: L on line 1, R on line 2. Column 0 = the letter; columns 1 to 15 = the bar,
   5 pixel columns each: 75 steps from floor to top (automatic scale).
3. **The controller drew a screen** (volume, input, menu, power on): the amp's screen appears at once and stays for 3 s after the
   last redraw.
4. **No music, no frames for 1 s, or the amp's display off**: the amp's screen.

The bar rises instantly and, when full, empties in 0.5 s (the decay follows the size of the scale). The peak holds for 1 s and falls
the whole scale in 1 s. Above −1 dBFS, the last cell lights
fully for 1 s (clip). Dots at the bottom of the empty bar mark −30, −20, −10, −6 and −3 dB below the top (only those above
the floor). The clip is always the real one (−1 dBFS), even with the top below 0.

That is the "thin bars" layout. There are four layouts, and each has its own 8 glyphs. In VU mode they take the
place of the amp's bar glyphs; when going back to the amp's screen, the Pico writes the controller's back.

| Layout | Lines | Steps | Glyphs |
|---|---|---|---|
| Thin bars (`bars`) | L and R, one line each, with the letter in column 0 | 75 | 1 to 4 columns, full cell, peak, scale mark, clip (`vu.GLYPHS`) |
| Cassette deck (`deck`) | like the bars, with 2 separate segments per cell; those in the last 3 cells taller (the hot zone). The peak is a lone segment; the clip lights the last cell | 30 | 7 (`vu.DECK_GLYPHS`) |
| Printed scale (`scale`) | L and R on line 1 (L in the top half of each cell, R in the bottom); line 2 is the ruler in dB below the top (`20 10 6 3 0` on the automatic scale). The peak is a lone segment; on clip, the ruler's 0 becomes the ROM's full block | 32 | 8 L/R pairs (`vu.SCALE_GLYPHS`) |
| Yamaha KX-393 (`kx393`) | the deck's meter: L and R on line 1, no letters (L on top, R below), one segment per cell on the deck's scale, from −30 to +8, in 2 dB steps near 0. The deck's 0 sits 10 dB below the top; the segments above it are taller. Line 2 is the ruler `30 17 10 4 0 4 8`. The peak is a lone segment; the clip lights the last one | 16 | 6 (`vu.KX_GLYPHS`) |


## Settings (app, Display tab)

| Field | Default | Range |
|---|---|---|
| VU meter | Disabled | Disabled (off), thin bars, cassette deck, printed scale or Yamaha KX-393 |
| VU source (IP) | empty | the IP of the board running the bridge, required with the VU on; MicroPython does not resolve `.local` names |

The scale is always automatic (below). With "Disabled", the layout chosen before is kept for when the VU comes back.

It lives in the Pico's `names.json`, together with the names (`"vu": {"on", "auto", "layout", "relay"}`; `"auto"` is always true, and the
`"floor"`/`"top"` of an old file is ignored). The line below the fields says
what the VU is doing: "VU on the display now", "waiting for music", "no data from the VU source"...

**Automatic scale (default since 2026-10-29):** the REC OUT level varies a lot with the source. Measured with
music: DAB averaging around −30 dBFS; vinyl (the Rega on the TUNER input) averaging −11 with peaks of −3, on both of the
detector's sockets, so it is not bass noise. With the automatic scale, the top sits 5 dB above the loudest frame: it rises instantly and,
with music, falls 1 dB/s (from vinyl to DAB takes about 24 s). The floor sits 20 dB below the top, as on a needle VU: the
music varies little from one frame to the next (on vinyl, 90 % of frames within a 7 dB range), and with 20 dB the bar stays
between half and 3/4, moving. Without music the top stays put; it ranges from −40 to 0 dB. The app shows the current scale
("scale −26 to −6 dB").

**Manual scale (removed from the page on 2026-11-02):** fixed floor and top, chosen by hand. It went because the automatic one
follows the source on its own; `vu.py` still accepts it (`"auto": false`), but only the tests use it.

**L and R identical:** the USB capture board (GeneralPlus USB Audio Device) is mono: microphone input only, 1 channel
(`/proc/asound/card0/stream0`: `Channels: 1`, `MONO`). The detector repeats the same value on both channels, and the REC
OUT's R is probably not even measured. With a stereo line capture, the VU shows both channels without changing anything on the Pico
or the bridge; only the gain needs recalibrating in the groove-detector.

If the VU errors on the Pico, it turns itself off and the display carries on with the amp's screen; the app shows the error.
Diagnostics at `http://sp103.local/names`, field `vu` (frames received, age of the last one, music).

## Installing the bridge

See [`trocar-de-placa.md`](trocar-de-placa.md). Each board with the groove-detector can have its own; the Pico chooses by IP.

The `sp103-vu-relay` service runs as `nobody`, in the `groove` group (the VU socket is `root:groove 0660`).

## Latency

Estimated, not yet measured: the detector gathers a block of samples before computing (~46 ms), the bridge and Wi-Fi add
5 to 20 ms (sometimes 50 to 100 ms), and the display's liquid crystal takes 100 to 200 ms to change a pixel. The bars
follow the music like a needle VU; a sharp kick drum hit may look slightly late. The Pico's Wi-Fi
power saving is already off (`wifi.py`).

The VU measures REC OUT, which normally comes before the amp's volume control: with the volume low, the bars stay
high.

## Tests

- `python3 tools/test_vu.py`: decay, peak, clip, line drawing, request to the bridge, "only with music" and the settings.
- `python3 tools/test_proxy.py`, part 3: the VU alternates with the amp's screen (3 s after a redraw) and disappears without frames.
- `cd relay && make test`: packet, requests (6 s validity, limit of 4), gate reading and the full path.
- On the network (2026-10-29): the bridge sent ~22 frames/s to the Mac and ~33/s to the Pico.
