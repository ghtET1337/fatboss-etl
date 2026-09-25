#!/bin/sh
# FatBoss add-on for Oksii's ET: Legacy image (oksii/etlegacy), used as the
# container entrypoint from docker-compose. Oksii's image and his settings repo
# stay untouched: his ./start still does all of the setup (settings, maps,
# configs, Lua scripts) and then launches /legacy/server/etlded. That one path
# is taken over by a tiny launcher, which right before the real server starts
#   - copies the FatBoss pk3s from /fatboss into the legacy dir (and removes
#     FatBoss pk3s of an older version, so players never download both),
#   - adds luascripts/fatboss.lua to the configs' lua_modules.
#
# docker-compose.yml, in the ETL server service:
#   entrypoint: ["/bin/sh", "/fatboss/fatboss-start.sh"]
#   volumes:
#     - /root/etlserver/fatboss:/fatboss:ro
# /root/etlserver/fatboss is filled by fatboss-install.sh: this script,
# fatboss.lua, the zzz_fatboss*.pk3 files and ETL_PK3.
#
# ETL_PK3 names the official pk3 the FatBoss cgame was built for
# (legacy_v2.86.0.pk3). When the image carries another ET: Legacy version
# (an update Oksii shipped), the server starts without FatBoss instead of
# handing players a cgame that does not match the server.
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
# $MARK: Oksii's settings are in place now; add FatBoss, start the server.
LAUNCHER
cat >> etlded.tmp <<'LAUNCHER'
FB=/fatboss
LEGACY=/legacy/server/legacy
ready=1
if [ -f "$FB/ETL_PK3" ]; then
    want=$(tr -d ' \r\n' < "$FB/ETL_PK3")
    if [ -n "$want" ] && [ ! -f "$LEGACY/$want" ]; then
        echo "FatBoss: built for $want, but this image has: $(ls "$LEGACY" | grep '^legacy_v' | tr '\n' ' ')- starting without FatBoss"
        ready=0
    fi
fi
# FatBoss pk3s that are not the ones in /fatboss (an older version) go; a pk3
# the test script bind-mounts read-only cannot be removed and simply stays
for f in "$LEGACY"/zzz_fatboss*.pk3; do
    [ -f "$f" ] || continue
    if [ "$ready" = 1 ] && [ -f "$FB/$(basename "$f")" ]; then
        continue
    fi
    rm -f "$f" 2>/dev/null && echo "FatBoss: removed $(basename "$f")"
done
if [ "$ready" = 1 ]; then
    for f in "$FB"/zzz_fatboss*.pk3; do
        [ -f "$f" ] || continue
        cmp -s "$f" "$LEGACY/$(basename "$f")" 2>/dev/null || cp "$f" "$LEGACY/" && echo "FatBoss: $(basename "$f") in place"
    done
fi
if [ "$ready" = 1 ] && [ -f "$FB/fatboss.lua" ]; then
    cp "$FB/fatboss.lua" "$LEGACY/luascripts/fatboss.lua"
    for f in /legacy/server/etmain/configs/*.config; do
        [ -f "$f" ] || continue
        grep -q 'luascripts/fatboss.lua' "$f" && continue
        sed -i -E 's#(setl[[:space:]]+lua_modules[[:space:]]+"[^"]*)"#\1 luascripts/fatboss.lua"#' "$f"
    done
    echo "FatBoss: luascripts/fatboss.lua added to lua_modules"
elif [ "$ready" = 1 ]; then
    echo "FatBoss: $FB/fatboss.lua not found, starting without it"
fi
exec /legacy/server/etlded.real "$@"
LAUNCHER
chmod 755 etlded.tmp && mv -f etlded.tmp etlded

exec ./start "$@"
