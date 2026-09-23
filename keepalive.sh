#!/usr/bin/env bash
# Botni doimo bitta nusxada ishlatib turadi (cron har daqiqada chaqiradi).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$DIR/bot.log"
cd "$DIR" || exit 1

# log 10 MB dan oshsa qisqartiramiz
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 10485760 ]; then
    tail -c 2000000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
fi

# flock: agar bot allaqachon ishlayotgan bo'lsa, darhol chiqadi
exec /usr/bin/flock -n "$DIR/bot.lock" "$DIR/venv/bin/python" "$DIR/bot.py" >> "$LOG" 2>&1
