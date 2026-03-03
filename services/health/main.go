package main

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

// Кэш метрик — обновляется раз в 30 секунд, не дёргает БД на каждый запрос
type metricsCache struct {
	mu        sync.RWMutex
	data      metricsData
	updatedAt time.Time
	ttl       time.Duration
}

type metricsData struct {
	Users             int `json:"users"`
	Chats             int `json:"chats"`
	Punishments       int `json:"punishments"`
	ActivePunishments int `json:"active_punishments"`
}

var cache = &metricsCache{ttl: 30 * time.Second}

func (c *metricsCache) get(db *sql.DB) metricsData {
	c.mu.RLock()
	if time.Since(c.updatedAt) < c.ttl {
		data := c.data
		c.mu.RUnlock()
		return data
	}
	c.mu.RUnlock()

	c.mu.Lock()
	defer c.mu.Unlock()

	// Повторная проверка — может другой горутин уже обновил
	if time.Since(c.updatedAt) < c.ttl {
		return c.data
	}

	var d metricsData
	_ = db.QueryRow("SELECT COUNT(*) FROM users").Scan(&d.Users)
	_ = db.QueryRow("SELECT COUNT(*) FROM chats").Scan(&d.Chats)
	_ = db.QueryRow("SELECT COUNT(*) FROM punishments").Scan(&d.Punishments)
	_ = db.QueryRow("SELECT COUNT(*) FROM punishments WHERE active = 1").Scan(&d.ActivePunishments)

	c.data = d
	c.updatedAt = time.Now()
	return d
}

func main() {
	dbPath := os.Getenv("DATABASE_PATH")
	if dbPath == "" {
		dbPath = "/data/app.db"
	}

	port := os.Getenv("HEALTH_PORT")
	if port == "" {
		port = "9090"
	}

	// Открываем SQLite в read-only — не мешаем Python-процессам писать
	dsn := "file:" + dbPath + "?mode=ro&_journal_mode=WAL&_busy_timeout=5000"
	db, err := sql.Open("sqlite3", dsn)
	if err != nil {
		log.Fatalf("не удалось открыть БД: %v", err)
	}
	defer db.Close()

	db.SetMaxOpenConns(2)
	db.SetMaxIdleConns(1)

	// Health — простая проверка доступности БД
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		var n int
		err := db.QueryRow("SELECT 1").Scan(&n)
		if err != nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(map[string]any{
				"status": "degraded",
				"db":     false,
			})
			return
		}

		json.NewEncoder(w).Encode(map[string]any{
			"status": "ok",
			"db":     true,
		})
	})

	// Метрики — счётчики с кэшем 30 сек
	http.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		data := cache.get(db)
		json.NewEncoder(w).Encode(data)
	})

	// Readiness — проверка что Python-сервисы доступны
	http.HandleFunc("/readiness", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		webOk := checkHTTP("http://localhost:8000/health")
		var n int
		dbOk := db.QueryRow("SELECT 1").Scan(&n) == nil

		status := "ok"
		code := http.StatusOK
		if !webOk || !dbOk {
			status = "degraded"
			code = http.StatusServiceUnavailable
		}

		w.WriteHeader(code)
		json.NewEncoder(w).Encode(map[string]any{
			"status": status,
			"db":     dbOk,
			"web":    webOk,
		})
	})

	log.Printf("health-сервис запущен на :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, nil))
}

func checkHTTP(url string) bool {
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}
