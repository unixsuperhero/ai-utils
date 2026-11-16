package main

// Loading and the per-node walk.

import (
	"fmt"
	"go/ast"
	"go/constant"
	"go/token"
	"go/types"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"golang.org/x/tools/go/packages"
)

type fnInfo struct {
	ID, Pkg, PkgName, File, Recv, Name string
	Line, Lines                        int
	Tags                               map[string]string // tag -> strongest level
	Via                                map[string]map[string]bool
	Subject, SubjectFrom               string
	IsVar                              bool // a package-level var initializer, not a function
	uses                               map[string]bool
}

func (f *fnInfo) Display() string {
	if f.Recv != "" {
		return f.Recv + "." + f.Name
	}
	return f.Name
}

type fieldRec struct {
	Struct, Field, Type string
	File                string
	Line                int
	Readers, Writers    map[string]bool
}

type structRec struct {
	Pkg, PkgPath, Name, Label, File string
	Line, Fields                    int
	Sigs                            []string
	obj                             *types.TypeName
}

type mapSite struct {
	Fn                      *fnInfo
	File                    string
	Line                    int
	MapType, Expr, Key, Use string
	Iface                   bool
}

type tupleRec struct {
	Fn    *fnInfo
	N     int
	Types string
}

type strSite struct {
	Fn   *fnInfo
	File string
	Line int
	Hit  strHit
}

type fileRec struct {
	Pkg, File               string
	Lines, Funcs, FuncLines int
}

type inventory struct {
	cfg       *config
	rules     *RuleSet
	strRules  *strRules
	fset      *token.FileSet
	commit    string
	loadErrs  []string
	fns       []*fnInfo
	byID      map[string]*fnInfo
	fields    map[string]*fieldRec                      // "Label.Field"
	fieldVars map[*types.Var]map[*types.TypeName]string // a field var is shared by `type B A`
	structs   []*structRec
	targets   []*structRec
	maps      []mapSite
	results   []tupleRec
	params    []tupleRec
	strs      []strSite
	typeNames map[string]bool
	files     []fileRec
	vocab     vocab
	tests     testFacts
	timings   []string
}

type runResult struct {
	Elapsed time.Duration
	Timings []string
}

func run(cfg *config) (*runResult, error) {
	start := time.Now()
	rs, err := NewRuleSet(cfg.RuleFiles)
	if err != nil {
		return nil, err
	}
	inv := &inventory{
		cfg: cfg, rules: rs, strRules: newStrRules(cfg.Seps),
		byID: map[string]*fnInfo{}, fields: map[string]*fieldRec{},
		fieldVars: map[*types.Var]map[*types.TypeName]string{}, typeNames: map[string]bool{},
	}
	inv.commit = gitHead(cfg.Root)
	t := time.Now()
	if err := inv.load(); err != nil {
		return nil, err
	}
	inv.timings = append(inv.timings, fmt.Sprintf("load+walk: %s", time.Since(t).Round(time.Millisecond)))
	inv.vocab = newVocab(sortedKeys(inv.typeNames))
	for _, f := range inv.fns {
		stem := strings.TrimSuffix(filepath.Base(f.File), ".go")
		f.Subject, f.SubjectFrom = inv.vocab.subjectOf(f.Name, f.Recv, stem, f.PkgName)
	}
	if cfg.Tests && len(inv.targets) > 0 {
		// The largest mapped struct that has a constructor.
		t = time.Now()
		var skipped []string
		for _, target := range inv.targets {
			inv.tests = measureTests(cfg.Root, target)
			if !inv.tests.NoCtor {
				break
			}
			skipped = append(skipped, target.Label)
		}
		inv.tests.Skipped = skipped
		inv.timings = append(inv.timings, fmt.Sprintf("tests reaching %s: %s", inv.tests.Struct, time.Since(t).Round(time.Millisecond)))
	}
	if err := os.MkdirAll(cfg.Out, 0o755); err != nil {
		return nil, err
	}
	if err := inv.write(cfg.Out, time.Since(start)); err != nil {
		return nil, err
	}
	return &runResult{time.Since(start), inv.timings}, nil
}

