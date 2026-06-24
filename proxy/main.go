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

type SR struct {
	URL      string `json:"url"`
	Note     string `json:"note"`
	Password string `json:"password"`
	DateTime string `json:"datetime"`
}
type SResp struct {
	Code int `json:"code"`
	Data struct {
		MergedByType map[string][]SR `json:"merged_by_type"`
		Total        int             `json:"total"`
	} `json:"data"`
}
type CE struct{ data SResp; t time.Time }
type Stat struct{ Ch, Pl, Ca, Se int; Up string }

var (
	cache   = map[string]*CE{}
	cacheMu sync.RWMutex
	psURL   = "http://localhost:8081/api/search"
	start   = time.Now()
	sc      int
	scMu    sync.Mutex
	chs     []string
	chMu    sync.RWMutex
	plugs   []string
	plugMu  sync.RWMutex
	chFile  = `D:\pansou.env`
	subFile = `D:\proxy\subs.json`
	adFile  = `D:\proxy\ads.json`
	authFile = `D:\proxy\auth.json`
)

func loadChs() {
	b, _ := os.ReadFile(chFile); s := string(b)
	if i := strings.Index(s, "CHANNELS="); i >= 0 {
		s = s[i+9:]
		if e := strings.Index(s, "\n"); e > 0 { s = s[:e] }
		chMu.Lock(); chs = strings.Split(strings.TrimSpace(s), ","); chMu.Unlock()
	}
	if j := strings.Index(string(b), "ENABLED_PLUGINS="); j >= 0 {
		p := string(b)[j+16:]
		if e := strings.Index(p, "\n"); e > 0 { p = p[:e] }
		plugMu.Lock(); plugs = strings.Split(strings.TrimSpace(p), ","); plugMu.Unlock()
	}
}
func saveChs() {
	chMu.RLock(); cl := strings.Join(chs, ","); chMu.RUnlock()
	plugMu.RLock(); pl := strings.Join(plugs, ","); plugMu.RUnlock()
	b, _ := os.ReadFile(chFile); c := string(b)
	if i := strings.Index(c, "CHANNELS="); i >= 0 {
		r := c[i+9:]
		if e := strings.Index(r, "\n"); e > 0 { r = r[e:] }
		c = c[:i+9] + cl + r
	}
	if j := strings.Index(c, "ENABLED_PLUGINS="); j >= 0 {
		r := c[j+16:]
		if e := strings.Index(r, "\n"); e > 0 { r = r[e:] }
		c = c[:j+16] + pl + r
	} else {
		c += "\nENABLED_PLUGINS=" + pl
	}
	os.WriteFile(chFile, []byte(c), 0644)
}

func navlinksAPI(w http.ResponseWriter, r *http.Request) {
	navFile := filepath.Join(filepath.Dir(chFile), "nav.json")
	w.Header().Set("Content-Type", "application/json")
	if r.Method == "GET" {
		b, _ := os.ReadFile(navFile)
		if len(b) == 0 { b = []byte(`[{"text":"🖼️ 图片站","url":"https://img.okva.cc"},{"text":"💬 AI 聊天","url":"https://chat.okva.cc"}]`) }
		w.Write(b)
		return
	}
	if r.Method == "POST" { b, _ := io.ReadAll(r.Body); os.WriteFile(navFile, b, 0644); json.NewEncoder(w).Encode(map[string]string{"ok":"saved"}) }
}

var authSessions = map[string]time.Time{}
var authMu sync.Mutex

func initAuth() {
	if _, err := os.Stat(authFile); os.IsNotExist(err) {
		os.WriteFile(authFile, []byte(`{"password":"admin123"}`), 0644)
	}
}

func checkAuth(w http.ResponseWriter, r *http.Request) bool {
	cookie, _ := r.Cookie("admin_token")
	if cookie == nil { return false }
	authMu.Lock()
	expire, ok := authSessions[cookie.Value]
	authMu.Unlock()
	return ok && time.Now().Before(expire)
}

