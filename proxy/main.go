package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type SearchResult struct {
	URL      string `json:"url"`
	Note     string `json:"note"`
	Password string `json:"password"`
	DateTime string `json:"datetime"`
}
type SearchResponse struct {
	Code int `json:"code"`
	Data struct {
		MergedByType map[string][]SearchResult `json:"merged_by_type"`
		Total        int                       `json:"total"`
	} `json:"data"`
}
type cacheEntry struct {
	data      SearchResponse
	timestamp time.Time
}

var (
	cacheMu   sync.RWMutex
	cache     = make(map[string]*cacheEntry)
	cacheTTL  = 10 * time.Minute
	pansouURL = "http://localhost:8081/api/search"
)

func getCached(key string) (*SearchResponse, bool) {
	cacheMu.RLock(); defer cacheMu.RUnlock()
	if e, ok := cache[key]; ok && time.Since(e.timestamp) < cacheTTL { return &e.data, true }
	return nil, false
}
func setCache(key string, data *SearchResponse) {
	cacheMu.Lock(); defer cacheMu.Unlock()
	cache[key] = &cacheEntry{data: *data, timestamp: time.Now()}
}

func searchHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	kw := r.URL.Query().Get("kw")
	if len(kw) < 2 { json.NewEncoder(w).Encode(&SearchResponse{Code: 0}); return }
	if c, ok := getCached(kw); ok { json.NewEncoder(w).Encode(c); return }

	merged := make(map[string][]SearchResult)
	seen := make(map[string]bool)
	var mu sync.Mutex
	var wg sync.WaitGroup

	// Query PanSou
	wg.Add(1)
	go func() {
		defer wg.Done()
		resp, err := http.Get(fmt.Sprintf("%s?kw=%s", pansouURL, url.QueryEscape(kw)))
		if err != nil { return }
		defer resp.Body.Close()
		var sr SearchResponse
		if json.NewDecoder(resp.Body).Decode(&sr) != nil { return }
		mu.Lock()
		for t, items := range sr.Data.MergedByType {
			merged[t] = append(merged[t], items...)
			for _, item := range items { seen[item.URL] = true }
		}
		mu.Unlock()
	}()

	// Query social scraper
	wg.Add(1)
	go func() {
		defer wg.Done()
		resp, err := http.Get(fmt.Sprintf("http://localhost:5002/api/search?kw=%s", url.QueryEscape(kw)))
		if err != nil { return }
		defer resp.Body.Close()
		var socialData struct{ Code int; Data struct{ Items []SearchResult `json:"items"` } }
		if json.NewDecoder(resp.Body).Decode(&socialData) != nil { return }
		mu.Lock()
		for _, item := range socialData.Data.Items {
			if seen[item.URL] { continue }
			seen[item.URL] = true
			merged["social"] = append(merged["social"], SearchResult{
				URL: item.URL, Note: item.Note, Password: item.Password, DateTime: item.DateTime,
			})
		}
		mu.Unlock()
	}()

	wg.Wait()
	total := 0
	for _, items := range merged { total += len(items) }
	sr := SearchResponse{Code: 0}
	sr.Data.MergedByType = merged
	sr.Data.Total = total
	setCache(kw, &sr)
	json.NewEncoder(w).Encode(sr)
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{"status": "ok", "backend": "PanSou", "cache": len(cache)})
}

func main() {
	port := os.Getenv("PORT")
	if port == "" { port = "8080" }
	staticDir := os.Getenv("STATIC_DIR")
	if staticDir == "" { staticDir = "." }
	mux := http.NewServeMux()
	mux.HandleFunc("/api/search", searchHandler)
	mux.HandleFunc("/api/health", healthHandler)
	absDir, _ := filepath.Abs(staticDir)
	fs := http.FileServer(http.Dir(absDir))
	mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") { http.NotFound(w, r); return }
		if _, err := os.Stat(filepath.Join(absDir, r.URL.Path)); os.IsNotExist(err) {
			http.ServeFile(w, r, filepath.Join(absDir, "index.html")); return
		}
		fs.ServeHTTP(w, r)
	}))
	srv := &http.Server{Addr: ":" + port, Handler: mux, ReadTimeout: 15 * time.Second, WriteTimeout: 60 * time.Second}
	log.Printf("凌云搜索 :%s → PanSou :8081", port)
	log.Fatal(srv.ListenAndServe())
}
