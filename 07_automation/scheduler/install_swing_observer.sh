#!/bin/sh
# Installs only the public-only, zero-capital review-window observer.
set -eu
runtime_root=/Users/messssi/LocalRuntime/equity
observer_label=com.steven.equity_research.swingobserver
observer_domain="gui/$(id -u)"
observer_template="$runtime_root/07_automation/scheduler/$observer_label.plist.template"
observer_target="$HOME/Library/LaunchAgents/$observer_label.plist"
if [ "${1:-}" = "--remove" ]; then
  /bin/launchctl bootout "$observer_domain/$observer_label" 2>/dev/null || true
  if [ -f "$observer_target" ]; then /bin/rm "$observer_target"; fi
  exit 0
fi
if [ "$#" -ne 0 ]; then
  echo 'Usage: install_swing_observer.sh [--remove]' >&2
  exit 2
fi
/usr/bin/plutil -lint "$observer_template"
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 "$runtime_root/09_scripts/equity_research/run_swing_observer.py" --root "$runtime_root" --check
/bin/mkdir -p "$HOME/Library/LaunchAgents"
observer_temp=$(mktemp "$HOME/Library/LaunchAgents/.swing-observer.XXXXXX")
trap '/bin/rm -f "$observer_temp"' EXIT HUP INT TERM
/bin/cp "$observer_template" "$observer_temp"
/bin/chmod 600 "$observer_temp"
/bin/launchctl bootout "$observer_domain/$observer_label" 2>/dev/null || true
/bin/mv "$observer_temp" "$observer_target"
/bin/launchctl bootstrap "$observer_domain" "$observer_target"
/bin/launchctl print "$observer_domain/$observer_label" | /usr/bin/awk '/^\t(state|program|runs|last exit code|run interval) = / {print}'
