#!/usr/bin/env bash
# FatBoss cgame test server, next to the production ETL server on the same host.
#
#   bash fbtest.sh start    download the pk3, start container etl-fbtest
#   bash fbtest.sh status   show whether players got in (ClientBegin / unpure)
#   bash fbtest.sh stop     remove the test container and the test pk3
#
# The production server is never touched: the test container reuses its image
# (same ET: Legacy build), its settings.env for REDIRECTURL, and a new port.
set -euo pipefail

VER="${FB_VER:-poc1}"
PK3="zzz_fatboss_${VER}.pk3"
URL="https://github.com/ghtET1337/fatboss-etl/releases/download/fatboss-${VER}"
ETL_DIR="${ETL_DIR:-/root/etlserver}"
PROD="${PROD:-etl-server1}"
NAME="etl-fbtest"
PORT="${PORT:-27970}"
PASS="${FB_PASS:-fbtest}"
EXPECT="legacy_v2.86.0.pk3"   # the ET: Legacy version this cgame was built for

start() {
	# the cgame must match the mod version the production image runs
	if ! docker exec "$PROD" ls /legacy/server/legacy/ | grep -qx "$EXPECT"; then
		echo "STOP: $PROD does not run $EXPECT, it has:"
		docker exec "$PROD" ls /legacy/server/legacy/ | grep '^legacy_v' || true
		exit 1
	fi
	image=$(docker inspect "$PROD" --format '{{.Image}}')

	# pk3 from the GitHub release, verified against its published sha256
	tmp=$(mktemp -d)
	trap 'rm -rf "$tmp"' EXIT
	curl -fsSL -o "$tmp/$PK3" "$URL/$PK3"
	curl -fsSL -o "$tmp/$PK3.sha256" "$URL/$PK3.sha256"
	(cd "$tmp" && sha256sum -c "$PK3.sha256")
	mkdir -p "$ETL_DIR/maps/legacy"
	# maps/legacy is what the redirect web server hands to players
	install -m 644 "$tmp/$PK3" "$ETL_DIR/maps/legacy/$PK3"

	docker rm -f -v "$NAME" >/dev/null 2>&1 || true
	docker run -d --name "$NAME" --restart no \
		--label com.centurylinklabs.watchtower.enable=false \
		--env-file "$ETL_DIR/settings.env" \
		-e MAP_PORT="$PORT" \
		-e HOSTNAME="^3FatBoss ^7test" \
		-e PASSWORD="$PASS" \
		-e STATS_SUBMIT=false \
		-e AUTORESTART=false \
		-e SVTRACKER= -e ADVERT=0 \
		-e MAPS= -e MAPS_AUTO=false \
		-e STARTMAP=oasis \
		-v "$ETL_DIR/maps/legacy/$PK3:/legacy/server/legacy/$PK3:ro" \
		-p "$PORT:$PORT/udp" \
		"$image" >/dev/null

	sleep 15
	if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
		echo "Test container did not stay up:"
		docker logs --tail 40 "$NAME"
		exit 1
	fi
	echo "OK: $NAME is running on UDP $PORT with $PK3 (image $image)"
	echo "Players download it from: $(docker exec "$NAME" printenv REDIRECTURL)/legacy/$PK3"
	if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
		ufw status | grep -q "^$PORT/udp" || echo "Note: ufw is active and $PORT/udp is not open (ufw allow $PORT/udp)"
	fi
	echo "In game:  /password $PASS   then   /connect <this host IP>:$PORT"
}

status() {
	docker ps --filter "name=^${NAME}$" --format '{{.Names}}  {{.Status}}  {{.Ports}}'
	docker logs "$NAME" 2>&1 | grep -E "ClientConnect|ClientBegin|clientDownload|Unpure|unpure|nChkSum|Dropped|disconnected" | tail -30 || true
}

stop() {
	docker rm -f -v "$NAME" >/dev/null 2>&1 && echo "removed $NAME" || echo "$NAME was not running"
	rm -f "$ETL_DIR/maps/legacy/$PK3" && echo "removed maps/legacy/$PK3"
}

case "${1:-}" in
	start) start ;;
	status) status ;;
	stop) stop ;;
	*) echo "usage: bash $0 start|status|stop"; exit 2 ;;
esac
