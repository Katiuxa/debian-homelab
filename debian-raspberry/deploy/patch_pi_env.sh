#!/usr/bin/env bash
# Variables .env optimizadas para Raspberry (admin). Idempotente.
set -eu
cd "$(dirname "$0")/.."
touch .env

set_kv() {
  local k="$1" v="$2"
  sed -i "/^${k}=/d" .env 2>/dev/null || true
  printf '%s=%s\n' "$k" "$v" >> .env
}

# Pi: sin cookies del navegador (no hay Edge/Chrome)
set_kv YTDLP_BROWSER ""
set_kv RESTORE_SPANISH_ORTHO 1
set_kv WHISPER_USE_PROMPT 0
set_kv GROQ_WHISPER_MODEL whisper-large-v3-turbo
set_kv FAST_POLISH 1
set_kv YTDLP_CONCURRENT_FRAGMENTS 4
set_kv FFMPEG_THREADS 2
set_kv AUDIO_CHUNK_SEC 600
set_kv TRANSCRIBE_PARALLEL_CHUNKS 6
set_kv TRANSCRIBE_GROQ_ONLY 1
# YouTube largo: solo audio, sin cortar al ~48 %
set_kv MAX_YOUTUBE_DOWNLOAD_MB 280
set_kv MAX_YOUTUBE_DURATION_SEC 18000
set_kv YTDLP_JOB_TIMEOUT_SEC 3600
set_kv YTDLP_SOCKET_TIMEOUT 60

echo "[OK] .env Pi (YouTube + Groq):"
grep -E '^(FAST_POLISH|RESTORE_SPANISH|WHISPER_USE|GROQ_WHISPER|MAX_YOUTUBE|YTDLP_|TRANSCRIBE_|AUDIO_CHUNK|FFMPEG_THREADS|YTDLP_BROWSER)=' .env || true
