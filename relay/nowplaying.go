package main

// Info screens: what is playing, for the SP103 display (docs/api-telas.md).
//
// This bridge is the groove adapter: it reads groove-identity (artist, song, position,
// track on the record), groove-catalog (record tracks, stylus) and the groove-detector
// transport file (AirPlay or Bluetooth playing, and its quality) and translates them into
// the Pico contract, which does not know where the data comes from. The Pico only draws:
// text arrives without accents and truncated, and times are valid at the moment of sending
// (the Pico counts from there).

import (
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	npVersion     = 1
	npFlagPlaying = 1 << 0
	npFlagSideEnd = 1 << 1

	infoPoll    = time.Second
	infoEvery   = 5 * time.Second // even without a change
	stylusEvery = 10 * time.Minute
	sideEndHold = 15 * time.Minute
	// "Side ended" only if the last track was less than this from its end, by the catalog
	// duration. Measured on the Pi 5 on 2026-10-30: Exodus (A5) ended 12 s before the
	// catalog duration; One Love (B5), 5 s after. Chosen with margin over both.
	sideEndNear  = 30 // s
	maxText      = 40
	httpTimeout  = 2 * time.Second
	fieldDivider = "\x1f"
)

// info is what goes in an "NP" packet. Numbers < 0 = unknown (empty field).
type info struct {
	Playing, SideEnd                bool
	Artist, Title, Position, Side   string
	Elapsed, Duration               int
	SideTrack, SideTracks, SideLeft int
	StylusHours, StylusWear         int
	stream
}

// streamSource is the streaming source playing now, as sent in the packet; "" = none.
type streamSource string

const (
	streamNone      streamSource = ""
	streamAirPlay   streamSource = "airplay"
	streamBluetooth streamSource = "bluetooth"
)

// stream is the streaming source playing and its quality (the groove-detector knows Bluetooth's).
type stream struct {
	Source                           streamSource
	Codec                            string
	SampleRateHz, BitDepth, BitrateK int
}

func unknownStream() stream {
	return stream{SampleRateHz: -1, BitDepth: -1, BitrateK: -1}
}

func unknownInfo() info {
	return info{Elapsed: -1, Duration: -1, SideTrack: -1, SideTracks: -1, SideLeft: -1,
		StylusHours: -1, StylusWear: -1, stream: unknownStream()}
}

// packet builds the "NP" datagram (docs/api-telas.md).
func (in info) packet() []byte {
	num := func(v int) string {
		if v < 0 {
			return ""
		}
		return strconv.Itoa(v)
	}
	fields := []string{fold(in.Artist), fold(in.Title), fold(in.Position), num(in.Elapsed), num(in.Duration),
		fold(in.Side), num(in.SideTrack), num(in.SideTracks), num(in.SideLeft),
		num(in.StylusHours), num(in.StylusWear),
		string(in.Source), fold(in.Codec), num(in.SampleRateHz), num(in.BitDepth), num(in.BitrateK)}
	var flags byte
	if in.Playing {
		flags |= npFlagPlaying
	}
	if in.SideEnd {
		flags |= npFlagSideEnd
	}
	return append([]byte{'N', 'P', npVersion, flags}, strings.Join(fields, fieldDivider)...)
}

// sameScreen says whether two readings show the same thing: times advance on their own on the Pico.
func sameScreen(a, b info) bool {
	a.Elapsed, a.SideLeft, b.Elapsed, b.SideLeft = 0, 0, 0, 0
	return a == b
}

var foldTable = map[rune]string{
	'ß': "ss", 'æ': "ae", 'Æ': "AE", 'œ': "oe", 'Œ': "OE", 'ð': "d", 'Ð': "D", 'þ': "th", 'Þ': "Th",
	'‘': "'", '’': "'", '´': "'", '`': "'", '“': "\"", '”': "\"", '–': "-", '—': "-", '…': "...",
	'~': "-", '\\': "/", '·': "-", '×': "x", ' ': " ",
}