func loadConfig(dir string, tests bool) *packages.Config {
	return &packages.Config{
		Mode: packages.NeedName | packages.NeedFiles | packages.NeedSyntax | packages.NeedTypes |
			packages.NeedTypesInfo | packages.NeedImports,
		Dir:   dir,
		Fset:  token.NewFileSet(),
		Tests: tests,
	}
}

func (inv *inventory) inRoot(name string) (string, bool) {
	if !strings.HasPrefix(name, inv.cfg.Root+"/") || strings.HasSuffix(name, "_test.go") {
		return "", false
	}
	return strings.TrimPrefix(name, inv.cfg.Root+"/"), true
}

func (inv *inventory) load() error {
	cfg := loadConfig(inv.cfg.Root, false)
	inv.fset = cfg.Fset
	pkgs, err := packages.Load(cfg, inv.cfg.Patterns...)
	if err != nil {
		return err
	}
	packages.Visit(pkgs, nil, func(p *packages.Package) {
		for _, e := range p.Errors {
			inv.loadErrs = append(inv.loadErrs, e.Error())
		}
	})
	if len(inv.loadErrs) > 0 {
		fmt.Fprintf(os.Stderr, "code-inventory: %d load errors, first: %s\n", len(inv.loadErrs), inv.loadErrs[0])
	}
	sort.Slice(pkgs, func(i, j int) bool { return pkgs[i].PkgPath < pkgs[j].PkgPath })
	// Pass 1: struct types, so the target fields are known before the walk.
	for _, p := range pkgs {
		if p.Types != nil {
			inv.collectStructs(p, cfg.Fset)
		}
	}
	if err := inv.pickTargets(); err != nil {
		return err
	}
	// Pass 2: the walk.
	for _, p := range pkgs {
		if p.TypesInfo == nil {
			continue
		}
		for _, f := range p.Syntax {
			if rel, ok := inv.inRoot(cfg.Fset.File(f.Pos()).Name()); ok {
				inv.walkFile(p, cfg.Fset, f, rel)
			}
		}
	}
	return nil
}

// collectStructs records the package-level named struct types of p and the
// type names that make up the subject vocabulary.
func (inv *inventory) collectStructs(p *packages.Package, fset *token.FileSet) {
	sc := p.Types.Scope()
	for _, n := range sc.Names() {
		tn, ok := sc.Lookup(n).(*types.TypeName)
		if !ok || tn.IsAlias() {
			continue
		}
		pos := fset.Position(tn.Pos())
		rel, ok := inv.inRoot(pos.Filename)
		if !ok {
			continue
		}
		if tn.Exported() {
			inv.typeNames[tn.Name()] = true
		}
		st, ok := tn.Type().Underlying().(*types.Struct)
		if !ok {
			continue
		}
		rec := &structRec{Pkg: p.Name, PkgPath: p.PkgPath, Name: tn.Name(), File: rel, Line: pos.Line, Fields: st.NumFields(), obj: tn}
		for i := 0; i < st.NumFields(); i++ {
			fv := st.Field(i)
			rec.Sigs = append(rec.Sigs, fv.Name()+" "+types.TypeString(fv.Type(), shortQual))
		}
		sort.Strings(rec.Sigs)
		inv.structs = append(inv.structs, rec)
	}
}

