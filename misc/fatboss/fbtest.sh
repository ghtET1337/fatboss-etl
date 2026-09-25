#!/usr/bin/env bash
# FatBoss test server, next to the production ETL server on the same host.
#
#   bash fbtest.sh start    download a FatBoss release, start container etl-fbtest
#   bash fbtest.sh status   show whether players got in (ClientBegin / unpure) and what FatBoss logged
#   bash fbtest.sh stop     remove the test container and the files this script put in place
#
# The production server is never touched: the test container reuses its image
# (same ET: Legacy build) and its environment, on another port. FatBoss runs
# the way production will, without a fork of anything: the pk3s go into the
# legacy dir, and fatboss-start.sh (the container entrypoint) adds
# fatboss.lua to Oksii's lua_modules at start.
#
# Test mode (FATBOSS_TEST=1): everybody can spray the fatboss graffiti, and
# /fbequip <knife|colt|luger|thompson|mp40|graffiti> <name> tries any skin.
#
# Against the real FatBoss site (loadouts from the Arsenal tab, /fblink codes):
#   FB_LOADOUT_URL=https://<fatboss>/crates/api/game/loadouts FB_API_TOKEN=<FATBOSS_GAME_TOKEN> bash fbtest.sh start
set -euo pipefail

VER="${FB_VER:-b4}"            # cgame release: fatboss-<VER>
SKINS="${FB_SKINS:-s3}"        # skins release: fatboss-skins-<SKINS>, pk3 names listed in its skins.txt
SERVER="${FB_SERVER:-0.5}"     # server files release: fatboss-server-<SERVER> (fatboss.lua, fatboss-start.sh)
REL="https://github.com/ghtET1337/fatboss-etl/releases/download"
ETL_DIR="${ETL_DIR:-/root/etlserver}"
PROD="${PROD:-etl-server1}"
NAME="etl-fbtest"
PORT="${PORT:-27970}"
PASS="${FB_PASS:-fbtest}"
EXPECT="legacy_v2.86.0.pk3"    # the ET: Legacy version this cgame was built for
PK3="zzz_fatboss_${VER}.pk3"
FB_DIR="$ETL_DIR/fatboss-test" # fatboss-start.sh, fatboss.lua and the list of what this script installed
WEB="$ETL_DIR/maps/legacy"     # what the redirect web server hands to players

fetch() { # <release tag> <file>...
	local tag=$1
	shift
	for f in "$@"; do
		curl -fsSL -o "$tmp/$f" "$REL/$tag/$f"
		curl -fsSL -o "$tmp/$f.sha256" "$REL/$tag/$f.sha256"
		(cd "$tmp" && sha256sum -c --quiet "$f.sha256") || { echo "STOP: $f does not match its sha256"; exit 1; }
	done
}

# removes the pk3s an earlier run put on the redirect, except the ones given
remove_installed() {
	[ -f "$FB_DIR/installed.txt" ] || return 0
	while read -r f; do
		case " $* " in *" $f "*) continue ;; esac
		[ -n "$f" ] && rm -f "$WEB/$f" && echo "removed $f from $WEB"
	done < "$FB_DIR/installed.txt"
}

