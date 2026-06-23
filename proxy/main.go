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
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

// ==================== Data Types ====================

type SearchResult struct {
	URL      string `json:"url"`
	Note     string `json:"note"`
	Password string `json:"password"`
	DateTime string `json:"datetime"`
	Type     string `json:"-"`
}

type SearchResponse struct {
	Code int `json:"code"`
	Data struct {
		MergedByType map[string][]SearchResult `json:"merged_by_type"`
		Total        int                       `json:"total"`
	} `json:"data"`
}

// ==================== Cache ====================

type cacheEntry struct {
	data      SearchResponse
	timestamp time.Time
}

var (
	cacheMu sync.RWMutex
	cache   = make(map[string]*cacheEntry)
	cacheTTL = 10 * time.Minute
)

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

// ==================== PanSou Client ====================

var pansouURL = "http://localhost:8081/api/search"

func queryPanSou(keyword string) (map[string][]SearchResult, error) {
	u := fmt.Sprintf("%s?kw=%s", pansouURL, url.QueryEscape(keyword))
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(u)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var sr SearchResponse
	if err := json.NewDecoder(resp.Body).Decode(&sr); err != nil {
		return nil, err
	}
	if sr.Code != 0 {
		return nil, fmt.Errorf("PanSou error code: %d", sr.Code)
	}
	return sr.Data.MergedByType, nil
}

// ==================== Web Scrapers ====================

var httpClient = &http.Client{
	Timeout: 8 * time.Second,
	Transport: &http.Transport{
		MaxIdleConns:    20,
		IdleConnTimeout: 30 * time.Second,
	},
}

var panURLRegex = regexp.MustCompile(
	`https?://(?:pan\.baidu\.com/s/[a-zA-Z0-9_-]{6,}|` +
		`(?:www\.)?aliyundrive\.com/s/[a-zA-Z0-9]{6,}|` +
		`pan\.quark\.cn/s/[a-zA-Z0-9]{8,}|` +
		`pan\.xunlei\.com/s/[a-zA-Z0-9]+|` +
		`cloud\.189\.cn/[^\s"']+|` +
		`drive\.uc\.cn/[^\s"']+|` +
		`115\.com/s/[^\s"']+|` +
		`123pan\.com/s/[^\s"']+|123684\.com/s/[^\s"']+)`,
)

func panType(link string) string {
	l := strings.ToLower(link)
	switch {
	case strings.Contains(l, "pan.baidu.com"): return "baidu"
	case strings.Contains(l, "aliyundrive.com") || strings.Contains(l, "alipan.com"): return "aliyun"
	case strings.Contains(l, "pan.quark.cn"): return "quark"
	case strings.Contains(l, "pan.xunlei.com"): return "xunlei"
	case strings.Contains(l, "cloud.189.cn"): return "tianyi"
	case strings.Contains(l, "drive.uc.cn"): return "uc"
	case strings.Contains(l, "115.com"): return "115"
	case strings.Contains(l, "123pan.com") || strings.Contains(l, "123684.com"): return "123"
	default: return ""
	}
}

func scrapeBaidu(keyword string) []SearchResult {
	var results []SearchResult
	q := url.QueryEscape(keyword + " 网盘")
	u := fmt.Sprintf("https://www.baidu.com/s?wd=%s&rn=15", q)
	req, _ := http.NewRequest("GET", u, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	req.Header.Set("Accept-Language", "zh-CN,zh;q=0.9")
	resp, err := httpClient.Do(req)
	if err != nil { return results }
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 512*1024))
	text := string(body)
	links := panURLRegex.FindAllString(text, -1)
	seen := make(map[string]bool)
	for _, link := range links {
		clean := strings.Split(link, "?")[0]
		if seen[clean] { continue }
		seen[clean] = true
		pt := panType(clean)
		if pt != "" {
			results = append(results, SearchResult{
				URL: clean, Note: keyword + " - 网盘资源",
				DateTime: time.Now().Format(time.RFC3339), Type: pt,
			})
		}
	}
	return results
}

func scrapeBing(keyword string) []SearchResult {
	var results []SearchResult
	q := url.QueryEscape(keyword + " site:pan.quark.cn OR site:pan.baidu.com")
	u := fmt.Sprintf("https://cn.bing.com/search?q=%s&count=15", q)
	req, _ := http.NewRequest("GET", u, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	req.Header.Set("Accept-Language", "zh-CN,zh;q=0.9")
	resp, err := httpClient.Do(req)
	if err != nil { return results }
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 512*1024))
	links := panURLRegex.FindAllString(string(body), -1)
	seen := make(map[string]bool)
	for _, link := range links {
		clean := strings.Split(link, "?")[0]
		if seen[clean] { continue }
		seen[clean] = true
		pt := panType(clean)
		if pt != "" {
			results = append(results, SearchResult{
				URL: clean, Note: keyword + " - 网盘资源",
				DateTime: time.Now().Format(time.RFC3339), Type: pt,
			})
		}
	}
	return results
}

