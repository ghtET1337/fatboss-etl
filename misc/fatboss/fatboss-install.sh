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
# A full disk never leaves half a file: the free space is checked before
# anything big is downloaded or written, a pk3 already in place with the right
# sha256 is left as it is, every file is written as <name>.part and moved over
# the old one only when it is whole, and old pk3s go once every new file is in.
#
# Pick versions with FB_VER (cgame), FB_SKINS (skins pack) and FB_SERVER
# (fatboss.lua and fatboss-start.sh).
set -euo pipefail

VER="${FB_VER:-b21}"
SKINS="${FB_SKINS:-s9}"
SERVER="${FB_SERVER:-0.20}"
REL="https://github.com/ghtET1337/fatboss-etl/releases/download"
ETL_DIR="${ETL_DIR:-/root/etlserver}"
FB_DIR="$ETL_DIR/fatboss"
WEB="$ETL_DIR/maps/legacy"
PK3="zzz_fatboss_${VER}.pk3"
part=                          # the <name>.part being written; the EXIT trap removes it
w_src=() w_dst=() w_sha=()     # pk3s to write: source, destination, sha256
dl=() kept=()                  # pk3s to download (<release tag>/<file>); pk3s already right in both places
declare -A dl_size=()          # downloaded file -> its size from the download's headers ("" when they do not say)

fetch() { # <release tag> <file>...
	local tag=$1
	shift
	for f in "$@"; do
		curl -fsSL -o "$tmp/$f" "$REL/$tag/$f"
		curl -fsSL -o "$tmp/$f.sha256" "$REL/$tag/$f.sha256"
		(cd "$tmp" && sha256sum -c --quiet "$f.sha256") || { echo "STOP: $f does not match its sha256"; exit 1; }
	done
}

# One pk3, in $FB_DIR and in $WEB: a copy that already has the right sha256 stays as it is; a missing or
# different one is written from a right copy on this host, or else from a download into $tmp
plan_pk3() { # <release tag> <file>
	local f=$2 want p src= todo=()
	want=$(cut -c1-64 "$tmp/$f.sha256")
	for p in "$FB_DIR/$f" "$WEB/$f"; do
		if [ -f "$p" ] && [ "$(sha256sum < "$p" | cut -c1-64)" = "$want" ]; then
			src=$p
		else
			todo+=("$p")
		fi
	done
	if [ "${#todo[@]}" -eq 0 ]; then
		kept+=("$f")
		return 0
	fi
	if [ -z "$src" ]; then
		src="$tmp/$f"
		dl+=("$1/$f")
	fi
	for p in "${todo[@]}"; do
		w_src+=("$src")
		w_dst+=("$p")
		w_sha+=("$want")
	done
}

# the size a release file will have, from the headers of its download (curl -I follows GitHub's redirect);
# nothing when they do not say
remote_size() { # <release tag>/<file>
	local h
	h=$(curl -fsSIL "$REL/$1" 2>/dev/null) || return 0
	printf '%s\n' "$h" | tr -d '\r' \
		| awk '/^HTTP\// { n = "" } tolower($1) == "content-length:" { n = $2 } END { if (n ~ /^[0-9]+$/ && n > 0) print n }' || true
}

