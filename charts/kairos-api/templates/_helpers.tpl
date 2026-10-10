{{- define "kairos.name" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "kairos.selectorLabels" -}}
app.kubernetes.io/name: kairos-api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "kairos.labels" -}}
{{ include "kairos.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}
