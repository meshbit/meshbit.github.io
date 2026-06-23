package main

import (
	"encoding/json"
	"fmt"
	"io"
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

type Hit struct {
	Index  string `json:"_index"`
	ID     string `json:"_id"`
	Source struct {
		URL      string `json:"url"`
		Note     string `json:"note"`
		Password string `json:"password"`
		DateTime string `json:"datetime"`
		DiskType string `json:"disk_type"`
	} `json:"_source"`
}

type Hits struct {
	Total struct {
		Value int `json:"value"`
	} `json:"total"`
	Hits []Hit `json:"hits"`
}

type ESResponse struct {
	Hits Hits `json:"hits"`
}

var (
	pansouURL = "http://localhost:8081/api/search"
	esURL     = "http://localhost:9200"
	esIndex   = "disk"
)

func cleanURL(u string) string {
	u = strings.Split(u, "?")[0]
	u = strings.Split(u, "#")[0]
	return u
}

func getCached(key string) (*SearchResponse, bool) {
	cacheMu.RLock()
	defer cacheMu.RUnlock()
	if entry, ok := cache[key]; ok && time.Since(entry.timestamp) < cacheTTL {
		return &entry.data, true
	}
	return nil, false
}

func setCache(key string, data *SearchResponse) {
	cacheMu.Lock()
	defer cacheMu.Unlock()
	cache[key] = &cacheEntry{data: *data, timestamp: time.Now()}
}

var (
	cacheMu  sync.RWMutex
	cache    = make(map[string]*cacheEntry)
	cacheTTL = 10 * time.Minute
)

type cacheEntry struct {
	data      SearchResponse
	timestamp time.Time
}

func searchHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	keyword := r.URL.Query().Get("kw")
	if len(keyword) < 2 {
		json.NewEncoder(w).Encode(&SearchResponse{Code: 0})
		return
	}

	if cached, ok := getCached(keyword); ok {
		json.NewEncoder(w).Encode(cached)
		return
	}

	merged := make(map[string][]SearchResult)
	seen := make(map[string]bool)
	var mu sync.Mutex
	var wg sync.WaitGroup

	// Query PanSou
	wg.Add(1)
	go func() {
		defer wg.Done()
		u := fmt.Sprintf("%s?kw=%s", pansouURL, url.QueryEscape(keyword))
		resp, err := http.Get(u)
		if err != nil { return }
		defer resp.Body.Close()
		var sr SearchResponse
		if json.NewDecoder(resp.Body).Decode(&sr) != nil { return }
		mu.Lock()
		for t, items := range sr.Data.MergedByType {
			merged[t] = append(merged[t], items...)
			for _, item := range items {
				seen[cleanURL(item.URL)] = true
			}
		}
		mu.Unlock()
	}()

	// Query Elasticsearch
	wg.Add(1)
	go func() {
		defer wg.Done()
		query := fmt.Sprintf(`{"query":{"multi_match":{"query":"%s","fields":["note","keyword"]}},"size":100}`, keyword)
		resp, err := http.Post(
			fmt.Sprintf("%s/%s/_search", esURL, esIndex),
			"application/json",
			strings.NewReader(query),
		)
		if err != nil { return }
		defer resp.Body.Close()
		body, _ := io.ReadAll(resp.Body)
		var esResp ESResponse
		if json.Unmarshal(body, &esResp) != nil { return }
		mu.Lock()
		for _, hit := range esResp.Hits.Hits {
			src := hit.Source
			clean := cleanURL(src.URL)
			if seen[clean] { continue }
			seen[clean] = true
			t := src.DiskType
			if t == "" { t = "others" }
			merged[t] = append(merged[t], SearchResult{
				URL: src.URL, Note: src.Note, Password: src.Password, DateTime: src.DateTime,
			})
		}
		mu.Unlock()
	}()

	wg.Wait()

	total := 0
	for _, items := range merged {
		total += len(items)
	}

	resp := &SearchResponse{Code: 0}
	resp.Data.MergedByType = merged
	resp.Data.Total = total
	setCache(keyword, resp)
	json.NewEncoder(w).Encode(resp)
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status": "ok", "version": "4.0.0",
		"backend": "PanSou+ES", "cache": len(cache),
	})
}

func main() {
	port := os.Getenv("PORT")
	if port == "" { port = "5000" }
	staticDir := os.Getenv("STATIC_DIR")
	if staticDir == "" { staticDir = "." }

	mux := http.NewServeMux()
	mux.HandleFunc("/api/search", searchHandler)
	mux.HandleFunc("/api/health", healthHandler)

	absDir, _ := filepath.Abs(staticDir)
	fs := http.FileServer(http.Dir(absDir))
	mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") {
			http.NotFound(w, r)
			return
		}
		path := filepath.Join(absDir, r.URL.Path)
		if _, err := os.Stat(path); os.IsNotExist(err) {
			http.ServeFile(w, r, filepath.Join(absDir, "index.html"))
			return
		}
		fs.ServeHTTP(w, r)
	}))

	srv := &http.Server{Addr: ":" + port, Handler: mux, ReadTimeout: 15 * time.Second, WriteTimeout: 60 * time.Second}

	log.Printf("凌云搜索 v4.0 :%s (PanSou+Elasticsearch)", port)
	log.Fatal(srv.ListenAndServe())
}
