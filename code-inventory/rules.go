package main

// The rule tables and the pure classifiers. Everything the report claims
// is derived from these; the report prints the rules it used.

import (
	"encoding/json"
	"fmt"
	"go/types"
	"os"
	"regexp"
	"sort"
	"strings"
	"unicode"
)

// ---------------------------------------------------------------------
// Responsibilities

// Rule tags a function with a responsibility when something it calls, a
// type it names, a construct it uses or its own name matches. Kind says
// what Pattern is matched against:
//
//	pkg    the callee's package path
//	func   "pkgpath.Name" of a package-level callee
//	callee the callee's name (function or method)
//	recv   the callee's receiver type name
//	type   "pkgpath.Name" of a type the function names
//	syntax a construct in the body: go, select, send, recv, make-chan
//	own    the function's own name; with With set, only when the function
//	       also names a type or calls a package function whose
//	       "pkgpath.Name" matches With
//
// Level "base" means the rule matches a standard or third-party library or
// a language construct (the function does the job itself); "named" means a
// naming convention or one of the codebase's own packages. A named match is
// reported as "local" when the callee or type is in the caller's own
// package, "uses" otherwise. "family" is accepted as an old spelling of
// "named".
type Rule struct {
	Tag     string `json:"tag"`
	Level   string `json:"level,omitempty"`
	Kind    string `json:"kind,omitempty"`
	Pattern string `json:"pattern,omitempty"`
	With    string `json:"with,omitempty"`
	Drop    bool   `json:"drop,omitempty"`
	re      *regexp.Regexp
	withRe  *regexp.Regexp
}

// RuleFile is the --rules JSON. Replace drops the default table first.
// Responsibilities, when given, sets the column order (tags not listed are
// appended). A rule with the same tag, kind and pattern as an existing one
// replaces it; with "drop": true it removes it, and a drop with only a tag
// removes every rule of that tag and the tag itself.
type RuleFile struct {
	Replace          bool     `json:"replace,omitempty"`
	Responsibilities []string `json:"responsibilities,omitempty"`
	Rules            []Rule   `json:"rules"`
}

// RuleSet is the merged table in force.
type RuleSet struct {
	Order   []string
	Rules   []Rule
	Sources []string
}

var defaultOrder = []string{"persist", "network", "process", "render", "parse", "concurrency", "config", "history", "notify"}