// pickTargets chooses the structs mapped field by field: the --structs
// largest by field count, plus every --struct, and binds their fields.
func (inv *inventory) pickTargets() error {
	labels := map[string]int{}
	for _, s := range inv.structs {
		labels[s.Pkg+"."+s.Name]++
	}
	for _, s := range inv.structs {
		s.Label = s.Pkg + "." + s.Name
		if labels[s.Label] > 1 {
			s.Label = s.PkgPath + "." + s.Name
		}
	}
	bySize := append([]*structRec(nil), inv.structs...)
	sort.SliceStable(bySize, func(i, j int) bool {
		if bySize[i].Fields != bySize[j].Fields {
			return bySize[i].Fields > bySize[j].Fields
		}
		return bySize[i].Label < bySize[j].Label
	})
	chosen := map[*structRec]bool{}
	for i := 0; i < inv.cfg.Structs && i < len(bySize); i++ {
		if bySize[i].Fields > 0 {
			chosen[bySize[i]] = true
		}
	}
	for _, want := range inv.cfg.Named {
		found := false
		for _, s := range inv.structs {
			if want == s.Name || want == s.Pkg+"."+s.Name || want == s.PkgPath+"."+s.Name || want == s.Label {
				chosen[s] = true
				found = true
			}
		}
		if !found {
			return fmt.Errorf("--struct %s: no such struct type in the scanned packages", want)
		}
	}
	for _, s := range bySize {
		if !chosen[s] {
			continue
		}
		inv.targets = append(inv.targets, s)
		st := s.obj.Type().Underlying().(*types.Struct)
		for i := 0; i < st.NumFields(); i++ {
			fv := st.Field(i)
			key := s.Label + "." + fv.Name()
			if inv.fieldVars[fv] == nil {
				inv.fieldVars[fv] = map[*types.TypeName]string{}
			}
			inv.fieldVars[fv][s.obj] = key
			line := s.Line
			if inv.fset != nil {
				line = inv.fset.Position(fv.Pos()).Line
			}
			inv.fields[key] = &fieldRec{Struct: s.Label, Field: fv.Name(), Type: types.TypeString(fv.Type(), qual(s.obj.Pkg())),
				File: s.File, Line: line, Readers: map[string]bool{}, Writers: map[string]bool{}}
		}
	}
	return nil
}

func qual(self *types.Package) types.Qualifier {
	return func(p *types.Package) string {
		if p == self {
			return ""
		}
		return p.Name()
	}
}

// shortQual spells types with the package name only.
func shortQual(p *types.Package) string { return p.Name() }

func recvName(t ast.Expr) string {
	switch t := t.(type) {
	case *ast.StarExpr:
		return recvName(t.X)
	case *ast.IndexExpr:
		return recvName(t.X)
	case *ast.IndexListExpr:
		return recvName(t.X)
	case *ast.Ident:
		return t.Name
	}
	return ""
}

func (inv *inventory) newFn(p *packages.Package, file, recv, name string, line, end int) *fnInfo {
	id := p.PkgPath + "." + name
	if recv != "" {
		id = p.PkgPath + ".(" + recv + ")." + name
	}
	if inv.byID[id] != nil { // init funcs, var groups: keep ids unique
		id = fmt.Sprintf("%s@%s:%d", id, file, line)
	}
	f := &fnInfo{ID: id, Pkg: p.PkgPath, PkgName: p.Name, File: file, Recv: recv, Name: name,
		Line: line, Lines: end - line + 1, Tags: map[string]string{}, Via: map[string]map[string]bool{}, uses: map[string]bool{}}
	inv.fns = append(inv.fns, f)
	inv.byID[id] = f
	if recv != "" {
		inv.typeNames[recv] = true
	}
	return f
}

var levelRank = map[string]int{"base": 3, "local": 2, "uses": 1}

func (f *fnInfo) tag(hits []tagHit, via string) {
	for _, h := range hits {
		if levelRank[h.Level] > levelRank[f.Tags[h.Tag]] {
			f.Tags[h.Tag] = h.Level
		}
		if f.Via[h.Tag] == nil {
			f.Via[h.Tag] = map[string]bool{}
		}
		f.Via[h.Tag][via] = true
	}
}

