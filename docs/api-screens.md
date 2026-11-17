# Info screens contract (source → Pico)

The SP103 Pico can show on the display the stylus hours and wear (on the turntable inputs) and the Bluetooth
quality (on the DAB input). It does not know where this data comes from: it only knows this contract.

Since 2026-11-07 the Pico no longer shows artist and song, track and position, side time or the end-of-side notice
(`firmware/screens.py`). The fields stay in the contract and the source keeps sending them: the Pico reads and ignores them. Anyone
who wants to show them again does not need to change the packet. Whatever speaks this contract is a
**source**. Today's source is `sp103-vu-relay`, which reads groove-identity and groove-catalog
(`relay/nowplaying.go`); another source (Volumio, Home Assistant) only needs to send the same packets.

Everything goes over UDP, on the source's port **7091**, the same as the VU (`docs/vu.md`).

## Request (Pico → source)

| Packet | Bytes | What |
|---|---|---|
| `"SUB1"` | 4 | VU only (the old format; still valid) |
| `"SUB2"` + mask | 5 | Mask: bit 0 = VU, bit 1 = screens |

A request is valid for 6 s; the Pico repeats it every 2 s. Without a valid request, the source sends nothing. A source that only has the screens
ignores bit 0, and one that only has the VU ignores bit 1.

## Screens (source → Pico)

```
"NP" version(1) flags  field 0x1F field 0x1F ... field
```

- `version` = 1. The Pico ignores packets of any other version.
- `flags`: bit 0 = playing now (the Pico shows the stylus when the record starts playing); bit 1 = the side ended
  (the Pico ignores it). It is a fact: the source repeats it while it holds.
- The fields always come in this order, separated by the byte 0x1F. **Empty field = unknown**: the screen that depends on it
  does not appear, and the others carry on.
- Text in ASCII only, from `" "` to `"}"`, without `"\"` (the display ROM has no accented letters; in it `"\"` shows as `"¥"` and `"~"` as an
  arrow). The source strips accents (`ã` → `a`) and truncates each text to 40 characters.
- Numbers are decimal integers.

| # | Field | Example | Screen |
|---|---|---|---|
| 0 | artist | `Pink Floyd` | (ignored) |
| 1 | song | `Time` | (ignored) |
| 2 | track on the record | `A4` | (ignored) |
| 3 | position in the track (s) | `161` | (ignored) |
| 4 | track duration (s) | `421` | (ignored) |
| 5 | side | `A` | (ignored) |
| 6 | track on the side | `4` | (ignored) |
| 7 | tracks on the side | `5` | (ignored) |
| 8 | time to the end of the side (s) | `608` | (ignored) |
| 9 | stylus hours | `312` | Stylus |
| 10 | stylus wear (%) | `62` | Stylus |
| 11 | streaming playing: `airplay` or `bluetooth` (empty = none) | `bluetooth` | DAB input name, Bluetooth quality |
| 12 | streaming codec | `SBC` | Bluetooth quality |
| 13 | sample rate (Hz) | `44100` | Bluetooth quality |
| 14 | bits per sample | `16` | Bluetooth quality |
| 15 | bitrate (kbit/s) | `328` | Bluetooth quality |

A packet is about 60 to 150 bytes. Extra fields at the end are ignored (for future versions with new fields).

### When to send

- When any field or flag changes (new track, side ended, stylus).
- Every 5 s while there is a request, even without a change.

The positions and the side time are valid **at the moment of sending**.

With no packet for 15 s, the Pico discards the data and goes back to the amp's screen.

## Today's source: sp103-vu-relay

| Field | Where it comes from |
|---|---|
| artist, song, track on the record, position, duration | groove-identity `GET /status` → `playback` (`artist`, `title`, `track_position`, `position_ms`, `duration_ms`), every 1 s |
| side, track on the side, side time | the letter of `track_position` and the record's track list: `album_programme.release_source` / `release_id` → groove-catalog `GET /catalog/library/releases/{source}/{id}/edition` (`draft.tracklist`: `position`, `duration_ms`), once per record. If the edition fails, it uses `.../tracks`, which only has the tracks that have already played, and reads again next time |
| stylus | groove-catalog `GET /catalog/stylus` → `metrics.stylus_hours_total`, `metrics.wear_percent`, every 10 min; empty if `active` is false |
| streaming, codec, sample rate, bits, bitrate | the groove-detector transport file, `/tmp/groove-transport.json` (`source`, `active`, `codec`, `samplerate`, `bitdepth`, `bitrate`), every 1 s; empty with no file or with `active` false. The bitrate only exists on Bluetooth with SBC, AAC or aptX |
| side ended | on the last track of the side, less than 30 s from its end by the catalog duration, identity opened a new capture (`recognition.epoch` > `playback.epoch`: the listener saw the music end) or stopped (`playback.active` false); holds until the next track or 15 min |

The addresses of the two services and the file are bridge options (`-identity`, `-catalog`, default `127.0.0.1`;
`-transport`, default `/tmp/groove-transport.json`).
