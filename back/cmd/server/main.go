package main

import (
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/go-chi/cors"
	"github.com/javad-moghofei/persian-ocr/back/internal/api"
	"github.com/javad-moghofei/persian-ocr/back/internal/config"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	root, err := os.Getwd()
	if err != nil {
		log.Fatalf("cwd: %v", err)
	}

	srv := api.NewServer(cfg, root)
	router := srv.Routes()

	corsMw := cors.Handler(cors.Options{
		AllowedOrigins:   cfg.CORSOrigins,
		AllowedMethods:   []string{"GET", "POST", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type"},
		AllowCredentials: true,
		MaxAge:           300,
	})

	addr := fmt.Sprintf("%s:%s", cfg.Host, cfg.Port)
	log.Printf("Persian OCR API (stateless, Cursor-only) on %s workspace=%s", addr, root)

	if err := http.ListenAndServe(addr, corsMw(router)); err != nil {
		log.Fatal(err)
	}
}