var defaultRules = []Rule{
	{Tag: "persist", Level: "base", Kind: "pkg", Pattern: `^database/sql(/|$)`},
	{Tag: "persist", Level: "base", Kind: "pkg", Pattern: `^(modernc\.org/sqlite|github\.com/mattn/go-sqlite3|zombiezen\.com/go/sqlite|crawshaw\.io/sqlite|github\.com/ncruces/go-sqlite3)`},
	{Tag: "persist", Level: "base", Kind: "pkg", Pattern: `^(go\.etcd\.io/bbolt|github\.com/boltdb/bolt|github\.com/dgraph-io/badger|github\.com/syndtr/goleveldb|github\.com/cockroachdb/pebble)`},
	{Tag: "persist", Level: "base", Kind: "pkg", Pattern: `^(github\.com/jackc/pgx|github\.com/lib/pq|github\.com/go-sql-driver/mysql|gorm\.io/|github\.com/jmoiron/sqlx|go\.mongodb\.org/|github\.com/redis/go-redis|github\.com/go-redis/redis)`},
	{Tag: "persist", Level: "base", Kind: "func", Pattern: `^os\.(WriteFile|Create|CreateTemp|OpenFile|Rename|Remove|RemoveAll|Mkdir|MkdirAll|MkdirTemp|Truncate|Symlink|Link|Chmod|Chtimes)$`},
	{Tag: "persist", Level: "named", Kind: "recv", Pattern: `(Store|Repo|Repository|DB)$`},
	{Tag: "network", Level: "base", Kind: "pkg", Pattern: `^(net|net/http|net/rpc|net/smtp|crypto/tls)(/|$)`},
	{Tag: "network", Level: "base", Kind: "pkg", Pattern: `^(google\.golang\.org/grpc|github\.com/gorilla/websocket|nhooyr\.io/websocket|github\.com/coder/websocket)`},
	{Tag: "process", Level: "base", Kind: "pkg", Pattern: `^os/exec$`},
	{Tag: "process", Level: "base", Kind: "func", Pattern: `^(os\.(StartProcess|FindProcess)|syscall\.(Exec|Kill|ForkExec|StartProcess))$`},
	{Tag: "process", Level: "base", Kind: "pkg", Pattern: `^github\.com/(creack/pty|charmbracelet/x/(xpty|conpty))`},
	{Tag: "render", Level: "base", Kind: "pkg", Pattern: `^(html/template|text/template)$`},
	{Tag: "render", Level: "base", Kind: "pkg", Pattern: `^(charm\.land/(lipgloss|glamour|bubbletea)|github\.com/charmbracelet/(lipgloss|glamour|bubbletea|x/ansi)|github\.com/muesli/termenv)`},
	{Tag: "render", Level: "base", Kind: "own", Pattern: `^(View|view|Render|render|Draw|draw)`, With: `^(fmt\.Fprint|fmt\.Fprintf|fmt\.Fprintln|io\.WriteString|strings\.Builder)$`},
	{Tag: "render", Level: "named", Kind: "callee", Pattern: `^(View|Render|Draw)$`},
	{Tag: "parse", Level: "base", Kind: "pkg", Pattern: `^(regexp|github\.com/dlclark/regexp2(/v2)?)$`},
	{Tag: "parse", Level: "base", Kind: "pkg", Pattern: `^(encoding(/|$)|text/scanner$|go/(parser|scanner)$)`},
	{Tag: "parse", Level: "base", Kind: "pkg", Pattern: `^(gopkg\.in/yaml|github\.com/BurntSushi/toml|github\.com/pelletier/go-toml|sigs\.k8s\.io/yaml)`},
	{Tag: "parse", Level: "base", Kind: "func", Pattern: `^bufio\.NewScanner$`},
	{Tag: "parse", Level: "base", Kind: "type", Pattern: `^bufio\.Scanner$`},
	{Tag: "parse", Level: "named", Kind: "callee", Pattern: `^(?i:parse|extract|decode|unmarshal)`},
	{Tag: "concurrency", Level: "base", Kind: "pkg", Pattern: `^(sync(/atomic)?|golang\.org/x/sync(/|$))`},
	{Tag: "concurrency", Level: "base", Kind: "syntax", Pattern: `^(go|select|send|recv|make-chan)$`},
	{Tag: "config", Level: "base", Kind: "pkg", Pattern: `^flag$`},
	{Tag: "config", Level: "base", Kind: "func", Pattern: `^os\.(Getenv|LookupEnv|Environ|ExpandEnv|Setenv)$`},
	{Tag: "config", Level: "base", Kind: "pkg", Pattern: `^github\.com/(spf13/(viper|pflag|cobra)|kelseyhightower/envconfig|caarlos0/env|urfave/cli)`},
	{Tag: "history", Level: "named", Kind: "recv", Pattern: `(?i)history|undo`},
	{Tag: "history", Level: "named", Kind: "callee", Pattern: `(?i)undo|redo|history`},
	{Tag: "history", Level: "named", Kind: "type", Pattern: `(?i)\.[A-Za-z]*(history|undo)[A-Za-z]*$`},
	{Tag: "notify", Level: "named", Kind: "callee", Pattern: `(?i)notif|notice|toast`},
	{Tag: "notify", Level: "named", Kind: "recv", Pattern: `(?i)notif|notice`},
}

var ruleKinds = map[string]string{
	"pkg": "callee package path", "func": "package function `pkg.Name`", "callee": "callee name",
	"recv": "callee receiver type", "type": "named type `pkg.Name`", "syntax": "body construct",
	"own": "own name",
}

func (r Rule) key() string { return r.Tag + "\x00" + r.Kind + "\x00" + r.Pattern }

func compile(r *Rule) error {
	if r.Level == "family" {
		r.Level = "named"
	}
	if r.Level == "" {
		r.Level = "base"
	}
	if r.Level != "base" && r.Level != "named" {
		return fmt.Errorf("rule %s/%s: level %q is not base or named", r.Tag, r.Pattern, r.Level)
	}
	if _, ok := ruleKinds[r.Kind]; !ok {
		return fmt.Errorf("rule %s/%s: unknown kind %q", r.Tag, r.Pattern, r.Kind)
	}
	var err error
	if r.re, err = regexp.Compile(r.Pattern); err != nil {
		return fmt.Errorf("rule %s: %w", r.Tag, err)
	}
	if r.With != "" {
		if r.withRe, err = regexp.Compile(r.With); err != nil {
			return fmt.Errorf("rule %s with: %w", r.Tag, err)
		}
	}
	return nil
}

