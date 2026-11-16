package main

// Tests that construct the largest struct: a reference graph over the
// struct's package and its tests, and reverse reachability from its
// constructors.

import (
	"go/ast"
	"go/types"
	"regexp"
	"sort"
	"strings"

	"golang.org/x/tools/go/packages"
)

type testFacts struct {
	Struct       string
	Pkg          string
	Constructors []string
	Tests        int
	Direct       int
	Reach        int
	Helpers      []helperRec // test-file functions returning the struct
	Err          string
	NoCtor       bool     // no New* returns the struct
	Skipped      []string // larger mapped structs with no constructor
}

type helperRec struct {
	Name, File string
	Line, Refs int
}

var testNameRe = regexp.MustCompile(`^Test([A-Z0-9_]|$)`)

// funcKey names a function the same way in a package and its test variant.
func funcKey(f *types.Func) string { return f.Origin().FullName() }

// isStruct says whether t is the target struct or a pointer to it.
func isStruct(t types.Type, target *structRec) bool {
	if pt, ok := t.(*types.Pointer); ok {
		t = pt.Elem()
	}
	nt, ok := t.(*types.Named)
	return ok && nt.Obj().Name() == target.Name && nt.Obj().Pkg() != nil && nt.Obj().Pkg().Path() == target.PkgPath
}

func returns(sig *types.Signature, target *structRec) bool {
	for i := 0; i < sig.Results().Len(); i++ {
		if isStruct(sig.Results().At(i).Type(), target) {
			return true
		}
	}
	return false
}

// measureTests loads the target's package with its tests (internal and
// external) and builds a reference graph over their functions: an edge from
// f to g when f's body names g (a call or a function value). A constructor
// is a package-level non-test function named New* that returns the struct
// or a pointer to it. A test reaches the struct when a constructor is
// reachable from it.
func measureTests(root string, target *structRec) testFacts {
	facts := testFacts{Struct: target.Label, Pkg: target.PkgPath}
	cfg := loadConfig(root, true)
	pkgs, err := packages.Load(cfg, target.PkgPath)
	if err != nil {
		facts.Err = err.Error()
		return facts
	}
	own := func(p *types.Package) bool {
		return p != nil && (p.Path() == target.PkgPath || p.Path() == target.PkgPath+"_test")
	}
	edges := map[string]map[string]bool{}
	tests := map[string]bool{}
	ctors := map[string]bool{}
	refs := map[string]int{}
	helpers := map[string]helperRec{}
	for _, p := range pkgs {
		if p.TypesInfo == nil || !own(p.Types) {
			continue
		}
		info := p.TypesInfo
		for _, f := range p.Syntax {
			name := cfg.Fset.File(f.Pos()).Name()
			isTest := strings.HasSuffix(name, "_test.go")
			for _, d := range f.Decls {
				fd, ok := d.(*ast.FuncDecl)
				if !ok || fd.Body == nil {
					continue
				}
				obj, ok := info.Defs[fd.Name].(*types.Func)
				if !ok {
					continue
				}
				key := funcKey(obj)
				sig := obj.Type().(*types.Signature)
				if !isTest && fd.Recv == nil && strings.HasPrefix(fd.Name.Name, "New") && returns(sig, target) {
					ctors[key] = true
				}
				if isTest && fd.Recv == nil && testNameRe.MatchString(fd.Name.Name) && sig.Params().Len() == 1 &&
					types.TypeString(sig.Params().At(0).Type(), nil) == "*testing.T" {
					tests[key] = true
				}
				if isTest && returns(sig, target) {
					helpers[key] = helperRec{Name: fd.Name.Name, File: strings.TrimPrefix(name, root+"/"), Line: cfg.Fset.Position(fd.Pos()).Line}
				}
				if edges[key] != nil && !isTest {
					continue // the same function seen in the package and its test variant
				}
				out := map[string]bool{}
				ast.Inspect(fd.Body, func(n ast.Node) bool {
					if id, ok := n.(*ast.Ident); ok {
						if g, ok := info.Uses[id].(*types.Func); ok && own(g.Pkg()) {
							out[funcKey(g)] = true
							refs[funcKey(g)]++
						}
					}
					return true
				})
				edges[key] = out
			}
		}
	}
	for k := range ctors {
		facts.Constructors = append(facts.Constructors, k)
	}
	sort.Strings(facts.Constructors)
	if len(ctors) == 0 {
		facts.Err = "no New* function in " + target.PkgPath + " returns " + target.Name
		facts.NoCtor = true
		return facts
	}
	yes := map[string]bool{}
	for k := range ctors {
		yes[k] = true
	}
	for changed := true; changed; {
		changed = false
		for f, out := range edges {
			if yes[f] {
				continue
			}
			for g := range out {
				if yes[g] {
					yes[f] = true
					changed = true
					break
				}
			}
		}
	}
	facts.Tests = len(tests)
	for t := range tests {
		for c := range ctors {
			if edges[t][c] {
				facts.Direct++
				break
			}
		}
		if yes[t] {
			facts.Reach++
		}
	}
	for k, h := range helpers {
		h.Refs = refs[k]
		facts.Helpers = append(facts.Helpers, h)
	}
	sort.Slice(facts.Helpers, func(i, j int) bool {
		if facts.Helpers[i].Refs != facts.Helpers[j].Refs {
			return facts.Helpers[i].Refs > facts.Helpers[j].Refs
		}
		return facts.Helpers[i].Name < facts.Helpers[j].Name
	})
	return facts
}
