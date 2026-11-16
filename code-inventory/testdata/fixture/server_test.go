package fixture

import "testing"

func newTestServer() *Server { return NewServer("t") }

func TestKey(t *testing.T) {
	if newTestServer().Key("a", "b") != "a:b" {
		t.Fatal("key")
	}
}

func TestDecode(t *testing.T) {
	if n, _, _ := Decode(map[string]any{"name": "x"}); n != "x" {
		t.Fatal("decode")
	}
}