start() {
	# the cgame must match the mod version the production image runs
	if ! docker exec "$PROD" ls /legacy/server/legacy/ | grep -qx "$EXPECT"; then
		echo "STOP: $PROD does not run $EXPECT, it has:"
		docker exec "$PROD" ls /legacy/server/legacy/ | grep '^legacy_v' || true
		exit 1
	fi
	image=$(docker inspect "$PROD" --format '{{.Image}}')

	tmp=$(mktemp -d)
	trap 'rm -rf "$tmp"' EXIT
	echo "Downloading fatboss-$VER, fatboss-skins-$SKINS and fatboss-server-$SERVER ..."
	fetch "fatboss-$VER" "$PK3"
	fetch "fatboss-server-$SERVER" fatboss.lua fatboss-start.sh
	fetch "fatboss-skins-$SKINS" skins.txt
	mapfile -t skins < <(grep -E '^zzz_fatboss_skins_[a-z0-9]+\.pk3$' "$tmp/skins.txt")
	[ "${#skins[@]}" -gt 0 ] || { echo "STOP: skins.txt lists no pk3"; exit 1; }
	fetch "fatboss-skins-$SKINS" "${skins[@]}"

	mkdir -p "$WEB" "$FB_DIR"
	remove_installed "$PK3" "${skins[@]}"
	mounts=()
	for f in "$PK3" "${skins[@]}"; do
		install -m 644 "$tmp/$f" "$WEB/$f"
		mounts+=(-v "$WEB/$f:/legacy/server/legacy/$f:ro")
	done
	printf '%s\n' "$PK3" "${skins[@]}" > "$FB_DIR/installed.txt"
	install -m 644 "$tmp/fatboss.lua" "$FB_DIR/fatboss.lua"
	install -m 644 "$tmp/fatboss-start.sh" "$FB_DIR/fatboss-start.sh"
	# players on older clients download the official pk3 too, and at 34 MB it
	# only arrives over the web: the UDP fallback stalls for good at 32 MiB
	if [ ! -f "$WEB/$EXPECT" ]; then
		docker cp "$PROD:/legacy/server/legacy/$EXPECT" "$WEB/$EXPECT" && chmod 644 "$WEB/$EXPECT"
		echo "Added $EXPECT to $WEB for the redirect"
	fi

	# the production container's own environment, minus what the test changes
	docker inspect "$PROD" --format '{{range .Config.Env}}{{println .}}{{end}}' \
		| grep -vE '^(PATH|HOME|HOSTNAME|MAP_PORT|PASSWORD|STATS_SUBMIT|STATS_GATHER_FEATURES|STATS_AUTO_[A-Z_]*|SETTINGSBRANCH|AUTORESTART|SVTRACKER|ADVERT|MAPS|MAPS_AUTO|STARTMAP|FATBOSS_[A-Z_]*)=' \
		| grep . > "$tmp/env" || true
	# optionally the real FatBoss site instead of /fbequip alone
	if [ -n "${FB_LOADOUT_URL:-}" ]; then
		printf 'FATBOSS_LOADOUT_URL=%s\nFATBOSS_API_TOKEN=%s\nFATBOSS_DEFAULT_GRAFFITI=fatboss\n' "$FB_LOADOUT_URL" "${FB_API_TOKEN:-}" >> "$tmp/env"
		echo "Loadouts and /fblink go to $FB_LOADOUT_URL"
	fi

	# Oksii's stats.lua loads only from the etl-stats-api settings branch, which
	# production gets through STATS_SUBMIT=true. The test loads it the same way
	# but submits nothing and runs none of the gather automation (rename, sort,
	# auto start, map, config), so it cannot touch api.etl.lol or real matches.
	docker rm -f -v "$NAME" >/dev/null 2>&1 || true
	docker run -d --name "$NAME" --restart no \
		--label com.centurylinklabs.watchtower.enable=false \
		--env-file "$tmp/env" \
		-e MAP_PORT="$PORT" \
		-e HOSTNAME="^3FatBoss ^7test" \
		-e PASSWORD="$PASS" \
		-e SETTINGSBRANCH=etl-stats-api \
		-e STATS_SUBMIT=false \
		-e STATS_GATHER_FEATURES=false \
		-e STATS_AUTO_RENAME=false -e STATS_AUTO_SORT=false -e STATS_AUTO_START=false \
		-e STATS_AUTO_MAP=false -e STATS_AUTO_CONFIG=false -e STATS_AUTO_SCORES=false \
		-e STATS_API_DUMPJSON=true -e STATS_API_PATH=/legacy/homepath/legacy/fbtest-stats/ \
		-e AUTORESTART=false \
		-e SVTRACKER= -e ADVERT=0 \
		-e MAPS= -e MAPS_AUTO=false \
		-e STARTMAP=oasis \
		-e FATBOSS_TEST=1 \
		-v "$FB_DIR:/fatboss:ro" \
		"${mounts[@]}" \
		-p "$PORT:$PORT/udp" \
		--entrypoint /bin/sh \
		"$image" /fatboss/fatboss-start.sh >/dev/null

	sleep 20
	if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
		echo "Test container did not stay up:"
		docker logs --tail 40 "$NAME"
		exit 1
	fi
	echo "OK: $NAME on UDP $PORT with $PK3 ${skins[*]} (image $image)"
	docker logs "$NAME" 2>&1 | grep -iE "fatboss" | tail -5 || true
	if docker exec "$NAME" sh -c 'grep -l "luascripts/fatboss.lua" /legacy/server/etmain/configs/*.config' >/dev/null 2>&1; then
		echo "OK: fatboss.lua is in lua_modules:"
		docker exec "$NAME" sh -c 'grep -h "lua_modules" /legacy/server/etmain/configs/*.config' | sort | uniq -c
	else
		echo "WARNING: fatboss.lua did not get into lua_modules"
	fi

	# the redirect must serve the pk3s; over UDP they crawl, and past 32 MiB they never finish
	redirect=$(docker exec "$NAME" printenv REDIRECTURL 2>/dev/null || true)
	if [ -z "$redirect" ]; then
		echo "WARNING: no REDIRECTURL, players download everything over UDP (very slow)"
	else
		for f in "$EXPECT" "$PK3" "${skins[@]}"; do
			if curl -fsI --max-time 10 "$redirect/legacy/$f" >/dev/null; then
				echo "OK: redirect serves $redirect/legacy/$f"
			else
				echo "WARNING: $redirect/legacy/$f is not reachable - players fall back to slow UDP downloads"
			fi
		done
	fi
	if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
		ufw status | grep -q "^$PORT/udp" || echo "Note: ufw is active and $PORT/udp is not open (ufw allow $PORT/udp)"
	fi
	echo "In game:  /password $PASS   then   /connect <this host IP>:$PORT"
	echo "Then:     bind t spray   bind i +ilookatweapon   /fbequip colt gold   /fb_skins"
}

status() {
	docker ps --filter "name=^${NAME}$" --format '{{.Names}}  {{.Status}}  {{.Ports}}'
	docker logs "$NAME" 2>&1 | grep -iE "ClientConnect|ClientBegin|clientDownload|unpure|nChkSum|Dropped|disconnected|fatboss|lua" | tail -40 || true
	# Oksii's stats.lua writes each finished round here instead of sending it to api.etl.lol
	echo "Stats files written by stats.lua (one per finished round):"
	docker exec "$NAME" sh -c 'ls -la /legacy/homepath/legacy/fbtest-stats/ 2>/dev/null | tail -n +2' || true
}

stop() {
	docker rm -f -v "$NAME" >/dev/null 2>&1 && echo "removed $NAME" || echo "$NAME was not running"
	remove_installed
	rm -rf "$FB_DIR" && echo "removed $FB_DIR"
}

case "${1:-}" in
	start) start ;;
	status) status ;;
	stop) stop ;;
	*) echo "usage: bash $0 start|status|stop"; exit 2 ;;
esac
