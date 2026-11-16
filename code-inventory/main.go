// code-inventory maps a Go codebase's unnamed data, largest structs and
// duplicated responsibilities, and writes report.md plus one TSV per table.
// It only reads the code it scans.
//
// Usage:
//
//	code-inventory PATH [--packages ./...] [--out DIR] [--structs N]
//	    [--struct NAME]... [--rules FILE]... [flags]
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type listFlag []string

func (l *listFlag) String() string     { return strings.Join(*l, ",") }
func (l *listFlag) Set(s string) error { *l = append(*l, s); return nil }

// config is everything a run depends on; the report prints it.
type config struct {
	Root       string
	Patterns   []string
	Out        string
	Structs    int
	Named      []string
	RuleFiles  []string
	Cluster    float64
	ClusterLow float64
	Pair       float64
	Seps       []string
	Long       int
	Top        int
	Results    int
	Params     int
	Link       string
	Tests      bool
}

func main() {
	cfg, err := parseArgs(os.Args[1:], os.Stderr)
	if err != nil {
		if err != flag.ErrHelp {
			fmt.Fprintln(os.Stderr, "code-inventory:", err)
		}
		os.Exit(2)
	}
	res, err := run(cfg)
	if err != nil {
		fmt.Fprintln(os.Stderr, "code-inventory:", err)
		os.Exit(1)
	}
	fmt.Printf("wrote %s in %s\n", filepath.Join(cfg.Out, "report.md"), res.Elapsed.Round(time.Millisecond))
	for _, s := range res.Timings {
		fmt.Println("  " + s)
	}
}

func parseArgs(args []string, stderr io.Writer) (*config, error) {
	fs := flag.NewFlagSet("code-inventory", flag.ContinueOnError)
	fs.SetOutput(stderr)
	var named, rules listFlag
	pkgs := fs.String("packages", "./...", "package patterns, space or comma separated, relative to PATH")
	out := fs.String("out", "", "output directory (default $TMPDIR/code-inventory/<base of PATH>)")
	structs := fs.Int("structs", 5, "how many of the largest structs (by field count) to map field by field")
	fs.Var(&named, "struct", "also map this struct: Name, pkg.Name or import/path.Name (repeatable)")
	fs.Var(&rules, "rules", "JSON rules file that adds, overrides or replaces responsibility rules (repeatable)")
	cluster := fs.Float64("cluster", 0.5, "field clusters: every pair has reader Jaccard >= this")
	clusterLow := fs.Float64("cluster-low", 0.3, "second, looser clustering pass")
	pair := fs.Float64("pair", 0.5, "field pairs listed in field_pairs.tsv have Jaccard >= this")
	seps := fs.String("seps", "/,:", "id separators for structure-in-strings, comma separated")
	long := fs.Int("long", 100, "functions this many lines or more are listed as long")
	top := fs.Int("top", 20, "rows per table in report.md (TSVs are complete)")
	results := fs.Int("results", 3, "functions returning this many values or more are tuples")
	params := fs.Int("params", 4, "parameter lists this long or more are compared for recurrence")
	link := fs.String("link", "", "path prefix for file links in the report (default PATH)")
	tests := fs.Bool("tests", true, "count tests that reach the largest struct's constructor")
	fs.Usage = func() {
		fmt.Fprintln(stderr, "usage: code-inventory PATH [flags]")
		fs.PrintDefaults()
	}
	var pos []string
	for {
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if fs.NArg() == 0 {
			break
		}
		pos = append(pos, fs.Arg(0))
		args = fs.Args()[1:]
	}
	if len(pos) != 1 {
		fs.Usage()
		return nil, fmt.Errorf("want exactly one PATH, got %d", len(pos))
	}
	root, err := filepath.Abs(pos[0])
	if err != nil {
		return nil, err
	}
	if st, err := os.Stat(root); err != nil || !st.IsDir() {
		return nil, fmt.Errorf("%s is not a directory", root)
	}
	cfg := &config{
		Root: root, Patterns: splitList(*pkgs), Out: *out, Structs: *structs, Named: named, RuleFiles: rules,
		Cluster: *cluster, ClusterLow: *clusterLow, Pair: *pair, Seps: splitComma(*seps),
		Long: *long, Top: *top, Results: *results, Params: *params, Link: *link, Tests: *tests,
	}
	if cfg.Out == "" {
		cfg.Out = filepath.Join(os.TempDir(), "code-inventory", filepath.Base(root))
	}
	if cfg.Link == "" {
		cfg.Link = root
	}
	if len(cfg.Patterns) == 0 {
		cfg.Patterns = []string{"./..."}
	}
	return cfg, nil
}

func splitList(s string) []string {
	return strings.FieldsFunc(s, func(r rune) bool { return r == ',' || r == ' ' || r == '\t' })
}

func splitComma(s string) []string {
	var out []string
	for _, x := range strings.Split(s, ",") {
		if x != "" {
			out = append(out, x)
		}
	}
	return out
}

// gitHead describes the commit at dir, or says it is not a repository.
func gitHead(dir string) string {
	out, err := exec.Command("git", "-C", dir, "log", "-1", "--format=%h %s").Output()
	if err != nil {
		return "not a git repository (or no commits)"
	}
	s := strings.TrimSpace(string(out))
	if st, err := exec.Command("git", "-C", dir, "status", "--porcelain", "--untracked-files=no").Output(); err == nil && len(strings.TrimSpace(string(st))) > 0 {
		s += " (with uncommitted changes)"
	}
	return s
}