func (inv *inventory) walkFile(p *packages.Package, fset *token.FileSet, f *ast.File, rel string) {
	info := p.TypesInfo
	fr := fileRec{Pkg: p.PkgPath, File: rel, Lines: fset.File(f.Pos()).LineCount()}
	line := func(n ast.Node) int { return fset.Position(n.Pos()).Line }
	for _, d := range f.Decls {
		switch d := d.(type) {
		case *ast.FuncDecl:
			recv := ""
			if d.Recv != nil && len(d.Recv.List) > 0 {
				recv = recvName(d.Recv.List[0].Type)
			}
			fn := inv.newFn(p, rel, recv, d.Name.Name, line(d), fset.Position(d.End()).Line)
			fr.Funcs++
			fr.FuncLines += fn.Lines
			if obj, ok := info.Defs[d.Name].(*types.Func); ok {
				inv.signature(fn, obj.Type().(*types.Signature))
			}
			if d.Body != nil {
				inv.walkBody(fn, d.Body, info, p.Types, fset, rel)
			}
			hits, via := inv.rules.TagOwn(fn.Name, fn.uses)
			for i, h := range hits {
				fn.tag([]tagHit{h}, via[i])
			}
		case *ast.GenDecl:
			for _, s := range d.Specs {
				vs, ok := s.(*ast.ValueSpec)
				if !ok || d.Tok != token.VAR || len(vs.Values) == 0 {
					continue
				}
				// Package-level values: walked for maps and strings,
				// attributed to a pseudo function named after the first name.
				fn := inv.newFn(p, rel, "", "var "+vs.Names[0].Name, line(vs), fset.Position(vs.End()).Line)
				fn.IsVar = true
				for _, v := range vs.Values {
					inv.walkBody(fn, v, info, p.Types, fset, rel)
				}
			}
		}
	}
	inv.files = append(inv.files, fr)
}

func (inv *inventory) signature(fn *fnInfo, sig *types.Signature) {
	tuple := func(t *types.Tuple, variadic bool) string {
		var ss []string
		for i := 0; i < t.Len(); i++ {
			s := types.TypeString(t.At(i).Type(), shortQual)
			if variadic && i == t.Len()-1 {
				s = "..." + strings.TrimPrefix(s, "[]")
			}
			ss = append(ss, s)
		}
		return strings.Join(ss, ", ")
	}
	if n := sig.Results().Len(); n >= inv.cfg.Results {
		inv.results = append(inv.results, tupleRec{fn, n, tuple(sig.Results(), false)})
	}
	if n := sig.Params().Len(); n >= inv.cfg.Params {
		inv.params = append(inv.params, tupleRec{fn, n, tuple(sig.Params(), sig.Variadic())})
	}
}

func unparen(e ast.Expr) ast.Expr {
	for {
		p, ok := e.(*ast.ParenExpr)
		if !ok {
			return e
		}
		e = p.X
	}
}

// constString gives a constant string, byte or rune expression as a string.
func constString(info *types.Info, e ast.Expr) (string, bool) {
	tv, ok := info.Types[e]
	if !ok || tv.Value == nil {
		return "", false
	}
	switch tv.Value.Kind() {
	case constant.String:
		return constant.StringVal(tv.Value), true
	case constant.Int:
		if b, ok := tv.Type.Underlying().(*types.Basic); ok && (b.Kind() == types.Byte || b.Kind() == types.Rune || b.Kind() == types.UntypedRune) {
			if v, ok := constant.Int64Val(tv.Value); ok {
				return string(rune(v)), true
			}
		}
	}
	return "", false
}

func isString(info *types.Info, e ast.Expr) bool {
	t := info.TypeOf(e)
	if t == nil {
		return false
	}
	b, ok := t.Underlying().(*types.Basic)
	return ok && b.Info()&types.IsString != 0
}

// isWrite says whether n (a child of the top of stack) is written: assigned,
// incremented, address taken, ranged into, or an element of it assigned.
func isWrite(n ast.Node, stack []ast.Node) bool {
	child := n
	for i := len(stack) - 1; i >= 0; i-- {
		switch p := stack[i].(type) {
		case *ast.ParenExpr:
			child = p
			continue
		case *ast.AssignStmt:
			for _, l := range p.Lhs {
				if l == child {
					return true
				}
			}
			return false
		case *ast.IncDecStmt:
			return p.X == child
		case *ast.UnaryExpr:
			return p.Op == token.AND && p.X == child
		case *ast.RangeStmt:
			return p.Key == child || p.Value == child
		case *ast.IndexExpr:
			if p.X != child {
				return false
			}
			child = p // a[k] = v writes into a
			continue
		}
		return false
	}
	return false
}