func init() {
	for _, group := range []string{"aàáâãäåā", "AÀÁÂÃÄÅĀ", "cçćč", "CÇĆČ", "eèéêëēę", "EÈÉÊËĒĘ", "iìíîïī", "IÌÍÎÏĪ",
		"nñń", "NÑŃ", "oòóôõöøō", "OÒÓÔÕÖØŌ", "uùúûüū", "UÙÚÛÜŪ", "yýÿ", "YÝŸ", "sšś", "SŠŚ", "zžźż", "ZŽŹŻ",
		"lł", "LŁ", "rř", "RŘ", "gğ", "GĞ"} {
		r := []rune(group)
		for _, x := range r[1:] {
			foldTable[x] = string(r[0])
		}
	}
}

// fold reduces the text to what the display ROM has: ASCII from " " to "}", without "\"
// (it shows as "¥" on the display) and truncated to maxText characters. Letters with no
// equivalent become "?".
func fold(s string) string {
	var b strings.Builder
	for _, r := range strings.Join(strings.Fields(s), " ") {
		switch {
		case foldTable[r] != "":
			b.WriteString(foldTable[r])
		case r >= ' ' && r <= '}':
			b.WriteRune(r)
		default:
			b.WriteByte('?')
		}
		if b.Len() >= maxText {
			break
		}
	}
	out := b.String()
	if len(out) > maxText {
		out = out[:maxText]
	}
	return strings.TrimSpace(out)
}

// transportFile is the part of the groove-detector's /tmp/groove-transport.json that
// matters here (its docs/contracts.md, "Streaming transport file").
type transportFile struct {
	Source     string `json:"source"`
	Active     bool   `json:"active"`
	Codec      string `json:"codec"`
	SampleRate string `json:"samplerate"` // "44.1 kHz"
	BitDepth   string `json:"bitdepth"`   // "16 bit"
	Bitrate    string `json:"bitrate"`    // "328 kbps"
}

// readStream reads the transport file. No file, stopped, or a source the contract does
// not know: no streaming.
func readStream(path string) stream {
	st := unknownStream()
	data, err := os.ReadFile(path)
	if err != nil {
		return st
	}
	var tf transportFile
	if json.Unmarshal(data, &tf) != nil || !tf.Active {
		return st
	}
	switch src := streamSource(tf.Source); src {
	case streamAirPlay, streamBluetooth:
		st.Source = src
	default:
		return st
	}
	st.Codec = tf.Codec
	st.SampleRateHz = parseUnit(tf.SampleRate, map[string]float64{"kHz": 1000, "Hz": 1})
	st.BitDepth = parseUnit(tf.BitDepth, map[string]float64{"bit": 1})
	st.BitrateK = parseUnit(tf.Bitrate, map[string]float64{"kbps": 1})
	return st
}

// parseUnit reads "44.1 kHz" with the unit table (kHz → 1000): 44100. -1 if it cannot.
func parseUnit(s string, units map[string]float64) int {
	f := strings.Fields(s)
	if len(f) != 2 {
		return -1
	}
	scale, ok := units[f[1]]
	v, err := strconv.ParseFloat(f[0], 64)
	if !ok || err != nil || v <= 0 {
		return -1
	}
	return int(math.Round(v * scale))
}

// track is a record track in the catalog.
type track struct {
	Position string `json:"track_position"`
	Duration int64  `json:"duration_ms"`
}

// splitPosition splits "A4" into side "A" and number 4. No letter (a CD: "4") = no side.
func splitPosition(pos string) (side string, n int, ok bool) {
	pos = strings.TrimSpace(pos)
	i := 0
	for i < len(pos) && (pos[i] >= 'A' && pos[i] <= 'Z' || pos[i] >= 'a' && pos[i] <= 'z') {
		i++
	}
	n, err := strconv.Atoi(pos[i:])
	if i == 0 || err != nil {
		return "", 0, false
	}
	return strings.ToUpper(pos[:i]), n, true
}

// sideOf computes the side, track on the side, tracks on the side and the time to the
// end of the side (s). left = what remains of the current track. Without the duration of
// any following track, the side time is -1.
func sideOf(tracks []track, pos string, left int) (side string, idx, total, sideLeft int) {
	side, n, ok := splitPosition(pos)
	if !ok {
		return "", -1, -1, -1
	}
	type entry struct {
		n   int
		dur int64
	}
	var same []entry
	for _, t := range tracks {
		if s, tn, ok := splitPosition(t.Position); ok && s == side {
			same = append(same, entry{tn, t.Duration})
		}
	}
	sort.Slice(same, func(a, b int) bool { return same[a].n < same[b].n })
	idx, sideLeft = -1, -1
	if left >= 0 {
		sideLeft = left
	}
	for i, e := range same {
		if e.n == n {
			idx = i + 1
		} else if idx > 0 && sideLeft >= 0 {
			if e.dur <= 0 {
				sideLeft = -1
			} else {
				sideLeft += int(e.dur / 1000)
			}
		}
	}
	if idx < 0 {
		return side, -1, -1, -1
	}
	return side, idx, len(same), sideLeft
}

