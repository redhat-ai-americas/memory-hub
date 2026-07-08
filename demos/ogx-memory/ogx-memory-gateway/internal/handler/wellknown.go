package handler

import (
	"encoding/json"
	"net/http"
)

// WellKnownHandler serves the /.well-known/agent.json agent card.
type WellKnownHandler struct {
	AgentName    string
	AgentVersion string
}

type agentCard struct {
	Name         string       `json:"name"`
	Version      string       `json:"version"`
	Description  string       `json:"description"`
	Capabilities capabilities `json:"capabilities"`
	Interfaces   []iface      `json:"interfaces"`
}

type capabilities struct {
	Streaming bool `json:"streaming"`
}

type iface struct {
	Type string `json:"type"`
	URL  string `json:"url"`
}

func (h *WellKnownHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	card := agentCard{
		Name:        h.AgentName,
		Version:     h.AgentVersion,
		Description: "OpenAI-compatible HTTP gateway for AI agents",
		Capabilities: capabilities{
			Streaming: true,
		},
		Interfaces: []iface{
			{Type: "openai-chat", URL: "/v1/chat/completions"},
		},
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(card)
}
