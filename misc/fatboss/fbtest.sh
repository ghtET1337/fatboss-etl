#!/usr/bin/env bash
# FatBoss test server, next to the production ETL server on the same host.
#
#   bash fbtest.sh start    download a FatBoss release, start container etl-fbtest
#   bash fbtest.sh status   show whether players got in (ClientBegin / unpure) and what FatBoss logged
#   bash fbtest.sh stop     remove the test container and the test pk3s
#
# The production server is never touched: the test container reuses its image
# (same ET: Legacy build) and its environment, on another port. FatBoss runs
# the way production will, without a fork of anything: the pk3s go into the
# legacy dir, and fatboss-start.sh (the container entrypoint) adds
# fatboss.lua to Oksii's lua_modules at start.
#
# Test mode (FATBOSS_TEST=1): everybody can spray the fatboss graffiti, and
# /fbequip <knife|colt|luger|thompson|mp40|graffiti> <name> tries any skin.
set -euo pipefail

VER="${FB_VER:-b2}"            # cgame release: fatboss-<VER>
SKINS="${FB_SKINS:-s1}"        # skins release: fatboss-skins-<SKINS>
REL="https://github.com/ghtET1337/fatboss-etl/releases/download"
ETL_DIR="${ETL_DIR:-/root/etlserver}"
PROD="${PROD:-etl-server1}"
NAME="etl-fbtest"
PORT="${PORT:-27970}"
PASS="${FB_PASS:-fbtest}"
EXPECT="legacy_v2.86.0.pk3"    # the ET: Legacy version this cgame was built for
PK3="zzz_fatboss_${VER}.pk3"
SKINS_PK3="zzz_fatboss_skins_${SKINS}.pk3"
FB_DIR="$ETL_DIR/fatboss-test" # fatboss-start.sh and fatboss.lua for the test container
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
	echo "Downloading fatboss-$VER and fatboss-skins-$SKINS ..."
	fetch "fatboss-$VER" "$PK3" fatboss.lua fatboss-start.sh
	fetch "fatboss-skins-$SKINS" "$SKINS_PK3"

	mkdir -p "$WEB" "$FB_DIR"
	install -m 644 "$tmp/$PK3" "$WEB/$PK3"
	install -m 644 "$tmp/$SKINS_PK3" "$WEB/$SKINS_PK3"
	install -m 644 "$tmp/fatboss.lua" "$FB_DIR/fatboss.lua"
	install -m 644 "$tmp/fatboss-start.sh" "$FB_DIR/fatboss-start.sh"
	# players on older clients download the official pk3 too; over the web, not UDP
	if [ ! -f "$WEB/$EXPECT" ]; then
		docker cp "$PROD:/legacy/server/legacy/$EXPECT" "$WEB/$EXPECT" && chmod 644 "$WEB/$EXPECT"
		echo "Added $EXPECT to $WEB for the redirect"
	fi

	# the production container's own environment, minus what the test changes
	docker inspect "$PROD" --format '{{range .Config.Env}}{{println .}}{{end}}' \
		| grep -vE '^(PATH|HOME|HOSTNAME|MAP_PORT|PASSWORD|STATS_SUBMIT|AUTORESTART|SVTRACKER|ADVERT|MAPS|MAPS_AUTO|STARTMAP|FATBOSS_[A-Z_]*)=' \
		| grep . > "$tmp/env" || true

	docker rm -f -v "$NAME" >/dev/null 2>&1 || true
	docker run -d --name "$NAME" --restart no \
		--label com.centurylinklabs.watchtower.enable=false \
		--env-file "$tmp/env" \
		-e MAP_PORT="$PORT" \
		-e HOSTNAME="^3FatBoss ^7test" \
		-e PASSWORD="$PASS" \
		-e STATS_SUBMIT=false \
		-e AUTORESTART=false \
		-e SVTRACKER= -e ADVERT=0 \
		-e MAPS= -e MAPS_AUTO=false \
		-e STARTMAP=oasis \
		-e FATBOSS_TEST=1 \
		-v "$FB_DIR:/fatboss:ro" \
		-v "$WEB/$PK3:/legacy/server/legacy/$PK3:ro" \
		-v "$WEB/$SKINS_PK3:/legacy/server/legacy/$SKINS_PK3:ro" \
		-p "$PORT:$PORT/udp" \
		--entrypoint /bin/sh \
		"$image" /fatboss/fatboss-start.sh >/dev/null

	sleep 20
	if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
		echo "Test container did not stay up:"
		docker logs --tail 40 "$NAME"
		exit 1
	fi
	echo "OK: $NAME on UDP $PORT, $PK3 + $SKINS_PK3, image $image"
	docker logs "$NAME" 2>&1 | grep -iE "fatboss" | tail -5 || true
	if docker exec "$NAME" sh -c 'grep -l "luascripts/fatboss.lua" /legacy/server/etmain/configs/*.config' >/dev/null 2>&1; then
		echo "OK: fatboss.lua is in lua_modules"
	else
		echo "WARNING: fatboss.lua did not get into lua_modules"
	fi

	# the redirect must serve the pk3s: the skins pack is ~70 MB, far too big for UDP downloads
	redirect=$(docker exec "$NAME" printenv REDIRECTURL 2>/dev/null || true)
	if [ -z "$redirect" ]; then
		echo "WARNING: no REDIRECTURL, players download everything over UDP (very slow)"
	else
		for f in "$EXPECT" "$PK3" "$SKINS_PK3"; do
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
}

stop() {
	docker rm -f -v "$NAME" >/dev/null 2>&1 && echo "removed $NAME" || echo "$NAME was not running"
	rm -f "$WEB/$PK3" "$WEB/$SKINS_PK3" && echo "removed $PK3 and $SKINS_PK3 from $WEB"
	rm -rf "$FB_DIR" && echo "removed $FB_DIR"
}

case "${1:-}" in
	start) start ;;
	status) status ;;
	stop) stop ;;
	*) echo "usage: bash $0 start|status|stop"; exit 2 ;;
esac
