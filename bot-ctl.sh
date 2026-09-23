#!/usr/bin/env bash
# Botni boshqarish: ./bot-ctl.sh start|stop|restart|status|log|test
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bot_pids() {
    local pid argv
    for p in /proc/[0-9]*; do
        pid=${p#/proc/}
        [ -r "$p/cmdline" ] || continue
        mapfile -d '' -t argv < "$p/cmdline" 2>/dev/null || continue
        [ "${#argv[@]}" -ge 2 ] || continue
        [[ "${argv[0]}" == */venv/bin/python* ]] || continue
        [[ "${argv[1]}" == *bot.py ]] || continue
        echo "$pid"
    done
}

case "${1:-status}" in
  status)
      pids=$(bot_pids)
      if [ -n "$pids" ]; then
          echo "🟢 Bot ishlayapti (PID: $pids)"
          ps -o pid,etime,rss,cmd -p $pids --no-headers 2>/dev/null
      else
          echo "🔴 Bot ishlamayapti"
      fi
      crontab -l 2>/dev/null | grep -q keepalive.sh \
          && echo "⏱  cron nazorati: YOQILGAN (har daqiqada tekshiradi)" \
          || echo "⏱  cron nazorati: o'chiq"
      ;;
  start)
      "$DIR/keepalive.sh" & disown
      sleep 3; "$0" status ;;
  stop)
      pids=$(bot_pids)
      [ -z "$pids" ] && { echo "Bot allaqachon to'xtagan."; exit 0; }
      kill $pids; sleep 2
      pids=$(bot_pids); [ -n "$pids" ] && kill -9 $pids
      echo "⏹ To'xtatildi." ;;
  restart)
      "$0" stop; sleep 1; "$0" start ;;
  log)
      tail -f "$DIR/bot.log" ;;
  test)
      T=$(mktemp -d)
      DB_PATH="$T/test.db" "$DIR/venv/bin/python" -u "$DIR/tests/test_bot.py"
      rc=$?; rm -rf "$T"; exit $rc ;;
  *)
      echo "Foydalanish: $0 {start|stop|restart|status|log|test}" ;;
esac