// NewRuleSet starts from the default table and applies each rules file.
func NewRuleSet(files []string) (*RuleSet, error) {
	rs := &RuleSet{Order: append([]string(nil), defaultOrder...), Sources: []string{"default table"}}
	for _, r := range defaultRules {
		if err := compile(&r); err != nil {
			return nil, err
		}
		rs.Rules = append(rs.Rules, r)
	}
	for _, f := range files {
		b, err := os.ReadFile(f)
		if err != nil {
			return nil, err
		}
		var rf RuleFile
		if err := json.Unmarshal(b, &rf); err != nil {
			return nil, fmt.Errorf("%s: %w", f, err)
		}
		if err := rs.Apply(rf); err != nil {
			return nil, fmt.Errorf("%s: %w", f, err)
		}
		rs.Sources = append(rs.Sources, f)
	}
	return rs, nil
}

// Apply merges one rules file into the set.
func (rs *RuleSet) Apply(rf RuleFile) error {
	if rf.Replace {
		rs.Rules, rs.Order = nil, nil
		rs.Sources = nil
	}
	for _, r := range rf.Rules {
		if r.Drop && r.Kind == "" && r.Pattern == "" {
			rs.Rules = filterRules(rs.Rules, func(x Rule) bool { return x.Tag != r.Tag })
			rs.Order = filterStrings(rs.Order, r.Tag)
			continue
		}
		if r.Drop {
			k := r.key()
			rs.Rules = filterRules(rs.Rules, func(x Rule) bool { return x.key() != k })
			continue
		}
		if err := compile(&r); err != nil {
			return err
		}
		replaced := false
		for i := range rs.Rules {
			if rs.Rules[i].key() == r.key() {
				rs.Rules[i] = r
				replaced = true
			}
		}
		if !replaced {
			rs.Rules = append(rs.Rules, r)
		}
	}
	if len(rf.Responsibilities) > 0 {
		order := append([]string(nil), rf.Responsibilities...)
		for _, t := range rs.Order {
			if !contains(order, t) {
				order = append(order, t)
			}
		}
		rs.Order = order
	}
	for _, r := range rs.Rules {
		if !contains(rs.Order, r.Tag) {
			rs.Order = append(rs.Order, r.Tag)
		}
	}
	return nil
}

func filterRules(rs []Rule, keep func(Rule) bool) []Rule {
	var out []Rule
	for _, r := range rs {
		if keep(r) {
			out = append(out, r)
		}
	}
	return out
}

func filterStrings(xs []string, drop string) []string {
	var out []string
	for _, x := range xs {
		if x != drop {
			out = append(out, x)
		}
	}
	return out
}

func contains(xs []string, s string) bool {
	for _, x := range xs {
		if x == s {
			return true
		}
	}
	return false
}

// callee is what the walker knows about one call target.
type callee struct {
	Pkg, Recv, Name string
}

// tagHit is one rule firing; Level is base, local or uses.
type tagHit struct {
	Tag, Level string
}

func levelFor(r Rule, targetPkg, callerPkg string) string {
	if r.Level == "base" {
		return "base"
	}
	if targetPkg == callerPkg {
		return "local"
	}
	return "uses"
}

// TagCallee returns the responsibilities a call to c gives a function in
// package callerPkg.
func (rs *RuleSet) TagCallee(c callee, callerPkg string) []tagHit {
	var out []tagHit
	for _, r := range rs.Rules {
		var s string
		switch r.Kind {
		case "pkg":
			s = c.Pkg
		case "func":
			if c.Recv != "" {
				continue
			}
			s = c.Pkg + "." + c.Name
		case "callee":
			s = c.Name
		case "recv":
			s = c.Recv
		default:
			continue
		}
		if s != "" && r.re.MatchString(s) {
			out = append(out, tagHit{r.Tag, levelFor(r, c.Pkg, callerPkg)})
		}
	}
	return out
}

