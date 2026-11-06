# Run on the NAS: start wrapper server, take screenshots, stop server.
#   sh shoot.sh                                  -> Homepage at monitor/laptop/phone sizes
#   sh shoot.sh URL name:W,H [name:W,H ...]      -> any page, custom sizes
cd ~/shot
URL=${1:-http://192.168.1.14:3001/}; [ $# -gt 0 ] && shift
SPECS=${*:-monitor:1920,1080 laptop:1800,1125 phone:400,860}
printf '%s\n' 'user_pref("dom.image-lazy-loading.enabled", false);' 'user_pref("layout.css.prefers-color-scheme.content-override", 0);' 'user_pref("ui.systemUsesDarkTheme", 1);' 'user_pref("webgl.force-enabled", true);'  > user.js   # load all icons; dark mode like the user's browser
python3 shotserver.py 18999 "$URL" & PID=$!
sleep 1
for spec in $SPECS; do
  name=${spec%%:*}; size=${spec#*:}
  docker exec firefox-app-1 sh -c "rm -rf /tmp/sp && mkdir -p /tmp/sp"
  docker cp user.js firefox-app-1:/tmp/sp/user.js
  docker exec firefox-app-1 sh -c "timeout 90 firefox --headless --no-remote --profile /tmp/sp --window-size=$size --screenshot /tmp/$name.png http://192.168.1.14:18999/ >/dev/null 2>&1"
  docker exec firefox-app-1 cat /tmp/$name.png > ~/shot/$name.png
done
kill $PID