func scrapeSogou(keyword string) []SearchResult {
	var results []SearchResult
	q := url.QueryEscape(keyword + " 网盘资源")
	u := fmt.Sprintf("https://www.sogou.com/web?query=%s&num=15", q)
	req, _ := http.NewRequest("GET", u, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	req.Header.Set("Accept-Language", "zh-CN,zh;q=0.9")
	resp, err := httpClient.Do(req)
	if err != nil { return results }
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 512*1024))
	links := panURLRegex.FindAllString(string(body), -1)
	seen := make(map[string]bool)
	for _, link := range links {
		clean := strings.Split(link, "?")[0]
		if seen[clean] { continue }
		seen[clean] = true
		pt := panType(clean)
		if pt != "" {
			results = append(results, SearchResult{
				URL: clean, Note: keyword + " - 网盘资源",
				DateTime: time.Now().Format(time.RFC3339), Type: pt,
			})
		}
	}
	return results
}

// ==================== Aggregator ====================

func aggregateSearch(keyword string) *SearchResponse {
	// Check cache
	if cached, ok := getCached(keyword); ok {
		return cached
	}

	merged := make(map[string][]SearchResult)
	seen := make(map[string]bool)
	var mu sync.Mutex
	var wg sync.WaitGroup

	// Query PanSou (primary)
	wg.Add(1)
	go func() {
		defer wg.Done()
		results, err := queryPanSou(keyword)
		if err != nil {
			log.Printf("PanSou error: %v", err)
			return
		}
		mu.Lock()
		for t, items := range results {
			merged[t] = append(merged[t], items...)
			for _, item := range items {
				seen[cleanURL(item.URL)] = true
			}
		}
		mu.Unlock()
	}()

	// Query scrapers in parallel
	scrapers := []func(string) []SearchResult{scrapeBaidu, scrapeBing, scrapeSogou}
	for _, sc := range scrapers {
		wg.Add(1)
		go func(fn func(string) []SearchResult) {
			defer wg.Done()
			results := fn(keyword)
			mu.Lock()
			for _, r := range results {
				clean := cleanURL(r.URL)
				if seen[clean] { continue }
				seen[clean] = true
				t := r.Type
				if t == "" { t = "others" }
				r.Type = ""
				merged[t] = append(merged[t], r)
			}
			mu.Unlock()
		}(sc)
	}

	wg.Wait()

	// Count total
	total := 0
	for _, items := range merged {
		total += len(items)
	}

	resp := &SearchResponse{Code: 0}
	resp.Data.MergedByType = merged
	resp.Data.Total = total

	// Cache
	setCache(keyword, resp)

	return resp
}

func cleanURL(u string) string {
	u = strings.Split(u, "?")[0]
	u = strings.Split(u, "#")[0]
	return u
}

// ==================== HTTP Handlers ====================

func searchHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	keyword := r.URL.Query().Get("kw")
	if len(keyword) < 2 {
		json.NewEncoder(w).Encode(&SearchResponse{Code: 0})
		return
	}

	result := aggregateSearch(keyword)
	json.NewEncoder(w).Encode(result)
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":  "ok",
		"version": "2.0.0",
		"cache":   len(cache),
	})
}

func cacheStatsHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	cacheMu.RLock()
	defer cacheMu.RUnlock()
	stats := make(map[string]interface{})
	stats["entries"] = len(cache)
	var keys []string
	for k := range cache {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	if len(keys) > 20 {
		keys = keys[:20]
	}
	stats["keys"] = keys
	json.NewEncoder(w).Encode(stats)
}

// ==================== Main ====================

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "5000"
	}

	// Serve static files
	staticDir := os.Getenv("STATIC_DIR")
	if staticDir == "" {
		staticDir = "."
	}

	mux := http.NewServeMux()

	// API routes
	mux.HandleFunc("/api/search", searchHandler)
	mux.HandleFunc("/api/health", healthHandler)
	mux.HandleFunc("/api/cache", cacheStatsHandler)

	// Static files
	absDir, _ := filepath.Abs(staticDir)
	fs := http.FileServer(http.Dir(absDir))
	mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// API routes already handled above
		if strings.HasPrefix(r.URL.Path, "/api/") {
			http.NotFound(w, r)
			return
		}
		// SPA fallback
		path := filepath.Join(absDir, r.URL.Path)
		if _, err := os.Stat(path); os.IsNotExist(err) {
			http.ServeFile(w, r, filepath.Join(absDir, "index.html"))
			return
		}
		fs.ServeHTTP(w, r)
	}))

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	log.Printf("凌云搜索代理 v2.0 启动 :%s (静态: %s)", port, absDir)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}