// TagType returns the responsibilities from naming type pkg.name.
func (rs *RuleSet) TagType(pkg, name, callerPkg string) []tagHit {
	var out []tagHit
	s := pkg + "." + name
	for _, r := range rs.Rules {
		if r.Kind == "type" && r.re.MatchString(s) {
			out = append(out, tagHit{r.Tag, levelFor(r, pkg, callerPkg)})
		}
	}
	return out
}

// TagSyntax returns the responsibilities from a body construct.
func (rs *RuleSet) TagSyntax(construct string) []tagHit {
	var out []tagHit
	for _, r := range rs.Rules {
		if r.Kind == "syntax" && r.re.MatchString(construct) {
			out = append(out, tagHit{r.Tag, "base"})
		}
	}
	return out
}

// TagOwn returns the responsibilities from a function's own name. uses is
// the set of "pkgpath.Name" types it names and package functions it calls;
// a rule with With only fires when one of them matches. It also returns
// what matched With, for the report.
func (rs *RuleSet) TagOwn(name string, uses map[string]bool) ([]tagHit, []string) {
	var out []tagHit
	var via []string
	for _, r := range rs.Rules {
		if r.Kind != "own" || !r.re.MatchString(name) {
			continue
		}
		lvl := "base"
		if r.Level == "named" {
			lvl = "local"
		}
		if r.withRe == nil {
			out = append(out, tagHit{r.Tag, lvl})
			via = append(via, "own name")
			continue
		}
		for _, u := range sortedKeys(uses) {
			if r.withRe.MatchString(u) {
				out = append(out, tagHit{r.Tag, lvl})
				via = append(via, "own name + "+u)
				break
			}
		}
	}
	return out, via
}

// ---------------------------------------------------------------------
// Subjects

// tokens splits an identifier or file stem into lower-case words, with a
// trailing plural "s" removed ("paneDetails" -> pane, detail).
func tokens(s string) []string {
	var words []string
	var cur []rune
	flush := func() {
		if len(cur) > 0 {
			words = append(words, singular(strings.ToLower(string(cur))))
			cur = cur[:0]
		}
	}
	rs := []rune(s)
	for i, r := range rs {
		switch {
		case r == '_' || r == '-' || r == '.' || r == '/' || r == ' ' || r == '*':
			flush()
		case unicode.IsUpper(r):
			// New word at a lower->upper edge, or at the last upper of an
			// acronym followed by lower ("HTTPServer" -> http, server).
			if len(cur) > 0 && (unicode.IsLower(cur[len(cur)-1]) || unicode.IsDigit(cur[len(cur)-1]) ||
				(i+1 < len(rs) && unicode.IsLower(rs[i+1]))) {
				flush()
			}
			cur = append(cur, r)
		default:
			cur = append(cur, r)
		}
	}
	flush()
	return words
}

func singular(w string) string {
	if len(w) > 3 && strings.HasSuffix(w, "s") && !strings.HasSuffix(w, "ss") && !strings.HasSuffix(w, "us") {
		if strings.HasSuffix(w, "ies") {
			return w[:len(w)-3] + "y"
		}
		return w[:len(w)-1]
	}
	return w
}

// vocab is the subject vocabulary: names with their word lists, longest
// first so "context-item" wins over "item".
type vocab struct {
	names []string
	words map[string][]string
}

func newVocab(names []string) vocab {
	v := vocab{words: map[string][]string{}}
	seen := map[string]bool{}
	for _, n := range names {
		w := tokens(n)
		if len(w) == 0 {
			continue
		}
		key := strings.Join(w, "-")
		if seen[key] {
			continue
		}
		seen[key] = true
		v.names = append(v.names, key)
		v.words[key] = w
	}
	sort.Slice(v.names, func(i, j int) bool {
		a, b := v.names[i], v.names[j]
		if len(v.words[a]) != len(v.words[b]) {
			return len(v.words[a]) > len(v.words[b])
		}
		return a < b
	})
	return v
}