func loginAPI(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != "POST" { json.NewEncoder(w).Encode(map[string]string{"error":"POST required"}); return }
	var req struct{ Password string `json:"password"` }
	json.NewDecoder(r.Body).Decode(&req)
	b, _ := os.ReadFile(authFile)
	var cfg struct{ Password string `json:"password"` }
	json.Unmarshal(b, &cfg)
	if req.Password != cfg.Password { json.NewEncoder(w).Encode(map[string]string{"error":"密码错误"}); return }
	token := fmt.Sprintf("%x", time.Now().UnixNano())
	authMu.Lock()
	authSessions[token] = time.Now().Add(24 * time.Hour)
	authMu.Unlock()
	http.SetCookie(w, &http.Cookie{Name:"admin_token", Value:token, Path:"/admin", MaxAge:86400, HttpOnly:true})
	json.NewEncoder(w).Encode(map[string]string{"ok":"logged_in"})
}

func authMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !checkAuth(w, r) {
			if strings.HasPrefix(r.URL.Path, "/admin/api/") { w.Header().Set("Content-Type","application/json"); w.WriteHeader(401); json.NewEncoder(w).Encode(map[string]string{"error":"unauthorized"}); return }
			http.Redirect(w, r, "/login.html", 302)
			return
		}
		next(w, r)
	}
}

func loadDeadLinks() map[string]bool {
	dead := map[string]bool{}
	statusFile := filepath.Join(filepath.Dir(chFile), "link_status.json")
	b, _ := os.ReadFile(statusFile)
	var data struct{ Results map[string]struct{ Status string `json:"status"` } `json:"results"` }
	json.Unmarshal(b, &data)
	for url, r := range data.Results {
		if r.Status == "dead" { dead[url] = true }
	}
	return dead
}

