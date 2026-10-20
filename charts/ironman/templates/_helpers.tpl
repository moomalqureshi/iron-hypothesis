{{- define "ironman.env" -}}
- name: POSTGRES_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ .Values.secretName }}, key: POSTGRES_PASSWORD}}
- name: IRONMAN_DATABASE_URL
  value: postgresql://ironman:$(POSTGRES_PASSWORD)@postgres:5432/ironman
- name: IRONMAN_REDIS_URL
  value: redis://redis:6379/0
{{- range $k, $v := .Values.env }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- range $k := list "IRONMAN_SECRET_KEY" "IRONMAN_PSEUDONYM_KEY" "IRONMAN_STRAVA_CLIENT_ID" "IRONMAN_STRAVA_CLIENT_SECRET" "IRONMAN_STRAVA_VERIFY_TOKEN" "IRONMAN_LLM_API_KEY" "IRONMAN_TOKEN_ENC_KEY" }}
- name: {{ $k }}
  valueFrom: {secretKeyRef: {name: {{ $.Values.secretName }}, key: {{ $k }}, optional: true}}
{{- end }}
{{- end }}

{{- define "ironman.waitForDb" -}}
- name: wait-db
  image: {{ .Values.image.app }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  command: [python, -c, "import socket,time,sys\nfor _ in range(90):\n    try: socket.create_connection(('postgres',5432),2).close(); sys.exit(0)\n    except OSError: time.sleep(2)\nsys.exit(1)"]
{{- end }}
