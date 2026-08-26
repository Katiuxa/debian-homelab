#!/usr/bin/env bash
# Inyecta variables de transcripcion en .env de la Pi.
# GROQ_API_KEY debe existir en el entorno (nunca hardcodear la clave).
set -eu
: "${GROQ_API_KEY:?Define GROQ_API_KEY antes de ejecutar este script}"
cd /home/admin/MetavideoToText_bot
touch .env
sed -i '/^GROQ_API_KEY=/d;/^TRANSCRIBE_GROQ_ONLY=/d;/^TRANSCRIBE_PARALLEL_CHUNKS=/d;/^AUDIO_CHUNK_SEC=/d;/^FFMPEG_THREADS=/d;/^YTDLP_BROWSER=/d;/^YTDLP_JOB_TIMEOUT_SEC=/d;/^FAST_POLISH=/d;/^YTDLP_CONCURRENT_FRAGMENTS=/d;/^MAX_YOUTUBE_DOWNLOAD_MB=/d' .env
cat >> .env <<EOF
YTDLP_JOB_TIMEOUT_SEC=3600
GROQ_API_KEY=${GROQ_API_KEY}
TRANSCRIBE_GROQ_ONLY=1
TRANSCRIBE_PARALLEL_CHUNKS=6
AUDIO_CHUNK_SEC=600
FFMPEG_THREADS=2
FAST_POLISH=1
YTDLP_CONCURRENT_FRAGMENTS=4
MAX_YOUTUBE_DOWNLOAD_MB=280
YTDLP_BROWSER=
GROQ_WHISPER_MODEL=whisper-large-v3-turbo
EOF
bash deploy/patch_pi_env.sh
echo "[OK] .env actualizado (clave no se imprime)"
grep -E '^TRANSCRIBE_|^AUDIO_|^FFMPEG' .env
sudo systemctl restart metavideototext-bot
sleep 2
echo "[*] Estado:"
systemctl is-active metavideototext-bot
