package main

import "testing"

// An older running build must be recognised as older so the new build takes
// over; same or newer must be left alone.
func TestVersionLess(t *testing.T) {
	cases := []struct {
		a, b string
		want bool
	}{
		{"0.3.0", "0.4.0", true},
		{"0.4.0", "0.4.0", false},
		{"0.4.1", "0.4.0", false},
		{"0.4", "0.4.0", false},
		{"0.3.9", "0.4.0", true},
		{"0.10.0", "0.9.0", false}, // numeric, not lexical
		{"1.0.0", "0.99.0", false},
		{"", "0.4.0", true}, // no version at all = predates versioned pings
	}
	for _, c := range cases {
		if got := versionLess(c.a, c.b); got != c.want {
			t.Errorf("versionLess(%q,%q)=%v want %v", c.a, c.b, got, c.want)
		}
	}
}