// match returns the first name (longest word run first) found as a run of
// consecutive words in ws.
func (v vocab) match(ws []string) string {
	for _, n := range v.names {
		nw := v.words[n]
		for i := 0; i+len(nw) <= len(ws); i++ {
			ok := true
			for j := range nw {
				if ws[i+j] != nw[j] {
					ok = false
					break
				}
			}
			if ok {
				return n
			}
		}
	}
	return ""
}

// subjectOf tries the sources in order (function name, receiver type, file
// stem, package name) and returns the first name found and which source.
// The function name comes first because one large receiver often holds
// methods about many subjects.
func (v vocab) subjectOf(fn, recv, fileStem, pkg string) (string, string) {
	for _, src := range []struct{ from, s string }{{"function", fn}, {"receiver", recv}, {"file", fileStem}, {"package", pkg}} {
		if src.s == "" {
			continue
		}
		if n := v.match(tokens(src.s)); n != "" {
			return n, src.from
		}
	}
	return "(none)", ""
}

// ---------------------------------------------------------------------
// Structure in strings

// strRules classifies string joins and splits on a set of separators.
type strRules struct {
	seps                          []string
	prefixRe, fmtJoinRe, fmtPreRe *regexp.Regexp
}

const verbRe = `%[-+# 0-9.*]*[a-zA-Z]`

func newStrRules(seps []string) *strRules {
	var alts []string
	for _, s := range seps {
		alts = append(alts, regexp.QuoteMeta(s))
	}
	sort.Slice(alts, func(i, j int) bool { return len(alts[i]) > len(alts[j]) })
	alt := "(?:" + strings.Join(alts, "|") + ")"
	return &strRules{
		seps:      seps,
		prefixRe:  regexp.MustCompile(`^[a-z][a-z0-9_.-]*?` + alt + `$`),
		fmtJoinRe: regexp.MustCompile(`(` + verbRe + `)(` + strings.Join(alts, "|") + `)(` + verbRe + `)`),
		fmtPreRe:  regexp.MustCompile(`^([a-z][a-z0-9_.-]*?` + alt + `)` + verbRe),
	}
}

// sepOf returns the separator a prefix ends with (the longest that fits).
func (sr *strRules) sepOf(prefix string) string {
	best := ""
	for _, s := range sr.seps {
		if strings.HasSuffix(prefix, s) && len(s) > len(best) {
			best = s
		}
	}
	return best
}

// strHit is one site that joins or takes apart a structured string. Kind
// is "join" or "split"; Sep is the separator; Prefix the literal word
// prefix ("pane:") when there is one.
type strHit struct {
	Kind, Sep, Prefix, Form string
}

// part is one operand of a string concatenation.
type part struct {
	Const bool
	Val   string
}

// classifyConcat looks at the flattened operands of a + chain.
func (sr *strRules) classifyConcat(ps []part) []strHit {
	var out []strHit
	for i, p := range ps {
		if !p.Const {
			continue
		}
		prevVar := i > 0 && !ps[i-1].Const
		nextVar := i+1 < len(ps) && !ps[i+1].Const
		for _, sep := range sr.seps {
			if p.Val == sep && prevVar && nextVar {
				out = append(out, strHit{"join", sep, "", "concat"})
			}
		}
		if nextVar && sr.prefixRe.MatchString(p.Val) && (i == 0 || !ps[i-1].Const) {
			out = append(out, strHit{"join", sr.sepOf(p.Val), p.Val, "concat"})
		}
	}
	return out
}

// classifyFormat looks at a Sprintf format string.
func (sr *strRules) classifyFormat(f string) []strHit {
	var out []strHit
	for _, m := range sr.fmtJoinRe.FindAllStringSubmatch(f, -1) {
		form := "sprintf"
		if strings.HasSuffix(m[1], "d") && strings.HasSuffix(m[3], "d") {
			form = "sprintf-numeric"
		}
		out = append(out, strHit{"join", m[2], "", form})
	}
	if m := sr.fmtPreRe.FindStringSubmatch(f); m != nil {
		out = append(out, strHit{"join", sr.sepOf(m[1]), m[1], "sprintf"})
	}
	return out
}

var splitFuncs = map[string]bool{
	"strings.Split": true, "strings.SplitN": true, "strings.SplitAfter": true, "strings.SplitAfterN": true,
	"strings.Cut": true, "strings.Index": true, "strings.LastIndex": true, "strings.IndexByte": true,
	"strings.LastIndexByte": true, "strings.Count": true, "strings.IndexRune": true,
}

