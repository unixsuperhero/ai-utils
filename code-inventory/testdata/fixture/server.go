// Package fixture is a tiny module the end-to-end test scans.
package fixture

import (
	"database/sql"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"
)

type Server struct {
	Name  string
	Addr  string
	Port  int
	DB    *sql.DB
	mu    sync.Mutex
	Count int
}

type Client struct {
	Name    string
	Addr    string
	Retries int
}

type Peer struct {
	Name string
	Addr string
}

func NewServer(name string) *Server {
	return &Server{Name: name, Addr: os.Getenv("ADDR")}
}

func (s *Server) Save() error {
	_, err := s.DB.Exec("insert")
	return err
}

func (s *Server) Key(kind, id string) string { return kind + ":" + id }

func (s *Server) Parse(key string) []string { return strings.Split(key, ":") }

func (s *Server) Run() {
	s.mu.Lock()
	defer s.mu.Unlock()
	go func() {}()
	_ = exec.Command("true")
	s.Count++
}

func Decode(m map[string]any) (string, int, error) {
	n, _ := m["name"].(string)
	c, _ := m["count"].(int)
	return n, c, nil
}

func (s *Server) View() string {
	var b strings.Builder
	fmt.Fprintf(&b, "%s %d", s.Name, s.Port)
	return b.String()
}

// serverJSON shares Server's field objects; uses of Server must not count for it.
type serverJSON Server
