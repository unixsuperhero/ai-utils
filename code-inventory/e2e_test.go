package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestEndToEnd scans testdata/fixture with the default rules and checks one
// row of each table kind.
func TestEndToEnd(t *testing.T) {
	t.Setenv("GOWORK", "off")
	root, _ := filepath.Abs("testdata/fixture")
	out := t.TempDir()
	cfg, err := parseArgs([]string{root, "--out", out, "--structs", "2"}, os.Stderr)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := run(cfg); err != nil {
		t.Fatal(err)
	}
	read := func(name string) string {
		b, err := os.ReadFile(filepath.Join(out, name))
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	has := func(name string, wants ...string) {
		t.Helper()
		s := read(name)
		for _, w := range wants {
			if !strings.Contains(s, w) {
				t.Errorf("%s: missing %q", name, w)
			}
		}
	}
	const fn = "example.com/fixture."
	has("structs.tsv", "fixture.Server\t6\tserver.go:13\tyes", "fixture.serverJSON\t6\tserver.go:67\tyes", "fixture.Client\t3\tserver.go:22\t\n")
	has("fields.tsv", "fixture.Server\tCount\tint\tserver.go:19\t0\t1\t\t"+fn+"(Server).Run", "fixture.serverJSON\tCount\tint\tserver.go:19\t0\t0\t\t\n")
	has("field_groups.tsv", "4\t2\tAddr string; Name string\tfixture.Client, fixture.Peer, fixture.Server, fixture.serverJSON")
	has("map_sites.tsv", fn+"Decode\tserver.go:55\tmap[string]any\tyes\tm\t\"name\"\tread")
	has("tuple_results.tsv", fn+"Decode\tserver.go:54\t3\tstring, int, error")
	has("string_sites.tsv", fn+"(Server).Key\tserver.go:42\tjoin\t:", fn+"(Server).Parse\tserver.go:44\tsplit\t:")
	has("responsibility_functions.tsv",
		fn+"(Server).Save\tserver.go:37\t4\tserver\treceiver\tpersist=base",
		fn+"(Server).Run\tserver.go:46\t7\tserver\treceiver\tconcurrency=base process=base",
		fn+"NewServer\tserver.go:33\t3\tserver\tfunction\tconfig=base",
		fn+"(Server).View\tserver.go:60\t5\tserver\treceiver\trender=base",
		fn+"Decode\tserver.go:54\t5\tserver\tfile\tother")
	has("test_helpers.tsv", "newTestServer\t1\tserver_test.go:5")
	has("report.md", "| `Test*` functions in `example.com/fixture` reaching a constructor of `fixture.Server` | 1 of 2 (50%); 0 call one directly |",
		"| Path | `"+root+"` |")
}
