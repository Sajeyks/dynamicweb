{{- define "dw.image" -}}{{ .Values.image.repository }}:{{ .Values.image.tag }}{{- end -}}
{{- define "dw.pod" -}}
enableServiceLinks: false   # else a Service named "postgres" injects POSTGRES_PORT=tcp://...
{{- end -}}