func main() {
	loadChs()
	initAuth()
	port := "8080"
	if p := os.Getenv("PORT"); p != "" { port = p }
	sd := "."
	if d := os.Getenv("STATIC_DIR"); d != "" { sd = d }
	abs, _ := filepath.Abs(sd)
	// Ensure data files exist
	for _, f := range []string{subFile, adFile} {
		if _, err := os.Stat(f); os.IsNotExist(err) {
			if strings.Contains(f, "ads") {
				os.WriteFile(f, []byte(`{"title":"🔥 广告位招租","link":"mailto:admin@okva.cc","text":"👉 凌云搜索首页黄金广告位，按周/月计费"}`), 0644)
			} else {
				os.WriteFile(f, []byte(`[]`), 0644)
			}
		}
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/api/search", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Access-Control-Allow-Origin", "*")
		kw := r.URL.Query().Get("kw")
		if len(kw) < 2 { json.NewEncoder(w).Encode(&SResp{Code: 0}); return }
		cacheMu.RLock(); ce, ok := cache[kw]; cacheMu.RUnlock()
		if ok && time.Since(ce.t) < 10*time.Minute { json.NewEncoder(w).Encode(&ce.data); return }
		resp, err := http.Get(fmt.Sprintf("%s?kw=%s", psURL, url.QueryEscape(kw)))
		if err != nil { json.NewEncoder(w).Encode(&SResp{Code: -1}); return }
		defer resp.Body.Close()
		var sr SResp; json.NewDecoder(resp.Body).Decode(&sr)
		// 过滤失效链接
		dead := loadDeadLinks()
		if len(dead) > 0 {
			for t, items := range sr.Data.MergedByType {
				var filtered []SR
				for _, item := range items {
					if !dead[item.URL] { filtered = append(filtered, item) }
				}
				if len(filtered) == 0 { delete(sr.Data.MergedByType, t) } else { sr.Data.MergedByType[t] = filtered }
			}
		}
		cacheMu.Lock(); cache[kw] = &CE{data: sr, t: time.Now()}; cacheMu.Unlock()
		scMu.Lock(); sc++; scMu.Unlock()
		json.NewEncoder(w).Encode(sr)
	})
	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})
	// Admin API
	mux.HandleFunc("/admin/login", loginAPI)
	mux.HandleFunc("/admin/api/stats", func(w http.ResponseWriter, r *http.Request) { if !checkAuth(w,r) { http.Redirect(w,r,"/login.html",302); return }
		chMu.RLock(); ch := len(chs); chMu.RUnlock()
		plugMu.RLock(); pl := len(plugs); plugMu.RUnlock()
		cacheMu.RLock(); cc := len(cache); cacheMu.RUnlock()
		scMu.Lock(); scc := sc; scMu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(Stat{Ch: ch, Pl: pl, Ca: cc, Se: scc, Up: time.Since(start).Round(time.Second).String()})
	})
	mux.HandleFunc("/admin/api/channels", func(w http.ResponseWriter, r *http.Request) { if !checkAuth(w,r) { http.Redirect(w,r,"/login.html",302); return }
		w.Header().Set("Content-Type", "application/json")
		if r.Method == "GET" {
			chMu.RLock(); l := make([]string, len(chs)); copy(l, chs); chMu.RUnlock()
			json.NewEncoder(w).Encode(map[string]interface{}{"items": l, "count": len(l)}); return
		}
		handleListEdit(w, r, &chs, &chMu, saveChs)
	})
	mux.HandleFunc("/admin/api/plugins", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method == "GET" {
			plugMu.RLock(); l := make([]string, len(plugs)); copy(l, plugs); plugMu.RUnlock()
			json.NewEncoder(w).Encode(map[string]interface{}{"items": l, "count": len(l)}); return
		}
		handleListEdit(w, r, &plugs, &plugMu, saveChs)
	})
	mux.HandleFunc("/admin/api/ads", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method == "GET" { b, _ := os.ReadFile(adFile); w.Write(b); return }
		if r.Method == "POST" { b, _ := io.ReadAll(r.Body); os.WriteFile(adFile, b, 0644); json.NewEncoder(w).Encode(map[string]string{"ok":"saved"}) }
	})
	mux.HandleFunc("/admin/api/subs", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method == "GET" { b, _ := os.ReadFile(subFile); w.Write(b); return }
		if r.Method == "POST" { var items []map[string]string; json.NewDecoder(r.Body).Decode(&items); b, _ := json.Marshal(items); os.WriteFile(subFile, b, 0644); json.NewEncoder(w).Encode(map[string]string{"ok":"saved"}) }
	})
	mux.HandleFunc("/admin/api/config", func(w http.ResponseWriter, r *http.Request) {
		cfgFile := filepath.Join(filepath.Dir(chFile), "site_config.json")
		w.Header().Set("Content-Type", "application/json")
		if r.Method == "GET" {
			b, _ := os.ReadFile(cfgFile)
			if len(b) == 0 { b = []byte(`{"name":"凌云搜索","description":"聚合网盘搜索引擎","keywords":"网盘搜索","slogan":"全网网盘链接实现秒级检索，精益求精做最硬核的搜盘神器！","logo":"云"}`) }
			w.Write(b)
			return
		}
		if r.Method == "POST" { b, _ := io.ReadAll(r.Body); os.WriteFile(cfgFile, b, 0644); json.NewEncoder(w).Encode(map[string]string{"ok":"saved"}) }
	})
	mux.HandleFunc("/admin/api/cache/clear", func(w http.ResponseWriter, r *http.Request) {
		cacheMu.Lock(); cache = map[string]*CE{}; cacheMu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"ok":"cleared"})
	})
	mux.HandleFunc("/admin/api/cache/keys", func(w http.ResponseWriter, r *http.Request) {
		cacheMu.RLock(); defer cacheMu.RUnlock()
		var keys []string; for k := range cache { keys = append(keys, k) }
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(keys)
	})
	mux.HandleFunc("/admin/api/restart", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"ok":"restarting"})
		go func() { time.Sleep(500 * time.Millisecond); os.Exit(0) }()
	})
	mux.HandleFunc("/admin/api/password", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method != "POST" { return }
		var req struct{ Old string `json:"old"`; New string `json:"new"` }
		json.NewDecoder(r.Body).Decode(&req)
		b, _ := os.ReadFile(authFile)
		var cfg struct{ Password string `json:"password"` }
		json.Unmarshal(b, &cfg)
		if req.Old != cfg.Password { json.NewEncoder(w).Encode(map[string]string{"error":"旧密码错误"}); return }
		cfg.Password = req.New
		nb, _ := json.Marshal(cfg)
		os.WriteFile(authFile, nb, 0644)
		json.NewEncoder(w).Encode(map[string]string{"ok":"changed"})
	})
	mux.HandleFunc("/admin/api/linkcheck", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		statusFile := filepath.Join(filepath.Dir(chFile), "link_status.json")
		b, _ := os.ReadFile(statusFile)
		if len(b) == 0 { b = []byte(`{"total":0,"ok":0,"dead":0,"results":{}}`) }
		w.Write(b)
	})
	mux.HandleFunc("/admin/api/navlinks", navlinksAPI)
	mux.HandleFunc("/api/navlinks", navlinksAPI)
	// 代理 likeness 应用
	mux.HandleFunc("/likeness/", func(w http.ResponseWriter, r *http.Request) {
		target := r.URL.Path[len("/likeness"):]
		if target == "" { target = "/" }
		proxyURL := "http://localhost:3001" + target + "?" + r.URL.RawQuery
		resp, err := http.Get(proxyURL)
		if err != nil { http.Error(w, "likeness offline", 502); return }
		defer resp.Body.Close()
		for k, v := range resp.Header { for _, vv := range v { w.Header().Add(k, vv) } }
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
	})
	mux.HandleFunc("/admin/", func(w http.ResponseWriter, r *http.Request) {
		if !checkAuth(w, r) { http.Redirect(w, r, "/login.html", 302); return }
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		io.WriteString(w, adminHTML)
	})
	mux.HandleFunc("/admin", func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, "/admin/", 301) })
	fs := http.FileServer(http.Dir(abs))
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		path := r.URL.Path
		if strings.HasPrefix(path, "/api/") || strings.HasPrefix(path, "/admin") || strings.HasPrefix(path, "/likeness") { return }
		fp := filepath.Join(abs, path)
		if info, err := os.Stat(fp); err == nil && !info.IsDir() { fs.ServeHTTP(w, r); return }
		http.ServeFile(w, r, filepath.Join(abs, "index.html"))
	})
	srv := &http.Server{Addr: ":" + port, Handler: mux, ReadTimeout: 15 * time.Second, WriteTimeout: 60 * time.Second}
	log.Printf("凌云 :%s (后台 /admin/)", port)
	log.Fatal(srv.ListenAndServe())
}

