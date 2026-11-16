package main

import (
	"sort"
	"strings"
)

// realFns are the declared functions and methods (not var initializers).
func (inv *inventory) realFns() []*fnInfo {
	var out []*fnInfo
	for _, f := range inv.fns {
		if !f.IsVar {
			out = append(out, f)
		}
	}
	return out
}

type cluster struct {
	Struct string
	Fields []string
	Min    float64
	Shared []string
}

func (inv *inventory) readerSets(label string) ([]string, map[string]map[string]bool) {
	sets := map[string]map[string]bool{}
	var names []string
	for _, k := range sortedKeys(inv.fields) {
		f := inv.fields[k]
		if f.Struct != label || len(f.Readers) == 0 {
			continue
		}
		names = append(names, f.Field)
		sets[f.Field] = f.Readers
	}
	return names, sets
}

func (inv *inventory) clusters(threshold float64) []cluster {
	var out []cluster
	for _, t := range inv.targets {
		names, sets := inv.readerSets(t.Label)
		cs, mins := completeLinkage(names, sets, threshold)
		for i, c := range cs {
			shared := map[string]bool{}
			for k := range sets[c[0]] {
				shared[k] = true
			}
			for _, f := range c[1:] {
				for k := range shared {
					if !sets[f][k] {
						delete(shared, k)
					}
				}
			}
			var sh []string
			for _, k := range sortedKeys(shared) {
				sh = append(sh, shortFn(k))
			}
			out = append(out, cluster{t.Label, c, mins[i], sh})
		}
	}
	return out
}

type fieldPair struct {
	Struct, A, B string
	J            float64
	Co           int
}

func (inv *inventory) fieldPairs() []fieldPair {
	var out []fieldPair
	for _, t := range inv.targets {
		names, sets := inv.readerSets(t.Label)
		for i := range names {
			for j := i + 1; j < len(names); j++ {
				a, b := sets[names[i]], sets[names[j]]
				co := 0
				for k := range a {
					if b[k] {
						co++
					}
				}
				if co < 2 {
					continue
				}
				if jv := jaccard(a, b); jv >= inv.cfg.Pair {
					out = append(out, fieldPair{t.Label, names[i], names[j], jv, co})
				}
			}
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].J != out[j].J {
			return out[i].J > out[j].J
		}
		return out[i].Co > out[j].Co
	})
	return out
}

type fieldGroup struct {
	Fields  []string
	Structs []string
}

// fieldGroups returns the closed field groups: every intersection (2+
// fields) of two struct types' field sets, with the struct types that hold
// all of it.
func (inv *inventory) fieldGroups() []fieldGroup {
	index := map[string][]int{}
	for i, s := range inv.structs {
		for _, sig := range s.Sigs {
			index[sig] = append(index[sig], i)
		}
	}
	seen := map[string]bool{}
	var out []fieldGroup
	for i, s := range inv.structs {
		shared := map[int][]string{}
		for _, sig := range s.Sigs {
			for _, j := range index[sig] {
				if j > i {
					shared[j] = append(shared[j], sig)
				}
			}
		}
		for _, sigs := range shared {
			if len(sigs) < 2 {
				continue
			}
			sort.Strings(sigs)
			key := strings.Join(sigs, "\x00")
			if seen[key] {
				continue
			}
			seen[key] = true
			// Support: structs holding every sig.
			holders := map[int]int{}
			for _, sig := range sigs {
				for _, k := range index[sig] {
					holders[k]++
				}
			}
			var names []string
			for k, n := range holders {
				if n == len(sigs) {
					st := inv.structs[k]
					names = append(names, st.Label)
				}
			}
			sort.Strings(names)
			out = append(out, fieldGroup{append([]string(nil), sigs...), names})
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if len(out[i].Structs) != len(out[j].Structs) {
			return len(out[i].Structs) > len(out[j].Structs)
		}
		if len(out[i].Fields) != len(out[j].Fields) {
			return len(out[i].Fields) > len(out[j].Fields)
		}
		return strings.Join(out[i].Fields, ",") < strings.Join(out[j].Fields, ",")
	})
	return out
}

type mapFn struct {
	Fn    *fnInfo
	Sites int
	Keys  []string
}

type keySet struct {
	Keys []string
	Fns  []string
}