func (inv *inventory) walkBody(fn *fnInfo, root ast.Node, info *types.Info, self *types.Package, fset *token.FileSet, rel string) {
	var stack []ast.Node
	ast.Inspect(root, func(n ast.Node) bool {
		if n == nil {
			stack = stack[:len(stack)-1]
			return false
		}
		inv.visit(fn, n, stack, info, self, fset, rel)
		stack = append(stack, n)
		return true
	})
}

// fieldKeys returns the mapped "Label.Field" keys a use of v counts for.
// on is the struct type the field is selected on or the literal's type;
// when v belongs to several mapped types (type B A shares A's fields) only
// the one named by on counts, and all of them when on names none (a
// promoted field).
func (inv *inventory) fieldKeys(v *types.Var, on types.Type) []string {
	m := inv.fieldVars[v]
	if m == nil {
		m = inv.fieldVars[v.Origin()]
	}
	if len(m) == 0 {
		return nil
	}
	if on != nil {
		if pt, ok := on.(*types.Pointer); ok {
			on = pt.Elem()
		}
		if nt, ok := on.(*types.Named); ok {
			if k, ok := m[nt.Origin().Obj()]; ok {
				return []string{k}
			}
		}
	}
	var out []string
	for _, k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func (inv *inventory) visit(fn *fnInfo, n ast.Node, stack []ast.Node, info *types.Info, self *types.Package, fset *token.FileSet, rel string) {
	line := func() int { return fset.Position(n.Pos()).Line }
	syntax := func(c string) { fn.tag(inv.rules.TagSyntax(c), "syntax "+c) }
	switch n := n.(type) {
	case *ast.GoStmt:
		syntax("go")
	case *ast.SelectStmt:
		syntax("select")
	case *ast.SendStmt:
		syntax("send")
	case *ast.UnaryExpr:
		if n.Op == token.ARROW {
			syntax("recv")
		}
	case *ast.RangeStmt:
		if t := info.TypeOf(n.X); t != nil {
			if _, ok := t.Underlying().(*types.Chan); ok {
				syntax("recv")
			}
		}
	case *ast.SelectorExpr:
		if sel := info.Selections[n]; sel != nil && sel.Kind() == types.FieldVal {
			if v, ok := sel.Obj().(*types.Var); ok {
				w := isWrite(n, stack)
				for _, key := range inv.fieldKeys(v, sel.Recv()) {
					if w {
						inv.fields[key].Writers[fn.ID] = true
					} else {
						inv.fields[key].Readers[fn.ID] = true
					}
				}
			}
		}
	case *ast.KeyValueExpr:
		if len(stack) > 0 {
			if lit, ok := stack[len(stack)-1].(*ast.CompositeLit); ok {
				if id, ok := n.Key.(*ast.Ident); ok {
					if v, ok := info.Uses[id].(*types.Var); ok {
						for _, key := range inv.fieldKeys(v, info.TypeOf(lit)) {
							inv.fields[key].Writers[fn.ID] = true
						}
					}
				}
			}
		}
	case *ast.Ident:
		if tn, ok := info.Uses[n].(*types.TypeName); ok && tn.Pkg() != nil {
			fn.tag(inv.rules.TagType(tn.Pkg().Path(), tn.Name(), self.Path()), "type "+tn.Pkg().Name()+"."+tn.Name())
			fn.uses[tn.Pkg().Path()+"."+tn.Name()] = true
		}
	case *ast.IndexExpr:
		if ok, iface := stringMap(info.TypeOf(n.X)); ok {
			if k, ok := constString(info, n.Index); ok {
				use := "read"
				if isWrite(n, stack) {
					use = "write"
				}
				inv.maps = append(inv.maps, mapSite{fn, rel, line(), types.TypeString(info.TypeOf(n.X), shortQual), exprText(n.X), k, use, iface})
			}
		}
	case *ast.BinaryExpr:
		if n.Op != token.ADD || !isString(info, n) {
			return
		}
		if len(stack) > 0 {
			if pb, ok := stack[len(stack)-1].(*ast.BinaryExpr); ok && pb.Op == token.ADD && isString(info, pb) {
				return // only the outermost + of a chain
			}
		}
		var ps []part
		var flat func(e ast.Expr)
		flat = func(e ast.Expr) {
			e = unparen(e)
			if b, ok := e.(*ast.BinaryExpr); ok && b.Op == token.ADD {
				if _, isConst := constString(info, b); !isConst {
					flat(b.X)
					flat(b.Y)
					return
				}
			}
			s, c := constString(info, e)
			ps = append(ps, part{c, s})
		}
		flat(n)
		for _, h := range inv.strRules.classifyConcat(ps) {
			inv.strs = append(inv.strs, strSite{fn, rel, line(), h})
		}
	case *ast.CallExpr:
		inv.call(fn, n, info, self, rel, line())
	}
}

func exprText(e ast.Expr) string {
	switch e := unparen(e).(type) {
	case *ast.Ident:
		return e.Name
	case *ast.SelectorExpr:
		return exprText(e.X) + "." + e.Sel.Name
	case *ast.CallExpr:
		return exprText(e.Fun) + "()"
	case *ast.IndexExpr:
		return exprText(e.X) + "[...]"
	case *ast.StarExpr:
		return "*" + exprText(e.X)
	}
	return "expr"
}

func (inv *inventory) call(fn *fnInfo, n *ast.CallExpr, info *types.Info, self *types.Package, rel string, line int) {
	fun := unparen(n.Fun)
	switch f := fun.(type) {
	case *ast.IndexExpr:
		fun = f.X
	case *ast.IndexListExpr:
		fun = f.X
	}
	var obj types.Object
	switch f := fun.(type) {
	case *ast.Ident:
		obj = info.Uses[f]
	case *ast.SelectorExpr:
		obj = info.Uses[f.Sel]
	}
	if b, ok := obj.(*types.Builtin); ok && b.Name() == "make" && len(n.Args) > 0 {
		if t := info.TypeOf(n.Args[0]); t != nil {
			if _, ok := t.Underlying().(*types.Chan); ok {
				fn.tag(inv.rules.TagSyntax("make-chan"), "syntax make-chan")
			}
		}
	}
	tf, ok := obj.(*types.Func)
	if !ok || tf.Pkg() == nil {
		return
	}
	c := callee{Pkg: tf.Pkg().Path(), Name: tf.Name()}
	if sig, ok := tf.Type().(*types.Signature); ok && sig.Recv() != nil {
		rt := sig.Recv().Type()
		if pt, ok := rt.(*types.Pointer); ok {
			rt = pt.Elem()
		}
		if nt, ok := rt.(*types.Named); ok {
			c.Recv = nt.Obj().Name()
		}
	}
	via := c.Pkg + "." + c.Name
	if c.Recv != "" {
		via = c.Pkg + ".(" + c.Recv + ")." + c.Name
	} else {
		fn.uses[via] = true
	}
	fn.tag(inv.rules.TagCallee(c, self.Path()), via)

	// Strings joined or split on a separator.
	if c.Recv == "" && (c.Pkg == "strings" || c.Pkg == "fmt") {
		consts := make([]string, len(n.Args))
		for i, a := range n.Args {
			consts[i], _ = constString(info, a)
		}
		name := c.Pkg + "." + c.Name
		hits := inv.strRules.classifyCall(name, consts)
		if name == "fmt.Sprintf" && len(consts) > 0 && consts[0] != "" {
			hits = append(hits, inv.strRules.classifyFormat(consts[0])...)
		}
		for _, h := range hits {
			inv.strs = append(inv.strs, strSite{fn, rel, line, h})
		}
	}
	// A helper that decodes a field: an interface-valued string map and a
	// constant key passed to the same call (thingString(changes, "title")).
	var mapArg ast.Expr
	var keys []string
	for _, a := range n.Args {
		if ok, iface := stringMap(info.TypeOf(a)); ok && iface {
			mapArg = a
		} else if s, ok := constString(info, a); ok && isString(info, a) {
			keys = append(keys, s)
		}
	}
	if mapArg != nil && len(keys) > 0 && c.Pkg != "fmt" {
		for _, k := range keys {
			inv.maps = append(inv.maps, mapSite{fn, rel, line, types.TypeString(info.TypeOf(mapArg), shortQual), exprText(mapArg), k, "helper " + c.Name, true})
		}
	}
}