// identityStatus is the part of groove-identity's GET /status that matters here.
type identityStatus struct {
	Playback struct {
		Active        bool   `json:"active"`
		Epoch         uint64 `json:"epoch"`
		Artist        string `json:"artist"`
		Title         string `json:"title"`
		TrackPosition string `json:"track_position"`
		PositionMs    int64  `json:"position_ms"`
		DurationMs    int64  `json:"duration_ms"`
	} `json:"playback"`
	Recognition struct {
		Epoch uint64 `json:"epoch"`
	} `json:"recognition"`
	AlbumProgramme *struct {
		ReleaseSource string `json:"release_source"`
		ReleaseID     string `json:"release_id"`
	} `json:"album_programme"`
}

type stylusState struct {
	Active  bool `json:"active"`
	Metrics struct {
		Hours float64 `json:"stylus_hours_total"`
		Wear  float64 `json:"wear_percent"`
	} `json:"metrics"`
}

// nowPlaying reads the groove services and keeps what it needs between readings.
type nowPlaying struct {
	identity, catalog, transport string
	client                       *http.Client

	release    string // source/id of the record whose tracks are in tracks
	tracks     []track
	stylus     info // only the stylus fields
	stylusAt   time.Time
	last       info // the previous reading
	sideEndAt  time.Time
	lastWasEnd bool   // the previous reading was the last track of the side, near its end
	endedEpoch uint64 // the capture of the last track of a side that has already ended
}

func newNowPlaying(identity, catalog, transport string) *nowPlaying {
	return &nowPlaying{identity: strings.TrimRight(identity, "/"), catalog: strings.TrimRight(catalog, "/"),
		transport: transport, client: &http.Client{Timeout: httpTimeout}, stylus: unknownInfo(), last: unknownInfo()}
}

func (np *nowPlaying) getJSON(u string, v any) error {
	resp, err := np.client.Get(u)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("%s: %s", u, resp.Status)
	}
	return json.NewDecoder(resp.Body).Decode(v)
}

// read does a full reading. A service that is down only empties its own fields.
func (np *nowPlaying) read(now time.Time) info {
	in := unknownInfo()
	if np.stylusAt.IsZero() || now.Sub(np.stylusAt) >= stylusEvery {
		np.stylusAt = now
		np.stylus = unknownInfo()
		var st stylusState
		if err := np.getJSON(np.catalog+"/catalog/stylus", &st); err != nil {
			log.Printf("stylus: %v", err)
		} else if st.Active {
			np.stylus.StylusHours = int(st.Metrics.Hours + 0.5)
			np.stylus.StylusWear = int(st.Metrics.Wear + 0.5)
		}
	}
	in.StylusHours, in.StylusWear = np.stylus.StylusHours, np.stylus.StylusWear
	in.stream = readStream(np.transport)

	var st identityStatus
	if err := np.getJSON(np.identity+"/status", &st); err != nil {
		log.Printf("identity: %v", err)
		return in
	}
	pb := st.Playback
	// When the music ends, groove-listener sees the end of the track and identity opens a
	// new capture (the run-out groove) before dropping the track it was showing (27 s
	// earlier at 16:03). On the last track of the side, near its end, that new capture is
	// already the end of the side; the track identity keeps showing, with the old capture,
	// no longer counts as playing.
	// Measured on the Pi 5 on 2026-10-30: 15:36:51 and 16:03:12, the day's two side ends.
	if np.lastWasEnd && pb.Epoch != 0 && st.Recognition.Epoch > pb.Epoch {
		np.endedEpoch = pb.Epoch
	}
	if pb.Active && pb.Title != "" && pb.Epoch != np.endedEpoch {
		in.Playing = true
		in.Artist, in.Title, in.Position = pb.Artist, pb.Title, pb.TrackPosition
		left := -1
		if pb.DurationMs > 0 {
			in.Duration = int(pb.DurationMs / 1000)
			in.Elapsed = int(pb.PositionMs / 1000)
			if in.Elapsed > in.Duration {
				in.Elapsed = in.Duration
			}
			left = in.Duration - in.Elapsed
		}
		if p := st.AlbumProgramme; p != nil && p.ReleaseSource != "" && p.ReleaseID != "" {
			np.loadTracks(p.ReleaseSource, p.ReleaseID)
			in.Side, in.SideTrack, in.SideTracks, in.SideLeft = sideOf(np.tracks, pb.TrackPosition, left)
		}
		np.lastWasEnd = in.SideTrack > 0 && in.SideTrack == in.SideTracks && left >= 0 && left <= sideEndNear
		np.sideEndAt, np.endedEpoch = time.Time{}, 0
	} else if np.lastWasEnd || (!np.sideEndAt.IsZero() && now.Sub(np.sideEndAt) < sideEndHold) {
		// The last track of the side ended (new capture or recognition stopped): "Flip the record".
		if np.sideEndAt.IsZero() {
			np.sideEndAt = now
			log.Printf("side %s ended", np.last.Side)
		}
		np.lastWasEnd = false
		in.SideEnd = true
		in.Artist, in.Side, in.SideLeft = np.last.Artist, np.last.Side, 0
		in.SideTracks = np.last.SideTracks
		in.SideTrack = np.last.SideTracks
	}
	if in.Playing {
		np.last = in
	}
	return in
}