func (inv *inventory) mapFunctions() ([]mapFn, []keySet) {
	by := map[*fnInfo]map[string]bool{}
	sites := map[*fnInfo]int{}
	var order []*fnInfo
	for _, s := range inv.maps {
		if by[s.Fn] == nil {
			by[s.Fn] = map[string]bool{}
			order = append(order, s.Fn)
		}
		by[s.Fn][s.Key] = true
		sites[s.Fn]++
	}
	var out []mapFn
	sets := map[string][]string{}
	for _, f := range order {
		ks := sortedKeys(by[f])
		out = append(out, mapFn{f, sites[f], ks})
		if len(ks) >= 2 {
			k := strings.Join(ks, "\x00")
			sets[k] = append(sets[k], shortFn(f.ID))
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if len(out[i].Keys) != len(out[j].Keys) {
			return len(out[i].Keys) > len(out[j].Keys)
		}
		return out[i].Sites > out[j].Sites
	})
	var ks []keySet
	for _, k := range sortedByLen(sets) {
		fs := sets[k]
		sort.Strings(fs)
		ks = append(ks, keySet{strings.Split(k, "\x00"), fs})
	}
	return out, ks
}

type paramGroup struct {
	Types string
	N     int
	Fns   []*fnInfo
}

func (inv *inventory) paramGroups() []paramGroup {
	by := map[string][]*fnInfo{}
	n := map[string]int{}
	for _, r := range inv.params {
		by[r.Types] = append(by[r.Types], r.Fn)
		n[r.Types] = r.N
	}
	var out []paramGroup
	for _, k := range sortedByLen(by) {
		if len(by[k]) < 2 {
			continue
		}
		out = append(out, paramGroup{k, n[k], by[k]})
	}
	return out
}

type sepRow struct {
	Sep                   string
	JoinSites, SplitSites int
	Join, Split           map[string]bool
	Both                  int
}

type prefixRow struct {
	Prefix      string
	Join, Split map[string]bool
}

func (inv *inventory) stringMatches() ([]sepRow, []prefixRow) {
	seps := map[string]*sepRow{}
	pre := map[string]*prefixRow{}
	for _, s := range inv.strs {
		h := s.Hit
		r := seps[h.Sep]
		if r == nil {
			r = &sepRow{Sep: h.Sep, Join: map[string]bool{}, Split: map[string]bool{}}
			seps[h.Sep] = r
		}
		if h.Kind == "join" {
			r.JoinSites++
			r.Join[s.Fn.ID] = true
		} else {
			r.SplitSites++
			r.Split[s.Fn.ID] = true
		}
		if h.Prefix != "" {
			p := pre[h.Prefix]
			if p == nil {
				p = &prefixRow{Prefix: h.Prefix, Join: map[string]bool{}, Split: map[string]bool{}}
				pre[h.Prefix] = p
			}
			if h.Kind == "join" {
				p.Join[s.Fn.ID] = true
			} else {
				p.Split[s.Fn.ID] = true
			}
		}
	}
	var sr []sepRow
	for _, k := range sortedKeys(seps) {
		r := seps[k]
		for f := range r.Join {
			if r.Split[f] {
				r.Both++
			}
		}
		sr = append(sr, *r)
	}
	var pr []prefixRow
	for _, k := range sortedKeys(pre) {
		pr = append(pr, *pre[k])
	}
	sort.SliceStable(pr, func(i, j int) bool {
		a := min(len(pr[i].Join), len(pr[i].Split))
		b := min(len(pr[j].Join), len(pr[j].Split))
		if a != b {
			return a > b
		}
		return len(pr[i].Join)+len(pr[i].Split) > len(pr[j].Join)+len(pr[j].Split)
	})
	return sr, pr
}

type cell struct {
	Funcs, Lines, DirectFuncs, DirectLines int
}

// grid returns responsibility -> subject -> cell, and for each
// responsibility the subjects with functions doing it directly.
func (inv *inventory) grid(fns []*fnInfo) (map[string]map[string]cell, map[string]map[string][]*fnInfo) {
	g := map[string]map[string]cell{}
	impl := map[string]map[string][]*fnInfo{}
	add := func(r, s string, f *fnInfo, direct bool) {
		if g[r] == nil {
			g[r] = map[string]cell{}
		}
		c := g[r][s]
		c.Funcs++
		c.Lines += f.Lines
		if direct {
			c.DirectFuncs++
			c.DirectLines += f.Lines
			if impl[r] == nil {
				impl[r] = map[string][]*fnInfo{}
			}
			impl[r][s] = append(impl[r][s], f)
		}
		g[r][s] = c
	}
	for _, f := range fns {
		if len(f.Tags) == 0 {
			add("other", f.Subject, f, false)
			continue
		}
		for t, lvl := range f.Tags {
			add(t, f.Subject, f, lvl == "base" || lvl == "local")
		}
	}
	return g, impl
}
