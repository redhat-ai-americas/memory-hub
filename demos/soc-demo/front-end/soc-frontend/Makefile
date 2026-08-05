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
PACE      ?= 4

.PHONY: deploy build url replay logs clean

deploy:
	-@oc new-project $(NAMESPACE) 2>/dev/null || oc project $(NAMESPACE)
	oc apply -n $(NAMESPACE) -k manifests/
	oc start-build $(APP) -n $(NAMESPACE) --from-dir=. --follow
	oc rollout status deploy/$(APP) -n $(NAMESPACE) --timeout=180s
	@echo ""
	@echo "  display: https://$$(oc get route $(APP) -n $(NAMESPACE) -o jsonpath='{.spec.host}')"
	@echo "  feed it: make replay"

build:
	oc start-build $(APP) -n $(NAMESPACE) --from-dir=. --follow

url:
	@echo https://$$(oc get route $(APP) -n $(NAMESPACE) -o jsonpath='{.spec.host}')

replay:
	python replay.py --server https://$$(oc get route $(APP) -n $(NAMESPACE) -o jsonpath='{.spec.host}') --pace $(PACE)

logs:
	oc logs -f deploy/$(APP) -n $(NAMESPACE)

clean:
	oc delete -n $(NAMESPACE) -k manifests/ --ignore-not-found
