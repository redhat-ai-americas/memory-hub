{{/* Common labels shared by resources emitted by this chart. */}}
{{- define "memoryhub.labels" -}}
app.kubernetes.io/name: memoryhub
app.kubernetes.io/part-of: memoryhub
app.kubernetes.io/component: platform
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
{{- end -}}

{{/* Labels used by a workload and its matching Service selector. */}}
{{- define "memoryhub.componentLabels" -}}
app.kubernetes.io/name: {{ .component | quote }}
app.kubernetes.io/instance: {{ .root.Release.Name | quote }}
app.kubernetes.io/part-of: memoryhub
app.kubernetes.io/component: {{ .component | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service | quote }}
{{- end -}}

{{/* Render an image with either a tag or a pinned digest. */}}
{{- define "memoryhub.imageRef" -}}
{{- if .digest -}}
{{ printf "%s@%s" .repository .digest }}
{{- else -}}
{{ printf "%s:%s" .repository .tag }}
{{- end -}}
{{- end -}}

{{/* Optional pull credentials; every referenced Secret must exist per namespace. */}}
{{- define "memoryhub.imagePullSecrets" -}}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{/* Fully qualified in-cluster Service DNS name using the cluster's DNS domain. */}}
{{- define "memoryhub.serviceDNS" -}}
{{- printf "%s.%s.svc.%s" .name .namespace .domain -}}
{{- end -}}

{{- /*
  memoryhub.namespaceShouldRender — returns "true" (string) when this release
  should render the Namespace manifest; returns "" otherwise.

  Callers MUST use the pattern:
    (include "memoryhub.namespaceShouldRender" ... | trim) == "true"
  because Helm's `and` returns the last truthy value as a string, not a Go bool.
  Omitting the trim+eq check will misfire on namespaces owned by this release.
*/ -}}
{{- define "memoryhub.namespaceShouldRender" -}}
{{- $existing := lookup "v1" "Namespace" "" .name -}}
{{- if not $existing -}}
true
{{- else -}}
{{- $metadata := get $existing "metadata" | default dict -}}
{{- $annotations := get $metadata "annotations" | default dict -}}
{{- and
  (eq (get $annotations "meta.helm.sh/release-name" | default "") .root.Release.Name)
  (eq (get $annotations "meta.helm.sh/release-namespace" | default "") .root.Release.Namespace)
-}}
{{- end -}}
{{- end -}}
