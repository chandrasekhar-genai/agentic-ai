{{- define "aiops-agent.name" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aiops-agent.labels" -}}
app.kubernetes.io/name: aiops-agent
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "aiops-agent.selector" -}}
app.kubernetes.io/name: aiops-agent
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
