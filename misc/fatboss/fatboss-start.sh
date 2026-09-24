#!/bin/sh
# FatBoss add-on for Oksii's ET: Legacy image (oksii/etlegacy), used as the
# container entrypoint from docker-compose. Oksii's image and his settings repo
# stay untouched: his ./start still does all of the setup (settings, maps,
# configs, Lua scripts) and then launches /legacy/server/etlded. That one path
# is taken over by a tiny launcher, which adds luascripts/fatboss.lua to the
# configs' lua_modules right before the real server starts.
#
# docker-compose.yml, in the ETL server service:
#   entrypoint: ["/bin/sh", "/fatboss/fatboss-start.sh"]
#   volumes:
#     - /root/etlserver/fatboss:/fatboss:ro
# with fatboss-start.sh and fatboss.lua in /root/etlserver/fatboss.
#
# If /fatboss/fatboss.lua is missing, the server starts exactly as without it.
# Every step hands over with exec, so the game server still ends up as PID 1
# (Oksii's autorestart signals PID 1).
#
# When ./start replaces etlded itself (ETLDED_URL / ETLDED_REPO), that start
# runs without FatBoss; the next start moves the new binary aside and puts the
# launcher back.
cd /legacy/server || exit 1

MARK="FatBoss launcher"

# etlded is a real server binary on a fresh container, and again after ./start
# downloaded a new one: keep it as etlded.real
if ! grep -q "$MARK" etlded 2>/dev/null; then
    mv -f etlded etlded.real || exec ./start "$@"
fi

cat > etlded.tmp <<LAUNCHER
#!/bin/sh
# $MARK: Oksii's settings are in place now; add the module, start the server.
LAUNCHER
cat >> etlded.tmp <<'LAUNCHER'
if [ -f /fatboss/fatboss.lua ]; then
    cp /fatboss/fatboss.lua /legacy/server/legacy/luascripts/fatboss.lua
    for f in /legacy/server/etmain/configs/*.config; do
        [ -f "$f" ] || continue
        grep -q 'luascripts/fatboss.lua' "$f" && continue
        sed -i -E 's#(setl[[:space:]]+lua_modules[[:space:]]+"[^"]*)"#\1 luascripts/fatboss.lua"#' "$f"
    done
    echo "FatBoss: luascripts/fatboss.lua added to lua_modules"
else
    echo "FatBoss: /fatboss/fatboss.lua not found, starting without it"
fi
exec /legacy/server/etlded.real "$@"
LAUNCHER
chmod 755 etlded.tmp && mv -f etlded.tmp etlded

exec ./start "$@"
