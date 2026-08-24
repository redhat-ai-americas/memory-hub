# MemoryHub SOC demo frontend — deploy to OpenShift
#
#   make deploy              # project + manifests + in-cluster build + rollout
#   make replay              # feed the scripted scenario to the deployed app (4s pace)
#   make replay PACE=0       # burst mode: presenter steps through with SPACE
#
# The namespace is baked into manifests/ (kustomization namespace + the
# deployment's internal-registry image path). If you change NAMESPACE here,
# change it in those two places too.

NAMESPACE ?= soc-demo
APP       := soc-frontend
HARNESS   := soc-harness
PACE      ?= 4
CTX       ?= mcp-rhoai

.PHONY: deploy deploy-all build sidecar-build url replay logs logs-harness secret clean

deploy:
	-@oc new-project $(NAMESPACE) --context $(CTX) 2>/dev/null || true
	oc apply -n $(NAMESPACE) --context $(CTX) -k manifests/
	oc start-build $(APP) -n $(NAMESPACE) --context $(CTX) --from-dir=. --follow
	oc rollout status deploy/$(APP) -n $(NAMESPACE) --context $(CTX) --timeout=180s
	@echo ""
	@echo "  display: https://$$(oc get route $(APP) -n $(NAMESPACE) --context $(CTX) -o jsonpath='{.spec.host}')"

sidecar-build:
	@rm -rf .sidecar-stage
	@mkdir .sidecar-stage
	cp sidecar/Containerfile sidecar/trigger.py sidecar/run-live.sh \
	   sidecar/requirements.txt .sidecar-stage/
	cp ../../harness.py ../../seed-memories.py .sidecar-stage/
	cp replay.py scenario.json .sidecar-stage/
	oc start-build $(HARNESS) -n $(NAMESPACE) --context $(CTX) \
	   --from-dir=.sidecar-stage --follow
	@rm -rf .sidecar-stage

deploy-all: deploy sidecar-build
	oc rollout restart deploy/$(APP) -n $(NAMESPACE) --context $(CTX)
	oc rollout status deploy/$(APP) -n $(NAMESPACE) --context $(CTX) --timeout=180s
	@echo ""
	@echo "  display: https://$$(oc get route $(APP) -n $(NAMESPACE) --context $(CTX) -o jsonpath='{.spec.host}')"
	@echo "  buttons: REPLAY and LIVE available on the standby screen"

build:
	oc start-build $(APP) -n $(NAMESPACE) --context $(CTX) --from-dir=. --follow

url:
	@echo https://$$(oc get route $(APP) -n $(NAMESPACE) --context $(CTX) -o jsonpath='{.spec.host}')

replay:
	python replay.py --server https://$$(oc get route $(APP) -n $(NAMESPACE) --context $(CTX) -o jsonpath='{.spec.host}') --pace $(PACE)

logs:
	oc logs -f deploy/$(APP) -c $(APP) -n $(NAMESPACE) --context $(CTX)

logs-harness:
	oc logs -f deploy/$(APP) -c $(HARNESS) -n $(NAMESPACE) --context $(CTX)

secret:
	@echo "Create the soc-harness-config secret:"
	@echo ""
	@echo "  oc create secret generic soc-harness-config -n $(NAMESPACE) --context $(CTX) \\"
	@echo "    --from-literal=soc-forensics-url=https://YOUR_FIPS_AGENT_ROUTE \\"
	@echo "    --from-literal=memoryhub-url=https://YOUR_MEMORYHUB_URL \\"
	@echo "    --from-literal=memoryhub-api-key=YOUR_API_KEY"

clean:
	oc delete -n $(NAMESPACE) --context $(CTX) -k manifests/ --ignore-not-found
