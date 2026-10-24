package main

import "testing"

func asNet(h hostStanding) DiscoveredNet {
	return DiscoveredNet{HubID: h.ID, Name: "net-" + h.ID, Address: "10.0.0.9:7480",
		AutoJoin: true, Invite: "CODE", Chosen: h.Chosen, Members: h.Members, Since: h.Since}
}

// With N open hosts that can each see all the others, exactly one — the
// top-ranked — keeps hosting and every other host merges directly into it.
// This is the convergence rule behind open-pool merging; on real separate
// machines each host binds its own discovery port, so each really does see all
// the others and this rule leaves the network with a single pool.
func TestPickMergeTargetConverges(t *testing.T) {
	hosts := []hostStanding{
		{ID: "77", Members: 1, Since: 500},
		{ID: "11", Members: 3, Since: 900},               // most online, but elected
		{ID: "aa", Members: 1, Since: 100},               // up longest among elected
		{ID: "33", Chosen: true, Members: 1, Since: 800}, // chosen by a person: wins
		{ID: "ff", Chosen: true, Members: 1, Since: 950}, // chosen too, but newer
		{ID: "02", Members: 2, Since: 50},
	}
	const winner = "33"
	stayed := 0
	for _, me := range hosts {
		var nets []DiscoveredNet
		for _, other := range hosts {
			n := asNet(other)
			n.SameApp = other.ID == me.ID
			nets = append(nets, n)
		}
		tgt := pickMergeTarget(me, nets)
		if me.ID == winner {
			if tgt != nil {
				t.Fatalf("top host %s should keep hosting, got merge into %s", me.ID, tgt.HubID)
			}
			stayed++
			continue
		}
		if tgt == nil {
			t.Fatalf("host %s should merge but kept hosting", me.ID)
		}
		if tgt.HubID != winner {
			t.Fatalf("host %s merged into %s, want top host %s", me.ID, tgt.HubID, winner)
		}
	}
	if stayed != 1 {
		t.Fatalf("want exactly one host remaining, got %d", stayed)
	}
}

// The ranking itself: chosen beats elected; then more online; then up longer;
// then the smaller id — and it's a strict order, never true both ways.
func TestOutranks(t *testing.T) {
	chosen := hostStanding{ID: "z", Chosen: true, Members: 1, Since: 900}
	busy := hostStanding{ID: "y", Members: 5, Since: 900}
	older := hostStanding{ID: "x", Members: 1, Since: 100}
	newer := hostStanding{ID: "w", Members: 1, Since: 500}
	twin := hostStanding{ID: "a", Members: 1, Since: 500}
	cases := []struct {
		a, b hostStanding
		want bool
		why  string
	}{
		{chosen, busy, true, "chosen beats a busier elected host"},
		{busy, chosen, false, "…and not the other way"},
		{busy, older, true, "more online beats longer uptime"},
		{older, newer, true, "up longer wins a members tie"},
		{twin, newer, true, "smaller id breaks a full tie"},
		{newer, twin, false, "…and not the other way"},
	}
	for _, c := range cases {
		if got := outranks(c.a, c.b); got != c.want {
			t.Errorf("%s: outranks(%s,%s)=%v want %v", c.why, c.a.ID, c.b.ID, got, c.want)
		}
	}
}

// We never merge into a closed host (no auto-join / no code), into ourselves,
// or into a host we outrank.
func TestPickMergeTargetIgnoresClosedLowerAndSelf(t *testing.T) {
	me := hostStanding{ID: "50", Members: 2, Since: 500}
	nets := []DiscoveredNet{
		{HubID: "10", AutoJoin: false, Invite: "", Chosen: true, Members: 9},  // closed: never a merge target
		{HubID: "20", AutoJoin: true, Invite: "", Chosen: true, Members: 9},   // open but advertised no code
		{HubID: "50", AutoJoin: true, Invite: "C", SameApp: true, Members: 2}, // ourselves
		{HubID: "90", AutoJoin: true, Invite: "C", Members: 1, Since: 100},    // fewer online: we outrank it
	}
	if tgt := pickMergeTarget(me, nets); tgt != nil {
		t.Fatalf("should keep hosting, got merge into %s", tgt.HubID)
	}
}