var prefixFuncs = map[string]bool{
	"strings.HasPrefix": true, "strings.TrimPrefix": true, "strings.CutPrefix": true,
}

// classifyCall looks at a call to pkg.fn with its constant string (or byte
// or rune, as a string) arguments, in order, "" for non-constant ones.
func (sr *strRules) classifyCall(fn string, consts []string) []strHit {
	var out []strHit
	switch {
	case fn == "strings.Join" && len(consts) == 2:
		for _, sep := range sr.seps {
			if consts[1] == sep {
				out = append(out, strHit{"join", sep, "", "strings.Join"})
			}
		}
	case splitFuncs[fn] && len(consts) >= 2:
		for _, sep := range sr.seps {
			if consts[1] == sep {
				out = append(out, strHit{"split", sep, "", fn})
			}
		}
	case prefixFuncs[fn] && len(consts) >= 2:
		if sr.prefixRe.MatchString(consts[1]) {
			out = append(out, strHit{"split", sr.sepOf(consts[1]), consts[1], fn})
		}
	}
	return out
}

// ---------------------------------------------------------------------
// Hand-decoded maps

// stringMap says whether t is a map whose key is a string type, and
// whether its values are an interface (map[string]any and the like).
func stringMap(t types.Type) (ok, iface bool) {
	if t == nil {
		return false, false
	}
	m, isMap := t.Underlying().(*types.Map)
	if !isMap {
		return false, false
	}
	k, isBasic := m.Key().Underlying().(*types.Basic)
	if !isBasic || k.Kind() != types.String {
		return false, false
	}
	_, iface = m.Elem().Underlying().(*types.Interface)
	return true, iface
}

// ---------------------------------------------------------------------
// Clustering

func jaccard(a, b map[string]bool) float64 {
	if len(a) == 0 && len(b) == 0 {
		return 0
	}
	inter := 0
	for k := range a {
		if b[k] {
			inter++
		}
	}
	return float64(inter) / float64(len(a)+len(b)-inter)
}

// completeLinkage clusters items (each with a set) bottom-up: it merges the
// two clusters whose smallest pairwise Jaccard is highest, while that is at
// least threshold. Ties break on the sorted item names, so the result is
// deterministic. It returns clusters of 2+ items, each sorted, with the
// smallest pairwise similarity inside it.
func completeLinkage(names []string, sets map[string]map[string]bool, threshold float64) ([][]string, []float64) {
	names = append([]string(nil), names...)
	sort.Strings(names)
	n := len(names)
	sim := make([][]float64, n)
	for i := range sim {
		sim[i] = make([]float64, n)
		for j := range sim[i] {
			if i != j {
				sim[i][j] = jaccard(sets[names[i]], sets[names[j]])
			}
		}
	}
	clusters := make([][]int, n)
	for i := range clusters {
		clusters[i] = []int{i}
	}
	link := func(a, b []int) float64 {
		m := 2.0
		for _, x := range a {
			for _, y := range b {
				if sim[x][y] < m {
					m = sim[x][y]
				}
			}
		}
		return m
	}
	for {
		bi, bj, best := -1, -1, -1.0
		for i := 0; i < len(clusters); i++ {
			for j := i + 1; j < len(clusters); j++ {
				if s := link(clusters[i], clusters[j]); s > best {
					bi, bj, best = i, j, s
				}
			}
		}
		if bi < 0 || best < threshold {
			break
		}
		clusters[bi] = append(clusters[bi], clusters[bj]...)
		clusters = append(clusters[:bj], clusters[bj+1:]...)
	}
	var out [][]string
	var mins []float64
	for _, c := range clusters {
		if len(c) < 2 {
			continue
		}
		var ns []string
		for _, x := range c {
			ns = append(ns, names[x])
		}
		sort.Strings(ns)
		out = append(out, ns)
		m := 2.0
		for _, x := range c {
			for _, y := range c {
				if x != y && sim[x][y] < m {
					m = sim[x][y]
				}
			}
		}
		mins = append(mins, m)
	}
	return out, mins
}

func sortedKeys[V any](m map[string]V) []string {
	ks := make([]string, 0, len(m))
	for k := range m {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	return ks
}
