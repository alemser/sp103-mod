// Command sp103-vu-relay forwards the groove-detector VU to the SP103 Pico over UDP,
// along with what is playing, for the info screens (nowplaying.go).
//
// The groove-detector publishes the VU on a Unix socket (16 bytes per frame, ~21.5 per
// second: float32 L, float32 R, uint64 sample_index; see its docs/contracts.md) and
// says whether music is playing in the gate file ("state": "programme" or "idle"). The
// Pico is on Wi-Fi and cannot reach either. This bridge is just one more reader of them:
// the detector does not change and does not know the SP103 exists.
//
// Protocol (UDP port 7091):
//
//	Pico   → bridge "SUB1"                      VU-only request; valid for 6 s, the Pico repeats it every 2 s
//	Pico   → bridge "SUB2" mask                 bit 0 = VU, bit 1 = screens (docs/api-screens.md)
//	bridge → Pico   "VU" 0x01 flags L R         12 bytes; L and R float32 little-endian (RMS 0..1)
//	                flags: bit 0 = music playing, bit 1 = the gate was read
//	bridge → Pico   "NP" 0x01 flags fields...   the screens: see docs/api-screens.md
//
// Without a valid request, the bridge sends nothing.
package main

import (
	"encoding/json"
	"flag"
	"io"
	"log"
	"net"
	"os"
	"sync"
	"sync/atomic"
	"time"
)

const (
	frameSize  = 16
	packetSize = 12
	version    = 1
	leaseTTL   = 6 * time.Second
	maxSubs    = 4

	flagProgramme = 1 << 0
	flagGateKnown = 1 << 1

	maskVU   = 1 << 0
	maskInfo = 1 << 1
)

var subscribeMsg = []byte("SUB1")

// parseSubscribe reads a request: "SUB1" (VU only) or "SUB2" + mask. 0 = not a request.
func parseSubscribe(p []byte) byte {
	switch {
	case len(p) == 4 && string(p) == "SUB1":
		return maskVU
	case len(p) == 5 && string(p[:4]) == "SUB2":
		return p[4] & (maskVU | maskInfo)
	}
	return 0
}

type relay struct {
	mu   sync.Mutex
	subs map[string]subscriber

	programme atomic.Bool
	gateKnown atomic.Bool
}

type subscriber struct {
	addr  *net.UDPAddr
	mask  byte
	until time.Time
}

func newRelay() *relay {
	return &relay{subs: map[string]subscriber{}}
}

// subscribe renews addr's request. Returns false if maxSubs requests are already active.
func (r *relay) subscribe(addr *net.UDPAddr, mask byte, now time.Time) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	key := addr.String()
	if _, ok := r.subs[key]; !ok {
		r.expire(now)
		if len(r.subs) >= maxSubs {
			return false
		}
		log.Printf("subscriber %s (mask %d)", key, mask)
	}
	r.subs[key] = subscriber{addr: addr, mask: mask, until: now.Add(leaseTTL)}
	return true
}

// targets returns the still-valid requests that want what the mask says.
func (r *relay) targets(now time.Time, mask byte) []*net.UDPAddr {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.expire(now)
	out := make([]*net.UDPAddr, 0, len(r.subs))
	for _, s := range r.subs {
		if s.mask&mask != 0 {
			out = append(out, s.addr)
		}
	}
	return out
}

func (r *relay) expire(now time.Time) {
	for key, s := range r.subs {
		if now.After(s.until) {
			log.Printf("subscriber %s expired", key)
			delete(r.subs, key)
		}
	}
}

func (r *relay) flags() byte {
	var f byte
	if r.programme.Load() {
		f |= flagProgramme
	}
	if r.gateKnown.Load() {
		f |= flagGateKnown
	}
	return f
}

// packet builds the datagram for the Pico from a detector frame.
func packet(frame []byte, flags byte) []byte {
	p := make([]byte, packetSize)
	p[0], p[1], p[2], p[3] = 'V', 'U', version, flags
	copy(p[4:12], frame[0:8]) // L and R already arrive as float32 little-endian
	return p
}

// readGate reads the "state" from the detector's gate file.
func readGate(path string) (programme, ok bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return false, false
	}
	var g struct {
		State string `json:"state"`
	}
	if json.Unmarshal(data, &g) != nil || (g.State != "programme" && g.State != "idle") {
		return false, false
	}
	return g.State == "programme", true
}

func (r *relay) watchGate(path string, every time.Duration) {
	var last time.Time
	for {
		info, err := os.Stat(path)
		switch {
		case err != nil:
			if r.gateKnown.Swap(false) {
				log.Printf("gate %s: %v", path, err)
			}
			r.programme.Store(false)
			last = time.Time{}
		case !info.ModTime().Equal(last):
			last = info.ModTime()
			programme, ok := readGate(path)
			if ok && programme != r.programme.Load() {
				log.Printf("gate: programme=%v", programme)
			}
			r.programme.Store(programme)
			r.gateKnown.Store(ok)
		}
		time.Sleep(every)
	}
}

func (r *relay) serveSubscriptions(conn *net.UDPConn) {
	buf := make([]byte, 64)
	for {
		n, addr, err := conn.ReadFromUDP(buf)
		if err != nil {
			log.Printf("udp read: %v", err)
			time.Sleep(time.Second)
			continue
		}
		if mask := parseSubscribe(buf[:n]); mask != 0 {
			if !r.subscribe(addr, mask, time.Now()) {
				log.Printf("subscriber %s refused: %d already", addr, maxSubs)
			}
		}
	}
}

func (r *relay) pumpVU(sockPath string, conn *net.UDPConn) {
	frame := make([]byte, frameSize)
	for {
		c, err := net.Dial("unix", sockPath)
		if err != nil {
			log.Printf("vu socket: %v (retrying)", err)
			time.Sleep(2 * time.Second)
			continue
		}
		log.Printf("vu socket %s connected", sockPath)
		for {
			if _, err = io.ReadFull(c, frame); err != nil {
				break
			}
			targets := r.targets(time.Now(), maskVU)
			if len(targets) == 0 {
				continue
			}
			p := packet(frame, r.flags())
			for _, addr := range targets {
				conn.WriteToUDP(p, addr) // UDP: a lost frame does not matter
			}
		}
		c.Close()
		log.Printf("vu socket closed: %v (reconnecting)", err)
		time.Sleep(time.Second)
	}
}

func main() {
	listen := flag.String("listen", ":7091", "UDP address for the Pico's requests")
	vuSock := flag.String("vu", "/tmp/groove-vu.sock", "groove-detector VU socket")
	gate := flag.String("gate", "/tmp/groove-gate.json", "groove-detector gate file")
	identity := flag.String("identity", "http://127.0.0.1:7071", "groove-identity (what is playing)")
	catalog := flag.String("catalog", "http://127.0.0.1:7073", "groove-catalog (record tracks and stylus)")
	transport := flag.String("transport", "/tmp/groove-transport.json", "groove-detector transport file (AirPlay, Bluetooth)")
	flag.Parse()

	addr, err := net.ResolveUDPAddr("udp", *listen)
	if err != nil {
		log.Fatal(err)
	}
	conn, err := net.ListenUDP("udp", addr)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("sp103-vu-relay on udp %s, vu %s, gate %s, identity %s, catalog %s, transport %s",
		*listen, *vuSock, *gate, *identity, *catalog, *transport)

	r := newRelay()
	go r.watchGate(*gate, 500*time.Millisecond)
	go r.serveSubscriptions(conn)
	go r.pumpInfo(newNowPlaying(*identity, *catalog, *transport), conn)
	r.pumpVU(*vuSock, conn)
}
