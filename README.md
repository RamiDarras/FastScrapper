<p align="center">
  <h1 align="center">🕷️ FastScrapper</h1>
  <p align="center">
    <strong>Open-source web scraper with Cloudflare bypass, background polling, and REST API</strong><br>
    <small>Expose any web page content to your API with ease</small>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
    <img src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
    <img src="https://img.shields.io/badge/anti--bot-Nodriver-orange" alt="Nodriver">
  </p>
</p>

---

## ✨ Features

- **🛡️ Cloudflare Bypass** — Uses [Nodriver](https://github.com/ultrafunkamsterdam/nodriver) (stealth Chrome via CDP) to bypass Cloudflare, Turnstile, and other anti-bot protections
- **⚡ Dual Scraping Modes** — Stealth browser for protected sites, lightweight `httpx` + BeautifulSoup for simple ones
- **🔄 Background Polling** — Automatically scrapes targets at configurable intervals using APScheduler
- **📡 REST API** — FastAPI-powered JSON API with API key auth and auto-generated Swagger docs
- **🔁 Smart Retries** — Exponential backoff with jitter on failures
- **🐳 Docker Ready** — One-command deployment with `docker compose`

---

## 📋 Prerequisites

> [!IMPORTANT]
> **Chromium or Google Chrome must be installed** for stealth mode (`use_stealth: true`).
> Without a browser binary, stealth scraping will fail.

### Install Chromium (Linux)

```bash
# Debian / Ubuntu
sudo apt install chromium-browser

# or Google Chrome
sudo apt install google-chrome-stable

# Arch
sudo pacman -S chromium

# Fedora
sudo dnf install chromium
```

### Install Chromium (macOS)

```bash
brew install --cask chromium
```

> [!TIP]
> If Chromium is installed at a non-standard path, set the `CHROME_PATH` environment variable
> or use `browser_executable_path` in your target config.

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/RamiDarras/FastScrapper.git
cd FastScrapper
pip install -r requirements.txt
```

### 2. Configure

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml` — set your target URLs, selectors, and a strong API key.

### 3. Run

```bash
python main.py
```

The API is now live at **http://localhost:8000** — Swagger docs at [/docs](http://localhost:8000/docs).

---

## 🐳 Docker

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your settings

docker compose up -d
```

Scraped data and logs are persisted via volume mounts.

---

## ⚙️ Configuration Reference

The config file (`config.yaml`) controls everything. Copy from `config.example.yaml` and customize.

### Global Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `server_host` | string | `"0.0.0.0"` | API bind address |
| `server_port` | int | `8000` | API bind port |
| `api_key` | string | **required** | API key for all `/api/*` endpoints (min 8 chars) |
| `log_level` | string | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `data_dir` | string | `"data"` | Directory for scraped data JSON files |
| `max_retries` | int | `3` | Retry attempts per failed scrape (1–10) |
| `retry_delay` | int | `5` | Base retry delay in seconds, doubles each retry |

### Target Settings

Each target in the `targets` list represents one page to scrape:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `name` | string | **required** | Unique identifier (alphanumeric, `-`, `_` only) |
| `url` | string | **required** | URL to scrape |
| `interval` | int | `300` | Seconds between polls (min 10) |
| `use_stealth` | bool | `true` | `true` = Nodriver (browser), `false` = httpx (lightweight) |
| `headless` | bool | `false` | Browser visibility — see [Headless vs Headed](#-headless-vs-headed-mode) |
| `timeout` | int | `30` | Page load timeout in seconds (5–300) |
| `wait_for_selector` | string | — | XPath/CSS selector to wait for before scraping (Nodriver only) |
| `enabled` | bool | `true` | Set to `false` to skip this target |
| `proxy` | string | — | Proxy URL, e.g. `"http://proxy:8080"` |
| `headers` | dict | — | Custom HTTP headers (httpx mode only) |
| `browser_executable_path` | string | — | Explicit path to Chrome/Chromium binary |

### Selector Settings

Each target has one or more `selectors` that define what to extract:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `selector` | string | **required** | CSS selector, element ID, or class name |
| `selector_type` | string | `"css"` | `css`, `xpath`, `id`, or `class` |
| `param` | string | **required** | Key name in the API response JSON |
| `content_mode` | string | `"text"` | `text`, `inner_html`, or `outer_html` |
| `attribute` | string | — | HTML attribute to extract (e.g. `"href"`). Omit for text content |
| `multiple` | bool | `false` | `true` = return array of all matches |
| `default` | string | — | Fallback value if element is missing. If omitted, missing elements cause an error |

---

## 📖 Config Example (Explained)

```yaml
targets:
  # ── Stealth target (Cloudflare-protected site) ─────────────────
  - name: "example_product"               # unique ID for API + filenames
    url: "https://example.com/product/123" # page to scrape
    interval: 300                          # poll every 5 minutes
    use_stealth: true                      # use real Chrome browser (Nodriver)
    headless: false                        # show browser window (better CF bypass)
    timeout: 30                            # give page 30s to load
    selectors:
      - selector: "price-tag"              # look for <div id="price-tag">
        selector_type: "id"                # interpret as element ID
        param: "price"                     # store as {"price": "..."} in API
        default: "N/A"                     # if element missing → return "N/A"

      - selector: "h1.product-title"       # CSS selector for <h1 class="product-title">
        selector_type: "css"
        param: "title"                     # no default → error if not found

      - selector: "div.stock-status"
        selector_type: "css"
        param: "in_stock"
        attribute: "data-available"        # extract attribute value, not text

  # ── Simple target (no anti-bot protection) ─────────────────────
  - name: "news_headlines"
    url: "https://example-news.com"
    interval: 600                          # poll every 10 minutes
    use_stealth: false                     # lightweight httpx + BeautifulSoup
    timeout: 15
    selectors:
      - selector: "article h2"
        selector_type: "css"
        param: "headlines"
        multiple: true                     # return ALL matching elements as array

      - selector: "article a"
        selector_type: "css"
        param: "links"
        multiple: true
        attribute: "href"                  # extract href from each <a> tag

# ── Server ────────────────────────────────────────────────────────
server_host: "0.0.0.0"
server_port: 8000
api_key: "change-me-to-a-strong-secret"   # ⚠️ CHANGE THIS! (min 8 chars)
log_level: "INFO"                          # use "DEBUG" for troubleshooting
data_dir: "data"
max_retries: 3
retry_delay: 5                             # 5s → 10s → 20s exponential backoff
```

---

## 🖥️ Headless vs Headed Mode

> [!WARNING]
> **Cloudflare-protected sites usually fail in headless mode** because Cloudflare detects headless Chrome.

| Mode | `headless` | Best for |
|------|-----------|----------|
| **Headed** (default) | `false` | Cloudflare-protected sites — a browser window briefly pops up, passes the challenge, then closes |
| **Headless** | `true` | Simple sites without anti-bot protection, or servers with no display |

```yaml
# Cloudflare site — use headed mode (default)
- name: "protected_site"
  use_stealth: true
  headless: false       # browser window will pop up briefly

# Simple site — headless is fine
- name: "simple_site"
  use_stealth: true
  headless: true        # no window, runs in background
```

> [!TIP]
> For servers without a display, you can use `xvfb` (virtual framebuffer) to run headed mode:
> ```bash
> sudo apt install xvfb
> xvfb-run python main.py
> ```

---

## 📡 API Endpoints

All `/api/*` endpoints require the `X-API-Key` header.

### `GET /` — Info (no auth)

```bash
curl http://localhost:8000/
```
```json
{ "name": "Ultimate Web Scraper", "version": "0.1.0", "docs": "/docs" }
```

### `GET /api/health` — Health Check

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/api/health
```
```json
{
  "status": "healthy",
  "uptime_seconds": 3600.5,
  "active_targets": 2,
  "total_scrapes": 24,
  "last_scrape": "2026-02-12T12:00:00"
}
```

### `GET /api/targets` — List Targets

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/api/targets
```
```json
{
  "targets": [
    {
      "name": "example_product",
      "url": "https://example.com/product/123",
      "enabled": true,
      "interval": 300,
      "use_stealth": true,
      "total_scrapes": 12,
      "successful_scrapes": 11,
      "failed_scrapes": 1,
      "last_scrape": "2026-02-12T12:00:00"
    }
  ],
  "total": 1
}
```

### `GET /api/data/{target_name}` — Get Scraped Data

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/api/data/example_product
```
```json
{
  "target_name": "example_product",
  "url": "https://example.com/product/123",
  "timestamp": "2026-02-12T12:00:00",
  "success": true,
  "data": {
    "price": "$29.99",
    "title": "Example Product",
    "in_stock": "true"
  },
  "error": null,
  "scrape_duration_ms": 4523
}
```

### Authentication

```bash
# ✅ Valid key
curl -H "X-API-Key: your-key" http://localhost:8000/api/health

# ❌ Missing or wrong key → 401 Unauthorized
curl http://localhost:8000/api/health
```

---

## 🔧 Troubleshooting

| Problem | Solution |
|---------|----------|
| `could not find a valid chrome browser binary` | Install Chromium: `sudo apt install chromium-browser` |
| Cloudflare challenge never clears | Set `headless: false` (default) — headless Chrome is detected by Cloudflare |
| Element returns `"N/A"` (default) | Set `log_level: "DEBUG"` and check logs — the selector might not match the actual page |
| `401 Unauthorized` on API calls | Include `X-API-Key: your-key` header matching the `api_key` in config |
| Scrapes timeout on slow pages | Increase the target's `timeout` value (max 300 seconds) |
| Running on a headless server | Use `xvfb-run python main.py` for headed mode without a display |

---

## 📄 License

MIT License — see [LICENSE](LICENSE).