# the bytes this run still writes: "<into $tmp> <into $FB_DIR> <into $WEB>". A file counts with its size on this
# host (in $tmp once downloaded), else with the size its download's headers gave, else 0.
room_needed() {
	local i n t into_tmp=0 into_fb=0 into_web=0
	for t in ${dl[@]+"${dl[@]}"}; do
		[ -f "$tmp/${t##*/}" ] || into_tmp=$(( into_tmp + ${dl_size[${t##*/}]:-0} ))
	done
	for i in ${w_dst[@]+"${!w_dst[@]}"}; do
		if [ -f "${w_src[$i]}" ]; then
			n=$(stat -c %s "${w_src[$i]}")
		else
			n=${dl_size[${w_src[$i]##*/}]:-0}
		fi
		if [ "${w_dst[$i]%/*}" = "$FB_DIR" ]; then
			into_fb=$(( into_fb + n ))
		else
			into_web=$(( into_web + n ))
		fi
	done
	# fatboss.lua, fatboss-start.sh and ETL_PK3; the official pk3 the redirect lacks goes through $tmp to $WEB
	into_fb=$(( into_fb + $(stat -c %s "$tmp/fatboss.lua") + $(stat -c %s "$tmp/fatboss-start.sh") + 100 ))
	echo "$(( into_tmp + legacy )) $into_fb $(( into_web + legacy ))"
}

# Stops when a filesystem lacks the room: <directory> <bytes> pairs, one per place this run writes to ($TMPDIR,
# $FB_DIR, $WEB; a directory not made yet counts as its parent). Places on one filesystem add up, and a replaced
# file counts in full: the new one is written whole before the old one goes.
check_space() { # <directory> <bytes>...
	local -A need=() free=() what=()
	local d line m kib
	while [ $# -ge 2 ]; do
		d=$1
		while [ ! -d "$d" ]; do d=$(dirname "$d"); done
		line=$(df -Pk "$d" 2>/dev/null | awk 'NR == 2 { print $4, $6 }') || line=
		case ${line%% *} in
			'' | *[!0-9]*)
				echo "Note: df does not say how much room $1 has; not checked"
				;;
			*)
				m=${line#* }
				free[$m]=${line%% *}
				need[$m]=$(( ${need[$m]:-0} + $2 ))
				what[$m]="${what[$m]:-}${what[$m]:+ and }$1"
				;;
		esac
		shift 2
	done
	for m in ${need[@]+"${!need[@]}"}; do
		# KiB, rounded up, plus 1 MiB for the filesystem's own bookkeeping
		kib=$(( (${need[$m]} + 1023) / 1024 + 1024 ))
		if [ "$kib" -gt "${free[$m]}" ]; then
			echo "STOP: not enough free space on $m (for ${what[$m]}): $(( (kib + 1023) / 1024 )) MB needed there, $(( ${free[$m]} / 1024 )) MB free."
			echo "      Nothing was installed or removed. Free some space (or point TMPDIR at a bigger disk) and run it again."
			exit 1
		fi
	done
}

# <source> to <destination> as <destination>.part, checked against <sha256> when one is given, then moved over the
# old file: a full disk or a cut copy never leaves a half file under the real name, and the old file stays till then
put() { # <source> <destination> [<sha256>]
	part="$2.part"
	if install -m 644 "$1" "$part" && { [ -z "${3:-}" ] || [ "$(sha256sum < "$part" | cut -c1-64)" = "$3" ]; } \
		&& mv -f "$part" "$2"; then
		part=
		return 0
	fi
	rm -f "$part"
	part=
	echo "STOP: could not write $2 whole (disk full?); the file that was there is unchanged. Run it again once there is room."
	exit 1
}

fatboss_containers() {
	# an if, not &&: a last container without /fatboss must not fail the loop (set -e + pipefail)
	docker ps --format '{{.Names}}' | while read -r n; do
		if docker inspect "$n" --format '{{range .Mounts}}{{.Destination}} {{end}}' | grep -qw /fatboss; then
			echo "$n"
		fi
	done
}

install_release() {
	tmp=$(mktemp -d)
	trap 'rm -rf "$tmp"; [ -z "$part" ] || rm -f "$part"' EXIT
	# room for the small files (checksums, notes, fatboss.lua: well under 1 MB) before the first download
	check_space "$tmp" 1048576
	echo "Downloading fatboss-$VER, fatboss-skins-$SKINS and fatboss-server-$SERVER ..."
	# the small files first: checksums, the pk3's notes, the server files and the list of skins pk3s
	curl -fsSL -o "$tmp/$PK3.sha256" "$REL/fatboss-$VER/$PK3.sha256"
	curl -fsSL -o "$tmp/$PK3.txt" "$REL/fatboss-$VER/$PK3.txt"
	fetch "fatboss-server-$SERVER" fatboss.lua fatboss-start.sh
	fetch "fatboss-skins-$SKINS" skins.txt
	mapfile -t skins < <(grep -E '^zzz_fatboss_(skins?|wear)_[a-z0-9_]+\.pk3$' "$tmp/skins.txt")
	[ "${#skins[@]}" -gt 0 ] || { echo "STOP: skins.txt lists no pk3"; exit 1; }
	for f in "${skins[@]}"; do
		curl -fsSL -o "$tmp/$f.sha256" "$REL/fatboss-skins-$SKINS/$f.sha256"
	done
	# the ET: Legacy version the cgame was built for, from the release notes of the pk3:
	# a release (2.86.0) or a snapshot (2.86.0-13-g39c75a3), named exactly like the official pk3
	etl=$(sed -n 's/^et:legacy: *v\{0,1\}\([0-9][0-9.]*\(-[0-9][0-9]*-g[0-9a-f][0-9a-f]*\)\{0,1\}\).*/\1/p' "$tmp/$PK3.txt" | head -n 1)
	[ -n "$etl" ] || { echo "STOP: $PK3.txt does not say which ET: Legacy it was built for"; exit 1; }

	# what this host still needs, and the room for it, before anything big is downloaded or written
	plan_pk3 "fatboss-$VER" "$PK3"
	for f in "${skins[@]}"; do
		plan_pk3 "fatboss-skins-$SKINS" "$f"
	done
	unsized=
	for t in ${dl[@]+"${dl[@]}"}; do
		dl_size[${t##*/}]=$(remote_size "$t")
		[ -n "${dl_size[${t##*/}]}" ] || unsized="$unsized ${t##*/}"
	done
	# the official pk3 the redirect lacks comes from a running container at the end (through $tmp)
	legacy=0
	if [ ! -f "$WEB/legacy_v${etl}.pk3" ]; then
		for n in $(docker ps --format '{{.Names}}' 2>/dev/null); do
			legacy=$(docker exec "$n" stat -c %s "/legacy/server/legacy/legacy_v${etl}.pk3" 2>/dev/null) && break || legacy=0
		done
		case $legacy in '' | *[!0-9]*) legacy=0 ;; esac
	fi
	[ "${#kept[@]}" -eq 0 ] || echo "Already right on this host, left as they are: ${kept[*]}"
	[ -z "$unsized" ] || echo "Note: GitHub did not say the size of$unsized; the room is checked again once downloaded."
	sizes=$(room_needed)
	read -r b_tmp b_fb b_web <<< "$sizes"
	check_space "$tmp" "$b_tmp" "$FB_DIR" "$b_fb" "$WEB" "$b_web"

	for t in ${dl[@]+"${dl[@]}"}; do
		f=${t##*/}
		curl -fsSL -o "$tmp/$f" "$REL/$t"
		(cd "$tmp" && sha256sum -c --quiet "$f.sha256") || { echo "STOP: $f does not match its sha256"; exit 1; }
	done
	# the real sizes now, before the first file is written
	sizes=$(room_needed)
	read -r b_tmp b_fb b_web <<< "$sizes"
	check_space "$tmp" "$b_tmp" "$FB_DIR" "$b_fb" "$WEB" "$b_web"

	mkdir -p "$FB_DIR" "$WEB"
	# the redirect's pk3s first: should one fail, /fatboss (what the containers copy) is still the old release
	for i in ${w_dst[@]+"${!w_dst[@]}"}; do
		if [ "${w_dst[$i]%/*}" != "$FB_DIR" ]; then
			put "${w_src[$i]}" "${w_dst[$i]}" "${w_sha[$i]}"
		fi
	done
	for i in ${w_dst[@]+"${!w_dst[@]}"}; do
		if [ "${w_dst[$i]%/*}" = "$FB_DIR" ]; then
			put "${w_src[$i]}" "${w_dst[$i]}" "${w_sha[$i]}"
		fi
	done
	put "$tmp/fatboss.lua" "$FB_DIR/fatboss.lua" "$(cut -c1-64 "$tmp/fatboss.lua.sha256")"
	put "$tmp/fatboss-start.sh" "$FB_DIR/fatboss-start.sh" "$(cut -c1-64 "$tmp/fatboss-start.sh.sha256")"
	echo "legacy_v${etl}.pk3" > "$tmp/ETL_PK3"
	put "$tmp/ETL_PK3" "$FB_DIR/ETL_PK3"
	# only the new version's pk3s stay in /fatboss: containers copy exactly what is here.
	# They go last, once every new file is in place.
	for f in "$FB_DIR"/zzz_fatboss*.pk3; do
		[ -f "$f" ] || continue
		case " $PK3 ${skins[*]} " in *" $(basename "$f") "*) ;; *) rm -f "$f" && echo "removed $(basename "$f") from $FB_DIR" ;; esac
	done
	echo "Installed in $FB_DIR: $PK3 ${skins[*]} fatboss.lua fatboss-start.sh (built for ET: Legacy $etl)"
	echo "Copied to $WEB for the redirect: $PK3 ${skins[*]}"
	# players who lack the official pk3 download it too, and at 34 MB only the web
	# download finishes it (UDP stalls for good at 32 MiB): take it from a server that has it
	if [ ! -f "$WEB/legacy_v${etl}.pk3" ]; then
		for n in $(docker ps --format '{{.Names}}'); do
			# through $tmp and <name>.part, so an interrupted copy never leaves a half pk3 on the redirect
			if docker exec "$n" test -f "/legacy/server/legacy/legacy_v${etl}.pk3" 2>/dev/null \
				&& docker cp "$n:/legacy/server/legacy/legacy_v${etl}.pk3" "$tmp/" >/dev/null 2>&1; then
				put "$tmp/legacy_v${etl}.pk3" "$WEB/legacy_v${etl}.pk3"
				echo "Copied legacy_v${etl}.pk3 from $n to $WEB for the redirect"
				break
			fi
		done
	fi
	if [ ! -f "$WEB/legacy_v${etl}.pk3" ]; then
		echo "Note: no running container has legacy_v${etl}.pk3, and $WEB has none either."
		echo "      This FatBoss is for servers on that ET: Legacy version; on any other the servers start without FatBoss."
		echo "      Once a server runs it: docker cp etl-server1:/legacy/server/legacy/legacy_v${etl}.pk3 $WEB/"
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
       init: true                         # reaps the curl/mv fatboss.lua forks, or zombies fill the pids limit
       volumes:
         - "$FB_DIR:/fatboss:ro"          # next to the volumes it already has

3. Apply it when the server is empty (the container is recreated, the other servers are left alone).
   The image tag in VERSION (settings.env) must carry legacy_v${etl}.pk3; pull it first:
     cd $ETL_DIR && docker compose --env-file=settings.env pull etl-server1 && etl-server start 1
   ('etl-server start 1' is 'docker compose --env-file=settings.env up -d etl-server1';
    'etl-server restart' does not pick up compose or settings.env changes.)

4. Check (the image must carry the ET: Legacy this FatBoss is built for):
     docker exec etl-server1 ls /legacy/server/legacy | grep legacy_v      -> legacy_v${etl}.pk3
     docker logs etl-server1 2>&1 | grep -i fatboss | tail                 -> fatboss: loadouts from FatBoss, links on

EOF
	if [ -n "$running" ]; then
		echo "Already on FatBoss: $running- restart them to pick up this release:"
		for n in $running; do
			if docker exec "$n" test -f "/legacy/server/legacy/legacy_v${etl}.pk3" 2>/dev/null; then
				echo "     docker restart $n"
			else
				echo "     $n runs another ET: Legacy: move it to an image with legacy_v${etl}.pk3 (step 3); until then it runs without FatBoss"
			fi
		done
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
