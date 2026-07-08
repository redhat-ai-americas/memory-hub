package handler_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/fips-agents/gateway-template/internal/handler"
)

func TestWellKnownHandler(t *testing.T) {
	h := &handler.WellKnownHandler{
		AgentName:    "test-agent",
		AgentVersion: "1.2.3",
	}

	req := httptest.NewRequest(http.MethodGet, "/.well-known/agent.json", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("GET /.well-known/agent.json: want status %d, got %d", http.StatusOK, rec.Code)
	}

	ct := rec.Header().Get("Content-Type")
	if ct != "application/json" {
		t.Errorf("GET /.well-known/agent.json: want Content-Type application/json, got %q", ct)
	}

	var card struct {
		Name         string `json:"name"`
		Version      string `json:"version"`
		Description  string `json:"description"`
		Capabilities struct {
			Streaming bool `json:"streaming"`
		} `json:"capabilities"`
		Interfaces []struct {
			Type string `json:"type"`
			URL  string `json:"url"`
		} `json:"interfaces"`
	}

	if err := json.Unmarshal(rec.Body.Bytes(), &card); err != nil {
		t.Fatalf("response is not valid JSON: %v\nbody: %s", err, rec.Body.String())
	}

	tests := []struct {
		field string
		got   string
		want  string
	}{
		{"name", card.Name, "test-agent"},
		{"version", card.Version, "1.2.3"},
	}
	for _, tc := range tests {
		if tc.got != tc.want {
			t.Errorf("field %q: want %q, got %q", tc.field, tc.want, tc.got)
		}
	}

	if !card.Capabilities.Streaming {
		t.Error("capabilities.streaming: want true, got false")
	}

	if card.Description == "" {
		t.Error("description should not be empty")
	}

	if len(card.Interfaces) == 0 {
		t.Fatal("interfaces: want at least one entry, got none")
	}
	if card.Interfaces[0].Type != "openai-chat" {
		t.Errorf("interfaces[0].type: want \"openai-chat\", got %q", card.Interfaces[0].Type)
	}
	if card.Interfaces[0].URL != "/v1/chat/completions" {
		t.Errorf("interfaces[0].url: want \"/v1/chat/completions\", got %q", card.Interfaces[0].URL)
	}
}