func handleListEdit(w http.ResponseWriter, r *http.Request, list *[]string, mu *sync.RWMutex, save func()) {
	if r.Method != "POST" { return }
	var req struct{ Action string `json:"action"`; Items []string `json:"items"` }
	json.NewDecoder(r.Body).Decode(&req)
	if req.Action == "add" {
		mu.Lock(); ex := map[string]bool{}
		for _, c := range *list { ex[c] = true }
		ad := 0
		for _, c := range req.Items { if !ex[c] { *list = append(*list, c); ex[c] = true; ad++ } }
		mu.Unlock(); save()
		json.NewEncoder(w).Encode(map[string]interface{}{"ok": true, "added": ad})
	}
	if req.Action == "delete" {
		mu.Lock(); dl := map[string]bool{}
		for _, c := range req.Items { dl[c] = true }
		var n []string
		for _, c := range *list { if !dl[c] { n = append(n, c) } }
		*list = n; mu.Unlock(); save()
		json.NewEncoder(w).Encode(map[string]interface{}{"ok": true})
	}
}

const adminHTML = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><title>凌云后台</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,sans-serif;background:#f5f6fa;color:#2d3436}
.sb{position:fixed;left:0;top:0;bottom:0;width:180px;background:#1a1a2e;color:#fff;padding:20px 0;z-index:10}
.sb h2{padding:0 18px 16px;font-size:16px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:8px}
.sb a{display:block;padding:8px 18px;color:rgba(255,255,255,.7);text-decoration:none;font-size:13px}
.sb a:hover,.sb a.on{background:rgba(255,255,255,.1);color:#fff}
.mn{margin-left:180px;padding:24px}
.cd{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.st{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px}
.si{background:#fff;border-radius:8px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.si .n{font-size:26px;font-weight:700;color:#1a73e8}.si .l{font-size:12px;color:#999;margin-top:4px}
input,textarea{width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:4px;font-size:14px;margin-bottom:8px;font-family:inherit}
textarea{height:80px;resize:vertical}
.bt{padding:8px 20px;border:none;border-radius:4px;cursor:pointer;font-size:14px}
.bp{background:#1a73e8;color:#fff}.bd{background:#e74c3c;color:#fff}.bg{background:#34a853;color:#fff}
.tg{display:inline-block;padding:3px 10px;background:#e8f0fe;color:#1a73e8;border-radius:12px;font-size:12px;margin:2px;cursor:pointer;word-break:break-all}
.tg:hover{background:#d2e3fc}
.tt{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#2d3436;color:#fff;padding:10px 24px;border-radius:20px;font-size:14px;z-index:999;opacity:0;transition:opacity .3s}
.tt.s{opacity:1}
.mbtn{display:none;position:fixed;top:0;left:0;right:0;height:44px;background:#1a1a2e;color:#fff;z-index:100;align-items:center;padding:0 16px;font-size:14px;cursor:pointer}
.row{display:flex;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #f0f0f0}
.row .info{flex:1;font-size:13px}
@media(max-width:768px){.sb{transform:translateX(-100%);transition:transform .2s}.sb.open{transform:translateX(0)}.mn{margin-left:0!important;padding:52px 12px 12px}.st{grid-template-columns:repeat(2,1fr)}.mbtn{display:flex}}
</style></head><body>
<div class="mbtn" onclick="document.querySelector('.sb').classList.toggle('open')">&#9776; 凌云后台</div>
<div class="sb"><h2>凌云后台</h2>
<a href="#" class="on" data-p="d" onclick="document.querySelector('.sb').classList.remove('open')">📊 仪表盘</a>
<a href="#" data-p="c" onclick="document.querySelector('.sb').classList.remove('open')">📡 频道</a>
<a href="#" data-p="p" onclick="document.querySelector('.sb').classList.remove('open')">🔌 插件</a>
<a href="#" data-p="a" onclick="document.querySelector('.sb').classList.remove('open')">📢 广告</a>
<a href="#" data-p="n" onclick="document.querySelector('.sb').classList.remove('open')">🔗 导航</a>
<a href="#" data-p="s" onclick="document.querySelector('.sb').classList.remove('open')">📮 投稿</a>
<a href="#" data-p="f" onclick="document.querySelector('.sb').classList.remove('open')">⚙ 配置</a>
<a href="#" data-p="x" onclick="document.querySelector('.sb').classList.remove('open')">🗑 缓存</a>
<a href="#" data-p="l" onclick="document.querySelector('.sb').classList.remove('open')">🔗 链接检测</a>
</div><div class="mn" id="mn" onclick="document.querySelector('.sb').classList.remove('open')"></div><div class="tt" id="tt"></div>
<script>
var cv='d',pageData={subs:[]};
var vs={
d:'<div class="st"><div class="si"><div class="n" id="sC">-</div><div class="l">频道</div></div><div class="si"><div class="n" id="sP">-</div><div class="l">插件</div></div><div class="si"><div class="n" id="sA">-</div><div class="l">缓存</div></div><div class="si"><div class="n" id="sS">-</div><div class="l">搜索次数</div></div></div><div class="cd"><h3>⚡ 系统状态</h3><table style="width:100%;font-size:13px"><tr><td style="padding:6px 0;color:#999">运行时间</td><td id="ut">-</td></tr><tr><td style="padding:6px 0;color:#999">后端</td><td>PanSou :8081</td></tr><tr><td style="padding:6px 0;color:#999">缓存TTL</td><td>10分钟</td></tr><tr><td style="padding:6px 0;color:#999">版本</td><td>v5.0</td></tr></table></div><div class="cd"><h3>🔍 最近搜索缓存</h3><div id="recent" style="font-size:12px;color:#999">加载中...</div></div><div class="cd"><h3>📋 快捷操作</h3><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="bt bp" onclick="loadPage(\'c\')">+ 频道</button><button class="bt bp" onclick="loadPage(\'p\')">+ 插件</button><button class="bt bp" onclick="loadPage(\'a\')">📢 广告</button><button class="bt bd" onclick="clC()">清缓存</button></div></div>',
c:'<div class="cd"><h3>添加频道</h3><textarea id="nc" placeholder="每行一个或用逗号分隔"></textarea><button class="bt bp" onclick="addItem(\'channels\',\'nc\')">添加</button></div><div class="cd"><h3>频道列表 (<span id="cN">-</span>)</h3><div id="cL" style="max-height:60vh;overflow-y:auto">...</div></div>',
p:'<div class="cd"><h3>添加插件</h3><textarea id="np" placeholder="每行一个或用逗号分隔"></textarea><button class="bt bp" onclick="addItem(\'plugins\',\'np\')">添加</button></div><div class="cd"><h3>插件列表 (<span id="pN">-</span>)</h3><div id="pL" style="max-height:60vh;overflow-y:auto">...</div></div>',
a:'<div class="cd"><h3>首页广告</h3><input id="aT" placeholder="标题: 🔥 广告位招租"><input id="aL" placeholder="链接: mailto:admin@okva.cc"><textarea id="aB" placeholder="内容: 凌云搜索首页黄金广告位...">'+'</textarea><button class="bt bp" style="margin-top:8px" onclick="saveAd()">保存广告</button></div>',
n:'<div class="cd"><h3>首页导航链接</h3><div id="nL"></div><div class="cd" style="margin-top:12px"><h4>添加链接</h4><input id="nT" placeholder="显示文字: 🖼️ 图片站"><input id="nU" placeholder="链接: https://img.okva.cc"><button class="bt bp" onclick="addNav()">添加</button></div></div>',
s:'<div class="cd"><h3>用户投稿</h3><div id="sL">加载中...</div></div>',
f:'<div class="cd"><h3>站点</h3><input id="nm" placeholder="名称"><input id="ds" placeholder="描述（SEO）"><input id="kw" placeholder="关键词"><input id="slogan" placeholder="首页标语"><input id="lg" placeholder="Logo文字（默认: 云）"><textarea id="footer" placeholder="底部声明" style="height:60px"></textarea><button class="bt bp" style="margin-top:12px" onclick="svCfg()">保存</button></div><div class="cd"><h3>🔒 修改密码</h3><input id="oldPw" type="password" placeholder="旧密码"><input id="newPw" type="password" placeholder="新密码"><button class="bt bp" onclick="chPw()">修改密码</button></div>',
x:'<div class="cd"><h3>缓存</h3><p style="color:#999;margin-bottom:12px">当前: <b id="xC">-</b></p><button class="bt bd" onclick="clC()">清空</button></div>',
l:'<div class="cd"><h3>🔗 链接有效性检测</h3><p style="color:#999;margin-bottom:12px" id="lStat">加载中...</p><button class="bt bp" onclick="runCheck()">开始检测</button><div id="lDetail" style="margin-top:12px;font-size:12px;max-height:50vh;overflow-y:auto"></div></div>'
};
function R(h){document.getElementById('mn').innerHTML=h}
function T(m){var t=document.getElementById('tt');t.textContent=m;t.classList.add('s');setTimeout(function(){t.classList.remove('s')},1800)}
async function api(url,opt){var r=opt?await fetch(url,opt):await fetch(url);return r.json()}
function tags(d,type){var h='';d.items.forEach(function(c){h+='<span class="tg" onclick="delItem(\''+type+'\',\''+c+'\')">'+c+' X</span>'});return h}
async function addItem(type,id){var t=document.getElementById(id).value.trim();if(!t)return;var items=t.split(/[,\n]+/).map(function(s){return s.trim()}).filter(Boolean);var d=await api('/admin/api/'+type,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'add',items:items})});T('+'+d.added);document.getElementById(id).value='';loadPage(cv)}
async function delItem(type,c){if(!confirm(c+'?'))return;await api('/admin/api/'+type,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',items:[c]})});T('ok');loadPage(cv)}
async function lG(){var r=await api('/admin/api/config');var d=await r.json();document.getElementById('nm').value=d.name;document.getElementById('ds').value=d.description;document.getElementById('kw').value=d.keywords;document.getElementById('slogan').value=d.slogan||''}
async function svCfg(){await api('/admin/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.getElementById('nm').value,description:document.getElementById('ds').value,keywords:document.getElementById('kw').value,slogan:document.getElementById('slogan').value,logo:document.getElementById('lg').value,footer:document.getElementById('footer').value})});T('saved')}
async function clC(){if(!confirm('?'))return;await api('/admin/api/cache/clear');T('ok');if(cv==='x')document.getElementById('xC').textContent='0'}
async function chPw(){var old=document.getElementById('oldPw').value;var nw=document.getElementById('newPw').value;if(!old||!nw)return;var d=await api('/admin/api/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old:old,new:nw})});if(d.ok){T('密码已修改');document.getElementById('oldPw').value='';document.getElementById('newPw').value=''}else{T(d.error||'失败')}}
async function loadPage(p){
	cv=p;R(vs[p]);
	document.querySelectorAll('.sb a').forEach(function(a){a.classList.toggle('on',a.dataset.p===p)});
	if(p==='d'){
		var d=await api('/admin/api/stats');
		document.getElementById('sC').textContent=d.Ch;document.getElementById('sP').textContent=d.Pl;
		document.getElementById('sA').textContent=d.Ca;document.getElementById('sS').textContent=d.Se;
		document.getElementById('ut').textContent=d.Up;
		api('/admin/api/cache/keys').then(function(keys){document.getElementById('recent').innerHTML=keys.length?keys.slice(0,10).join(', '):'暂无'});
	}
	if(p==='c'){var d=await api('/admin/api/channels');document.getElementById('cN').textContent=d.count;document.getElementById('cL').innerHTML=tags(d,'channels')}
	if(p==='p'){var d=await api('/admin/api/plugins');document.getElementById('pN').textContent=d.count;document.getElementById('pL').innerHTML=tags(d,'plugins')}
	if(p==='a'){var d=await api('/admin/api/ads');document.getElementById('aT').value=d.title||'';document.getElementById('aL').value=d.link||'';document.getElementById('aB').value=d.text||''}
	if(p==='n'){loadNavs()}
	if(p==='s'){
		var d=await api('/admin/api/subs');pageData.subs=d||[];
		var h=pageData.subs.length?'':'<p style="color:#999">暂无投稿</p>';
		pageData.subs.forEach(function(s,i){h+='<div class="row"><div class="info"><b>'+(s.name||'匿名')+'</b><br><small>'+s.time+'</small><br>'+s.content+'</div><button class="bt bd" onclick="delSub('+i+')">删除</button></div>'});
		document.getElementById('sL').innerHTML=h;
	}
	if(p==='f'){var d=await api('/admin/api/config');document.getElementById('nm').value=d.name;document.getElementById('ds').value=d.description;document.getElementById('kw').value=d.keywords;document.getElementById('slogan').value=d.slogan||'';document.getElementById('lg').value=d.logo||'云';document.getElementById('footer').value=d.footer||''}
	if(p==='x'){api('/admin/api/stats').then(function(d){document.getElementById('xC').textContent=d.Ca})}
	if(p==='l'){loadLinkStatus()}
}
function delSub(i){if(!confirm('删除?'))return;pageData.subs.splice(i,1);api('/admin/api/subs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pageData.subs)}).then(function(){loadPage('s');T('deleted')})}
function restart(){if(!confirm('确定重启代理？'))return;api('/admin/api/restart');T('重启中...');setTimeout(function(){location.reload()},3000)}
async function loadNavs(){var d=await api('/admin/api/navlinks');var h='';d.forEach(function(l,i){h+='<div class="row"><div class="info"><b>'+l.text+'</b> → '+l.url+'</div><button class="bt bp" style="padding:4px 10px;font-size:12px" onclick="editNav('+i+')">编辑</button><button class="bt bd" style="padding:4px 10px;font-size:12px;margin-left:4px" onclick="delNav('+i+')">删除</button></div>'});h||(h='<p style="color:#999">暂无导航链接</p>');document.getElementById('nL').innerHTML=h}
async function addNav(){var t=document.getElementById('nT').value.trim();var u=document.getElementById('nU').value.trim();if(!t||!u)return;var d=await api('/admin/api/navlinks');d.push({text:t,url:u});await api('/admin/api/navlinks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});T('已添加');document.getElementById('nT').value='';document.getElementById('nU').value='';loadNavs()}
async function delNav(i){if(!confirm('删除?'))return;var d=await api('/admin/api/navlinks');d.splice(i,1);await api('/admin/api/navlinks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});T('deleted');loadNavs()}
async function editNav(i){var d=await api('/admin/api/navlinks');var l=d[i];var t=prompt('显示文字',l.text);var u=prompt('链接地址',l.url);if(t&&u){d[i]={text:t,url:u};await api('/admin/api/navlinks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});T('已更新');loadNavs()}}
async function loadLinkStatus(){var d=await api('/admin/api/linkcheck');document.getElementById('lStat').innerHTML='检测 '+d.total+' 个链接 | ✅有效:'+d.ok+' | ❌失效:'+d.dead+' | 更新:'+(d.updated||'')}
function runCheck(){T('后台正在检测，约1分钟...');loadPage('l')}
document.querySelectorAll('.sb a').forEach(function(a){a.onclick=function(e){e.preventDefault();loadPage(this.dataset.p)}});
// 点击页面任意位置关闭侧边栏（移动端）
document.addEventListener('click',function(e){if(window.innerWidth<=768&&!e.target.closest('.sb')&&!e.target.closest('.mbtn'))document.querySelector('.sb').classList.remove('open')});
loadPage('d');
</script></body></html>`