// loadTracks fetches the record's tracks once per record.
//
// The list comes from the record's edition (/edition: all tracks, with duration). /tracks
// only has the tracks that have already played and entered the library: on a new record,
// only A1, which then looked like the last on side A and gave a false "End of side A"
// (All Shook Down, 2026-11-07). It stays as a fallback if the edition does not answer.
func (np *nowPlaying) loadTracks(source, id string) {
	key := source + "/" + id
	if key == np.release {
		return
	}
	base := np.catalog + "/catalog/library/releases/" + url.PathEscape(source) + "/" + url.PathEscape(id)
	var ed struct {
		Draft struct {
			Tracklist []struct {
				Position string `json:"position"`
				Duration int64  `json:"duration_ms"`
			} `json:"tracklist"`
		} `json:"draft"`
	}
	err := np.getJSON(base+"/edition", &ed)
	if err == nil && len(ed.Draft.Tracklist) > 0 {
		tracks := make([]track, len(ed.Draft.Tracklist))
		for i, t := range ed.Draft.Tracklist {
			tracks[i] = track{Position: t.Position, Duration: t.Duration}
		}
		np.release, np.tracks = key, tracks
		log.Printf("release %s: %d tracks (edition)", key, len(tracks))
		return
	}
	log.Printf("edition %s: %v (%d tracks); using library tracks", key, err, len(ed.Draft.Tracklist))
	var resp struct {
		Items []track `json:"items"`
	}
	if err := np.getJSON(base+"/tracks", &resp); err != nil {
		log.Printf("tracks %s: %v", key, err)
		np.tracks = nil // try again on the next reading
		return
	}
	// Without the edition the list may be incomplete: do not cache it, read again next time.
	np.tracks = resp.Items
	log.Printf("release %s: %d tracks (library)", key, len(resp.Items))
}

// pumpInfo reads the services every second, only while someone requests the screens, and
// sends the packet when what is shown changes or every infoEvery.
func (r *relay) pumpInfo(np *nowPlaying, conn *net.UDPConn) {
	var sent info
	var sentAt time.Time
	for {
		now := time.Now()
		targets := r.targets(now, maskInfo)
		if len(targets) == 0 {
			sentAt = time.Time{}
			time.Sleep(infoPoll)
			continue
		}
		in := np.read(now)
		if sentAt.IsZero() || !sameScreen(in, sent) || now.Sub(sentAt) >= infoEvery {
			p := in.packet()
			for _, addr := range targets {
				conn.WriteToUDP(p, addr)
			}
			sent, sentAt = in, now
		}
		time.Sleep(infoPoll)
	}
}
