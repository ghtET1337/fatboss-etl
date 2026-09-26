#!/usr/bin/env bash
# Puts a FatBoss release where Oksii's ETL containers on this host pick it up.
#
#   bash fatboss-install.sh           download, verify and install the release
#   bash fatboss-install.sh status    what is installed and which containers run FatBoss
#
# Fills /root/etlserver/fatboss (mounted into the containers as /fatboss) with
# fatboss-start.sh, fatboss.lua, the FatBoss pk3s and ETL_PK3 (the official pk3
# the cgame was built for), and copies the pk3s to maps/legacy, which the
# redirect web server hands to players. No server changes until
# docker-compose.yml points it at /fatboss and it is restarted; the output
# ends with exactly what to add.
#
# Pick versions with FB_VER (cgame), FB_SKINS (skins pack) and FB_SERVER
# (fatboss.lua and fatboss-start.sh).
set -euo pipefail

VER="${FB_VER:-b9}"
SKINS="${FB_SKINS:-s5}"
SERVER="${FB_SERVER:-0.8}"
REL="https://github.com/ghtET1337/fatboss-etl/releases/download"
ETL_DIR="${ETL_DIR:-/root/etlserver}"
FB_DIR="$ETL_DIR/fatboss"
WEB="$ETL_DIR/maps/legacy"
PK3="zzz_fatboss_${VER}.pk3"

fetch() { # <release tag> <file>...
	local tag=$1
	shift
	for f in "$@"; do
		curl -fsSL -o "$tmp/$f" "$REL/$tag/$f"
		curl -fsSL -o "$tmp/$f.sha256" "$REL/$tag/$f.sha256"
		(cd "$tmp" && sha256sum -c --quiet "$f.sha256") || { echo "STOP: $f does not match its sha256"; exit 1; }
	done
}

fatboss_containers() {
	docker ps --format '{{.Names}}' | while read -r n; do
		docker inspect "$n" --format '{{range .Mounts}}{{.Destination}} {{end}}' | grep -qw /fatboss && echo "$n"
	done
}

install_release() {
	tmp=$(mktemp -d)
	trap 'rm -rf "$tmp"' EXIT
	echo "Downloading fatboss-$VER, fatboss-skins-$SKINS and fatboss-server-$SERVER ..."
	fetch "fatboss-$VER" "$PK3"
	curl -fsSL -o "$tmp/$PK3.txt" "$REL/fatboss-$VER/$PK3.txt"
	fetch "fatboss-server-$SERVER" fatboss.lua fatboss-start.sh
	fetch "fatboss-skins-$SKINS" skins.txt
	mapfile -t skins < <(grep -E '^zzz_fatboss_skins_[a-z0-9]+\.pk3$' "$tmp/skins.txt")
	[ "${#skins[@]}" -gt 0 ] || { echo "STOP: skins.txt lists no pk3"; exit 1; }
	fetch "fatboss-skins-$SKINS" "${skins[@]}"
	# the ET: Legacy version the cgame was built for, from the release notes of the pk3
	etl=$(sed -n 's/^et:legacy: *v\{0,1\}\([0-9][0-9.]*\).*/\1/p' "$tmp/$PK3.txt" | head -n 1)
	[ -n "$etl" ] || { echo "STOP: $PK3.txt does not say which ET: Legacy it was built for"; exit 1; }

	mkdir -p "$FB_DIR" "$WEB"
	# only the new version's pk3s stay in /fatboss: containers copy exactly what is here
	for f in "$FB_DIR"/zzz_fatboss*.pk3; do
		[ -f "$f" ] || continue
		case " $PK3 ${skins[*]} " in *" $(basename "$f") "*) ;; *) rm -f "$f" && echo "removed $(basename "$f") from $FB_DIR" ;; esac
	done
	for f in "$PK3" "${skins[@]}"; do
		install -m 644 "$tmp/$f" "$FB_DIR/$f"
		install -m 644 "$tmp/$f" "$WEB/$f"
	done
	install -m 644 "$tmp/fatboss.lua" "$FB_DIR/fatboss.lua"
	install -m 644 "$tmp/fatboss-start.sh" "$FB_DIR/fatboss-start.sh"
	echo "legacy_v${etl}.pk3" > "$FB_DIR/ETL_PK3"
	echo "Installed in $FB_DIR: $PK3 ${skins[*]} fatboss.lua fatboss-start.sh (built for ET: Legacy $etl)"
	echo "Copied to $WEB for the redirect: $PK3 ${skins[*]}"
	if [ ! -f "$WEB/legacy_v${etl}.pk3" ]; then
		echo "Note: $WEB has no legacy_v${etl}.pk3; players on older clients would download it over UDP, which stops at 32 MiB."
		echo "      Copy it from a server: docker cp etl-server1:/legacy/server/legacy/legacy_v${etl}.pk3 $WEB/"
	fi

	running=$(fatboss_containers | tr '\n' ' ')
	cat <<EOF

Next steps
----------
1. settings.env (once), the same for every server:
     FATBOSS_LOADOUT_URL=https://fantasyleague.polandetlegacy.com/crates/api/game/loadouts
     FATBOSS_API_TOKEN=<FATBOSS_GAME_TOKEN from the bot's .env>
     FATBOSS_DEFAULT_GRAFFITI=fatboss

2. docker-compose.yml, in every server that gets FatBoss (etl-server1 as the example):
     etl-server1:
       entrypoint: ["/bin/sh", "/fatboss/fatboss-start.sh"]
       volumes:
         - "$FB_DIR:/fatboss:ro"          # next to the volumes it already has

3. Apply it (the container is recreated, the other servers are left alone):
     cd $ETL_DIR && docker compose up -d etl-server1

EOF
	if [ -n "$running" ]; then
		echo "Already on FatBoss: $running- restart them to pick up this release:"
		for n in $running; do echo "     docker restart $n"; done
	fi
}

status() {
	echo "== $FB_DIR"
	ls -la "$FB_DIR" 2>/dev/null || echo "(not installed)"
	[ -f "$FB_DIR/ETL_PK3" ] && echo "built for: $(cat "$FB_DIR/ETL_PK3")"
	echo "== containers with /fatboss"
	for n in $(fatboss_containers); do
		echo "-- $n"
		docker logs "$n" 2>&1 | grep -E "^FatBoss:|fatboss: " | tail -8 || true
	done
}

case "${1:-install}" in
	install) install_release ;;
	status) status ;;
	*) echo "usage: bash $0 [install|status]"; exit 2 ;;
esac
