PROJECT       ?= ui-template
RELEASE_NAME  ?= ui-template
IMAGE_NAME    ?= ui-template
IMAGE_TAG     ?= latest
PORT          ?= 3000

.PHONY: build run test lint image-build build-openshift deploy clean help

build: ## Build the UI server binary
	go build -o bin/server ./cmd/server

run: ## Run locally
	API_URL=$${API_URL:-http://localhost:8080} go run ./cmd/server

test: ## Run tests
	go test ./... -v

lint: ## Run go vet
	go vet ./...

image-build: ## Build container image
	podman build --platform linux/amd64 -t $(IMAGE_NAME):$(IMAGE_TAG) -f Containerfile . --no-cache

build-openshift: ## Build on OpenShift via BuildConfig (make build-openshift PROJECT=<ns>)
	@if ! oc get bc $(IMAGE_NAME) -n $(PROJECT) &>/dev/null; then \
		echo "Creating BuildConfig and ImageStream $(IMAGE_NAME) in $(PROJECT)..."; \
		sed 's/PLACEHOLDER/$(IMAGE_NAME)/g' build/buildconfig.yaml | oc apply -n $(PROJECT) -f -; \
	fi
	oc start-build $(IMAGE_NAME) --from-dir=. -n $(PROJECT) --follow

deploy: ## Deploy to OpenShift via Helm (make deploy PROJECT=<ns>)
	helm upgrade --install $(RELEASE_NAME) chart/ \
		-n $(PROJECT) \
		--set image.repository=image-registry.openshift-image-registry.svc:5000/$(PROJECT)/$(IMAGE_NAME) \
		--set image.tag=$(IMAGE_TAG) \
		--wait

clean: ## Remove build artifacts
	rm -rf bin/

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
