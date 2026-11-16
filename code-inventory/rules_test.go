package main

import (
	"go/types"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func ruleSet(t *testing.T, rules ...Rule) *RuleSet {
	t.Helper()
	rs := &RuleSet{}
	if err := rs.Apply(RuleFile{Replace: true, Rules: rules}); err != nil {
		t.Fatal(err)
	}
	return rs
}

func TestRuleKinds(t *testing.T) {
	rs := ruleSet(t,
		Rule{Tag: "pkg", Kind: "pkg", Pattern: `^database/sql$`},
		Rule{Tag: "func", Kind: "func", Pattern: `^os\.WriteFile$`},
		Rule{Tag: "callee", Level: "named", Kind: "callee", Pattern: `(?i)^undo`},
		Rule{Tag: "recv", Level: "named", Kind: "recv", Pattern: `Store$`},
		Rule{Tag: "type", Kind: "type", Pattern: `^bufio\.Scanner$`},
		Rule{Tag: "syntax", Kind: "syntax", Pattern: `^go$`},
		Rule{Tag: "own", Kind: "own", Pattern: `^View`, With: `^strings\.Builder$`},
		Rule{Tag: "bare", Level: "named", Kind: "own", Pattern: `^Notify`},
	)
	cases := []struct {
		name string
		got  []tagHit
		want []tagHit
	}{
		{"pkg", rs.TagCallee(callee{Pkg: "database/sql", Recv: "DB", Name: "Exec"}, "app"), []tagHit{{"pkg", "base"}}},
		{"func", rs.TagCallee(callee{Pkg: "os", Name: "WriteFile"}, "app"), []tagHit{{"func", "base"}}},
		{"func skips methods", rs.TagCallee(callee{Pkg: "os", Recv: "File", Name: "WriteFile"}, "app"), nil},
		{"callee uses", rs.TagCallee(callee{Pkg: "hist", Name: "UndoLast"}, "app"), []tagHit{{"callee", "uses"}}},
		{"callee local", rs.TagCallee(callee{Pkg: "app", Name: "undo"}, "app"), []tagHit{{"callee", "local"}}},
		{"recv", rs.TagCallee(callee{Pkg: "db", Recv: "UserStore", Name: "Get"}, "app"), []tagHit{{"recv", "uses"}}},
		{"type", rs.TagType("bufio", "Scanner", "app"), []tagHit{{"type", "base"}}},
		{"syntax", rs.TagSyntax("go"), []tagHit{{"syntax", "base"}}},
		{"syntax other", rs.TagSyntax("select"), nil},
	}
	for _, c := range cases {
		if !reflect.DeepEqual(c.got, c.want) {
			t.Errorf("%s: got %v, want %v", c.name, c.got, c.want)
		}
	}
	if got, _ := rs.TagOwn("ViewList", map[string]bool{"fmt.Sprintf": true}); got != nil {
		t.Errorf("own without With match: %v", got)
	}
	got, via := rs.TagOwn("ViewList", map[string]bool{"strings.Builder": true})
	if !reflect.DeepEqual(got, []tagHit{{"own", "base"}}) || via[0] != "own name + strings.Builder" {
		t.Errorf("own with With match: %v %v", got, via)
	}
	if got, _ := rs.TagOwn("NotifyAll", nil); !reflect.DeepEqual(got, []tagHit{{"bare", "local"}}) {
		t.Errorf("own without With: %v", got)
	}
}

func TestRulesFileMerge(t *testing.T) {
	dir := t.TempDir()
	f := filepath.Join(dir, "r.json")
	os.WriteFile(f, []byte(`{"responsibilities": ["keys"], "rules": [
		{"tag": "keys", "level": "family", "kind": "callee", "pattern": "(?i)binding"},
		{"tag": "persist", "level": "named", "kind": "recv", "pattern": "(Store|Repo|Repository|DB)$"},
		{"tag": "network", "kind": "pkg", "pattern": "^(net|net/http|net/rpc|net/smtp|crypto/tls)(/|$)", "drop": true},
		{"tag": "notify", "drop": true}
	]}`), 0o644)
	rs, err := NewRuleSet([]string{f})
	if err != nil {
		t.Fatal(err)
	}
	if rs.Order[0] != "keys" || contains(rs.Order, "notify") || !contains(rs.Order, "network") {
		t.Errorf("order: %v", rs.Order)
	}
	n := 0
	for _, r := range rs.Rules {
		if r.Tag == "notify" || (r.Tag == "network" && r.Pattern == `^(net|net/http|net/rpc|net/smtp|crypto/tls)(/|$)`) {
			t.Errorf("dropped rule kept: %+v", r)
		}
		if r.Tag == "keys" && r.Level != "named" {
			t.Errorf("family not read as named: %+v", r)
		}
		if r.Tag == "persist" && r.Kind == "recv" {
			n++
		}
	}
	if n != 1 {
		t.Errorf("same tag/kind/pattern should replace, got %d rows", n)
	}
	if len(rs.Rules) != len(defaultRules)+1-1-2 {
		t.Errorf("rule count %d", len(rs.Rules))
	}
}

func TestStringRules(t *testing.T) {
	sr := newStrRules([]string{"::", "|"})
	if got := sr.classifyConcat([]part{{false, ""}, {true, "::"}, {false, ""}}); len(got) != 1 || got[0].Sep != "::" {
		t.Errorf("concat join: %v", got)
	}
	if got := sr.classifyConcat([]part{{true, "pane|"}, {false, ""}}); len(got) != 1 || got[0].Prefix != "pane|" || got[0].Sep != "|" {
		t.Errorf("concat prefix: %v", got)
	}
	if got := sr.classifyConcat([]part{{false, ""}, {true, "/"}, {false, ""}}); got != nil {
		t.Errorf("unlisted separator matched: %v", got)
	}
	if got := sr.classifyFormat("%d::%d"); len(got) != 1 || got[0].Form != "sprintf-numeric" {
		t.Errorf("format: %v", got)
	}
	if got := sr.classifyCall("strings.Split", []string{"", "|"}); len(got) != 1 || got[0].Kind != "split" {
		t.Errorf("split: %v", got)
	}
	if got := sr.classifyCall("strings.TrimPrefix", []string{"", "task::"}); len(got) != 1 || got[0].Prefix != "task::" {
		t.Errorf("prefix split: %v", got)
	}
}

func TestStringMap(t *testing.T) {
	str := types.Typ[types.String]
	anyT := types.NewInterfaceType(nil, nil)
	if ok, iface := stringMap(types.NewMap(str, anyT)); !ok || !iface {
		t.Error("map[string]any")
	}
	if ok, iface := stringMap(types.NewMap(str, types.Typ[types.Int])); !ok || iface {
		t.Error("map[string]int")
	}
	if ok, _ := stringMap(types.NewMap(types.Typ[types.Int], anyT)); ok {
		t.Error("map[int]any")
	}
}

func TestClustersAndSubjects(t *testing.T) {
	sets := map[string]map[string]bool{
		"a": {"f": true, "g": true}, "b": {"f": true, "g": true}, "c": {"h": true},
	}
	cs, mins := completeLinkage([]string{"c", "b", "a"}, sets, 0.5)
	if !reflect.DeepEqual(cs, [][]string{{"a", "b"}}) || mins[0] != 1 {
		t.Errorf("clusters %v %v", cs, mins)
	}
	v := newVocab([]string{"Item", "ContextItem", "HTTPServer"})
	if s, from := v.subjectOf("loadContextItems", "App", "app", "main"); s != "context-item" || from != "function" {
		t.Errorf("subject %s from %s", s, from)
	}
	if s, from := v.subjectOf("Run", "HTTPServer", "x", "y"); s != "http-server" || from != "receiver" {
		t.Errorf("subject %s from %s", s, from)
	}
}
