--[[
    fatboss.lua - FatBoss cosmetics on the official ET: Legacy server.

    Works with the FatBoss cgame (zzz_fatboss_*.pk3) and its skins packs
    (zzz_fatboss_skin_*.pk3, zzz_fatboss_wear_*.pk3), which draw everything;
    this module decides who wears what and tells every client.

    Weapon skins: each player's FatBoss loadout picks a theme for the knife,
    colt, luger, thompson and mp40, and every copy has a CS2 wear (a float,
    0 Factory New .. 1 Battle-Scarred) the cgame shows as scratches. Everybody
    sees everybody's skins. The
    loadout (and the graffiti design) sits in a configstring of its own,
    FB_CS + client number, so it reaches every client with the gamestate and
    the cgame loads all textures on the loading screen; a change during the map
    is a configstring update the cgame applies at the intermission, on the next
    map or after /reconnect.

    Graffiti: a player binds "spray" (bind t spray). Three graffiti per life
    (FATBOSS_SPRAYS_PER_LIFE), a couple of seconds apart, and each player's
    newest graffiti replaces the older one: one per player on the walls.

    Loadouts come from FatBoss. With FATBOSS_LOADOUT_URL set, the module
    fetches this every minute in the background (FATBOSS_API_TOKEN is sent as
    a bearer token):
        {"<cl_guid>": {"graffiti": "gg",
                       "skins": {"knife": "damascus", "colt": "gold", "luger": "neon",
                                 "thompson": "wut", "mp40": "camo"},
                       "wear": {"knife": 0.031, "thompson": 0.512}}, ...}
    Without the URL, the same JSON is read from <fs_homepath>/legacy/fatboss_loadouts.json.

    Game link: the FatBoss profile shows "/fblink CODE"; a player pastes it in
    the console and the module posts {code, guid, name, server} to
    FATBOSS_LINK_URL (by default the loadout URL with /loadouts replaced by
    /link), then tells the player how it went.

    In-game Arsenal panel (cgame b11, ESC -> FatBoss Arsenal): the panel sends
    "fbinv"; the module asks FatBoss (/inventory, next to the loadout URL) for the
    items of the account this computer is linked to and sends them back in a few
    "fbinv_items" commands. "fbwear <id>" or "fbwear off <slot>" goes to /equip;
    the new loadout comes back with the answer and is set at once (during play:
    from the next round, 0.22). FatBoss only ever touches the account the
    player's cl_guid is linked to.

    StatTrak, stickers, name tags (cgame b13): the feed also gives, per slot, the
    worn copy's id ("ids"), its StatTrak count ("st", StatTrak copies only), its
    stickers ("stk", a base-36 design code per spot of the gun, "." for an empty
    one: five spots, four before 0.15) and its name ("tags"). Cgame b16 draws a
    sticker on the spot the player put it on (":j" in the configstring; b13-b15
    read four places of their own from ":k", which is gone). Two-char codes (0.18):
    with 75 designs a gun that carries one from 36 up gets two chars per spot from
    FatBoss (base 36, high then low, ".." for none: 8 or 10 chars, the length tells
    them apart) and ":J" in the configstring, which cgame b21 reads and b20 skips
    (no stickers rather than wrong ones; its Arsenal panel gets "-" for them).
    An enemy killed with a StatTrak copy's weapon in a real game
    (gamestate playing, not a teammate, not yourself) adds one to its count at
    once (the configstring shows it) and goes to FatBoss (/stattrak, next to the
    loadout URL) with the minute's loadout download (the same background shell,
    so the server starts no extra process) and when the map ends; FatBoss only
    counts copies the killer's linked account still owns. Name tags go to the
    owner's cgame alone ("fbtags"), once it said it knows them ("fbsync 13").
    A knife kill counts only when the knife used shows the worn theme (0.21):
    WuT is on the Allied KA-BAR only, so an Axis knife kill or backstab adds
    nothing to a WuT knife (every other knife theme covers both knives).

    map_restart (0.20): the end of the warmup and stopwatch round 2 start a new
    Lua VM, but the players stay and their cgames send no new fbsync. The build
    each cgame told goes into a server cvar of its slot (fatboss_cgame<slot> =
    "<build> <cl_guid>") when the map restarts and comes back when that slot
    connects again with the same cl_guid; any other start only clears them.

    FATBOSS_DEFAULT_GRAFFITI=fatboss lets players without a graffiti of their
    own spray that design (the FatBoss starter everybody gets).

    FATBOSS_TEST=1 (test servers only): everybody gets the "fatboss" graffiti,
    and /fbequip <slot> <theme> [wear] [st or st=N] [k=abcde] [n=Name] tries any skin
    or graffiti without FatBoss, as a StatTrak copy with stickers and a name if
    asked (its kills count on the server, nothing is reported).

    Punishment prop (0.16): an admin puts it on a player on the FatBoss website or
    Discord; the feed carries "prop" and "prop_until" for their computers, and the
    configstring gets "p:<prop>:<until>" after the graffiti. The FatBoss cgame b17
    draws it on their helmet (older cgames read six tokens and skip it). It goes
    at "prop_until" even when the feed stops. /fbequip prop dong [minutes] tries it.

    Request files (0.17): every call to FatBoss is a background curl (10 s at most)
    whose fatboss_link_*, fatboss_panel_* or fatboss_stattrak* .req/.tmp/.res files
    stay in <fs_homepath>/legacy until RunFrame reads the answer. Each name carries
    the time its Lua VM started, so a file an earlier run left is never taken for
    an answer of this one. A call dropped while the map runs (the player left, no
    answer in time) loses its files 30 s after it started. What a map leaves when
    it ends (calls still on their way, the last StatTrak report) and what a server
    leaves when it quits go with a later map: 30 s into every map, RunFrame starts
    one find that deletes the request files of other runs nobody changed for over
    a minute (two with busybox find). A map's last files are only seconds old when
    the next map sweeps, so they usually go with the map after that; after a quit
    they go with the first or second map of the next start.

    No stutter (0.22): nothing FatBoss does may cost a server frame or a player's
    snapshots.
    - The site answers the feed and the panel's item list in lines (?format=lines,
      FatBoss from 19.10; an older bot ignores it and sends JSON, read at once as
      before, so the bot goes first). The feed: "fatboss-loadouts 1 <stamp>",
      one line per computer "<cl_guid> <graffiti> <prop> <prop_until> <knife>
      <colt> <luger> <thompson> <mp40>" (a slot "-" or "theme,wear x 1000,id,
      stattrak,stickers,name tag", "-" for what it lacks, the name tag
      %-encoded), "end <lines>". The panel: "fatboss-inventory 1", "account
      <total> <name %-encoded>", "entry <the feed line's fields without the
      cl_guid>", one line per item (the token the panel gets), "end <lines>".
      Both are read a few lines a frame (COST) into a new table that is put in
      place only once the "end" line matched; every field goes through the same
      checks as the JSON. The stamp is a hash of the rest of the feed, so an
      unchanged feed costs RunFrame one short line, never a whole read; the
      lines of computers that are not on the server are kept as they came and
      read when the player joins.
    - The panel's list goes out as fast as the player's line carries it: ET
      writes every command the client has not acknowledged into every snapshot,
      so the bytes this module sent in the last ping + snapshot must fit beside
      the snapshot (NET.reserve) in rate / snaps of the client (its userinfo,
      sv_maxRate / sv_minRate, sv_fps), in commands that fit one snapshot. What
      goes to everybody during play (a configstring change: a feed, a StatTrak
      kill, a panel answer; a graffiti) waits until every client's line has room
      for it, and while it waits no new panel command starts on the lines that
      lack the room, so it goes within a round trip (after NET.ledger ms it goes
      anyway). The frame a feed goes in place only compares each player's look,
      worked out once per loadout; a client's budget reads its userinfo again
      only when it changed: a full server costs the frame little.
    - A new look (theme, wear, stickers, name tag, graffiti) FatBoss sends for a
      player on the server during play shows from the next round, warmup or
      intermission; the changer hears it once a round. StatTrak counts (kills
      count on the copy that is shown) and the punishment prop still go out at
      once. A computer just linked with /fblink and the feed the map start
      downloads (it lands a few seconds in) show at once. A panel change during
      play no longer downloads the whole feed again; a feed asked for before it
      does not undo it. The loadout file a map_restart or the next map reads is
      fresh: it is downloaded when the countdown or the intermission begins, and
      after a skin change outside play (a map_restart can come any moment then).
    - The panel opened again while its list is still on its way gets that list
      (b22 keeps taking it), not a refusal that would cut it; after a cgame
      restart (fbsync) the next fbinv gets the whole list again.

    Runs next to Oksii's stats.lua and combinedfixes.lua in its own Lua VM and
    handles only its own commands ("spray", "fblink", "fbsync", "fbinv", "fbwear",
    and "fbequip" in test mode).
    fbsync (a cgame restart) gets the graffiti on the map again; skins need nothing.
]]

local json = require("dkjson")

local MODNAME = "fatboss"
local VERSION = "0.22"

local SLOTS           = { "knife", "colt", "luger", "thompson", "mp40" }   -- order in the configstring
local PROPS           = { dong = true }   -- punishment props the FatBoss cgame draws (b17)
-- first configstring past CS_MAX of ET: Legacy 2.86 (bg_public.h); the FatBoss cgame reads FB_CS + client
local FB_CS           = 943
local THEMES_HELP     = "fade nebula case redline frontier glacier pearl inferno emerald scales tiger marble skill_issue caution_noob "
                     .. "sticker_bomb knockoff connection_interrupted sale gold polska neon camo cyber plasma airstrike "
                     .. "damascus (knives) defender (colt) wut (thompson, kabar) "
                     .. "wyrmfire jade_serpent orbital synthwave kintsugi magma sapphire ruby black_pearl "
                     .. "crimson_web filigree carbon aurora sakura hex_reactor holo_prism blood_moon checkmate "
                     .. "neon_oni grandma_carpet googly_eyes duct_tape crayon_kid rubber_ducky hot_dog_stand princess_mode laser_cats "
                     .. "honk_honk "
                     .. "rabid_beast golden_coil empress mecha_unit red_vector black_ice corrupted neon_tokyo "
                     .. "lost_space toxic_breach nitro quantum bullet_rain neon_riot ti_burn laminate rust_coat "
                     .. "trench_art butcher pinstripe hot_rod wycinanki amber freehand enigma toy_blaster cardboard "
                     .. "comic_pow ugly_sweater gummy disco_ball bubblegum wildstyle leopard_diva lava_lamp "
                     .. "happy_trees"
-- /fbequip's list of every graffiti design
local GRAFFITI_HELP   = "fatboss poland_et gg ez gibbed noob nice_try cloudy skill_issue jebac_axis jebac_allies "
                     .. "kurwa_mac wut_1112 sprzedam_opla nastepny_przystanek next_stop skill_404 rip_bozo lagging "
                     .. "get_rekt spawn_camper arty_incoming dyno_planted headshot one_tap rage_quit skill_diff cry_more "
                     .. "brb_coffee panzer_noob potato_aim toaster_pc honk eat_shit git_gud_bitch suck_my_panzer "
                     .. "fuck_your_ping stfu_noob ur_mom certified_shitter asshat wtf_was_that holy_shit kiss_my_ass "
                     .. "touch_grass uninstall who_asked wallhack free_kill go_next alt_f4 hold_w cope_seethe no_scope "
                     .. "defused_lol beep_beep smoke_break airstrike_on_me oops mg42_brrr docs_stolen teamkiller "
                     .. "trust_covert obj_what_obj send_nukes bonk big_brain npc wanted rip_kd open_24_7 spierdalaj "
                     .. "no_i_chuj co_kurwa ja_pierdole"
-- /fbequip wear by condition: the middle of each CS2 range
local CONDITION_WEAR  = { fn = 0.035, mw = 0.11, ft = 0.265, ww = 0.415, bs = 0.72 }
local SPRAY_RANGE     = 128
local SPRAY_RADIUS    = 28      -- half the side of the graffiti square, in game units
local SPRAY_SCALES    = { 1.0, 0.8, 0.6 }
local SPRAY_SHIFTS    = { { 0, 0 }, { 0.35, 0 }, { -0.35, 0 }, { 0, 0.35 }, { 0, -0.35 },
                          { 0.3, 0.3 }, { -0.3, 0.3 }, { 0.3, -0.3 }, { -0.3, -0.3 } }
local ENTITYNUM_WORLD = (et.MAX_GENTITIES or 1024) - 2
local SURF_SKY        = 0x4
local SURF_NOMARKS    = 0x20
-- invisible brushes (clip in front of a detailed wall): the trace hits them, but the
-- client has no surface there to paint on, so the graffiti would silently not show
local SURF_NODRAW     = 0x80
local TEAM_AXIS       = 1
local TEAM_ALLIES     = 2
local CON_CONNECTED   = 2
local FETCH_MS        = 60000
local READ_MS         = 5000
local MESSAGE_GAP_MS  = 1500
local LINK_WAIT_MS    = 15000   -- how long a /fblink waits for FatBoss to answer
local LINK_GAP_MS     = 5000    -- one /fblink per player every few seconds
local SYNC_GAP_MS     = 3000    -- one fbsync (a cgame restart) per player every few seconds
local SPRAY_GAP_MS    = 2000    -- between two graffiti of one player
-- between two spray attempts of one player, refused ones too (0.19): a spray where the graffiti does not fit
-- costs up to ~244 traces, so a bound flood of "spray" must not reach them every frame
local SPRAY_TRY_MS    = 400
local PANEL_GAP_MS    = 500     -- one panel request (list, wear) per player every half second
local PANEL_WAIT_MS   = 15000   -- how long a panel request waits for FatBoss
local PANEL_CHUNK     = 700     -- characters of items per fbinv_items command, at most (a fast line)
local PANEL_MIN_CHUNK = 160     -- and at least: one item token always fits (the cgame reads 159 chars of one)
local REPORT_WAIT_MS  = 15000   -- StatTrak kills go to FatBoss with the minute's download (and when the map ends)
local CURL_MAX_S      = 10      -- curl's --max-time for every call to FatBoss
-- a request nobody waits for any more leaves its files until this long after it started: its curl is over by then
local CURL_DONE_MS    = 30000
local SWEEP_PER_FRAME = 4       -- abandoned requests whose files go in one frame, at most
-- what a request leaves in homeDir: <base>.req (the body), .tmp (curl's download), .res (the answer)
local REQUEST_FILES   = { "fatboss_link_*", "fatboss_panel_*", "fatboss_stattrak*" }
-- the map's sweep of earlier runs' request files skips a file changed in the last minute (find -mmin +1;
-- two minutes with busybox): no curl writes it any more
local SWEEP_AGE_MIN   = 1
local GS_PLAYING      = "0"
-- the countdown (GS_WARMUP_COUNTDOWN) ends in a map_restart, the intermission in the next map or a map_restart: a new
-- Lua VM that reads the loadout file (0.22)
local GS_RESTARTS     = { ["1"] = true, ["3"] = true }
-- the site's line format (0.22, see the top); a bot before 19.10 ignores the question and answers JSON
local LINES = {
    query = "format=lines",
    feed  = "^fatboss%-loadouts 1 (%w+)$",          -- the feed's first line, with its stamp
    inv   = "fatboss-inventory 1",                  -- the panel answer's first line
    line  = "^(%w+) (%S+) (%S+) (%S+) (%S+) (%S+) (%S+) (%S+) (%S+)$",
    entry = "^entry (%S+) (%S+) (%S+) (%S+) (%S+) (%S+) (%S+) (%S+)$",
    slot  = "^([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+)$",
    item  = "^(%d+),([%l%d]+),([%w_]+),(%-?%d+),(%d+),(%d+),(%-?%d+),([^,%s]+),([^,%s]+)$",
}
-- the work one server frame does for the site's answers, all together, in rough microseconds of Lua (measured on a
-- desktop i9; a VPS core takes about twice that): a feed line kept as it came (line), a feed line of a player on the
-- server read into a loadout (parse), a panel item turned into its token (item), a whole feed put in place (swap: a
-- player on the server, the frame after its last line), a player's configstring checked (check) and changed (change)
local COST = { frame = 200, line = 4, parse = 40, item = 4, swap = 12, check = 5, change = 30 }
-- the feed the map start downloads lands a few seconds into the round: it still counts as the round's start
local ROUND_START_MS  = 20000
-- reliable commands go to a client no faster than its line carries them (0.22). ET writes every command the client
-- has not acknowledged into every snapshot until the ack comes back, so what this module sent in the last ping +
-- snapshot must fit, beside the snapshot itself (reserve: playerstate, entities, other scripts' commands), in what
-- one snapshot may take of the client's rate (sv_snapshot.c SV_RateMsec), unfragmented (net_chan.c)
local NET = {
    reserve  = 260,
    -- UDP/IP header (UDPIP_HEADER_SIZE 28) + the netchan sequence (4) + 1: SV_RateMsec lets the next snapshot go only
    -- when more time passed than the last message took on the line, so a message that fills it exactly delays it
    overhead = 33,
    fragment = 1300,     -- MAX_PACKETLEN - 100: a message this big goes in fragments and the next snapshot waits
    huff     = 1.08,     -- bytes on the wire a char after ET's Huffman coding (item commands 1.07-1.09 with their
                         -- header, configstrings 1.04-1.06)
    cmd      = 8,        -- svc_serverCommand, the command's sequence number and the closing NUL
    ledger   = 2000,     -- the longest anything counts as unacknowledged here (ping 999 + a snapshot)
    snapMs   = 50,       -- a client without "snaps": DEFAULT_SV_FRAMETIME
}
local PUBLISH_PER_FRAME = 4     -- players whose configstring is rebuilt in one frame (a feed, a report, a round end)
local CGAME_TAGS      = 13      -- the first FatBoss cgame that shows name tags ("fbsync 13")
local CGAME_WIDE_STK  = 21      -- the first FatBoss cgame that reads two-char sticker codes (":J")
-- a map_restart keeps each cgame build in BUILD_CVAR .. slot (0.20): one cvar per slot, because Lua reads at most
-- 255 chars of a cvar; every slot the engine has (MAX_CLIENTS) is cleared at the next start
local BUILD_CVAR      = "fatboss_cgame"
local MAX_SLOTS       = 64
-- means of death -> the slot whose StatTrak copy counts the kill (bg_public.h of ET: Legacy 2.86)
local MOD_SLOT        = {
    [5] = "knife", [61] = "knife", [65] = "knife",                       -- knife, KA-BAR, backstab
    [6] = "luger", [12] = "luger", [54] = "luger", [56] = "luger",       -- luger, silenced, akimbo, akimbo silenced
    [7] = "colt", [45] = "colt", [53] = "colt", [55] = "colt",           -- colt, silenced, akimbo, akimbo silenced
    [8] = "mp40", [9] = "thompson",
}
-- which knife made a knife kill (0.21): MOD_KNIFE is the Axis knife, MOD_KNIFE_KABAR the Allied KA-BAR; a backstab
-- (MOD_BACKSTAB) names neither, so it is the knife in the killer's hand, read as the game's obituary reads it
-- (s.weapon: WP_KNIFE 1, WP_KNIFE_KABAR 48)
local MOD_KNIFE_USED  = { [5] = "knife", [61] = "kabar" }
local WP_KNIFE_USED   = { [1] = "knife", [48] = "kabar" }
-- themes in the knife slot that leave a knife stock, as the FatBoss cgame draws them (cg_fatboss_skins.inc) and the
-- bot sells them (SKIN_THEMES): WuT is on the KA-BAR only, Defender (a Colt skin) on neither; every other theme
-- covers both knives
local KNIFE_COVER     = { wut = { kabar = true }, defender = {} }

local loadouts     = {}  -- cl_guid (upper case) -> { graffiti = design, skins = { slot = theme }, wear = { slot = 0..1 } }
local testLoadouts = {}  -- the same, set with /fbequip in test mode; wins over loadouts
local setStrings   = {}  -- clientNum -> loadout configstring last set
local synced       = {}  -- clientNum -> true once the client got the graffiti on the map
local sprays       = {}  -- clientNum -> fbspray command without the sound flag
local sprayCount   = {}  -- clientNum -> graffiti sprayed in the current life
local lastSpray    = {}  -- clientNum -> time of the last graffiti
local lastTry      = {}  -- clientNum -> time of the last spray attempt that got past the gap checks
local lastMessage  = {}  -- clientNum -> level time of the last refusal
local links        = {}  -- clientNum -> { file, base, started, guid, deadline } of a /fblink waiting for FatBoss
local lastLink     = {}  -- clientNum -> time of the last /fblink
local lastSync     = {}  -- clientNum -> time the client last got everything
local requests     = {}  -- clientNum -> { file, base, started, guid, kind, deadline } of a panel request waiting for FatBoss
local lastPanel    = {}  -- clientNum -> time of the last panel request
local outbox       = {}  -- clientNum -> commands of an item list still to send
local stPending    = {}  -- copy id -> { guid, n }: StatTrak kills not reported yet
local stInflight   = nil -- { file, base, started, deadline, ids = { copy id -> n } } of the report on its way
local stFloor      = {}  -- copy id -> count FatBoss confirmed (a feed read before the report stays below it)
local cgameBuild   = {}  -- clientNum -> the FatBoss cgame build it announced with fbsync
local keptBuilds   = {}  -- clientNum -> { build, guid } the map_restart kept, until that slot connects again
local sentTags     = {}  -- clientNum -> fbtags command last sent
local abandoned    = {}  -- { base, deadline } of requests nobody waits for: their files go at the deadline
local sweepAt      = nil -- trap_Milliseconds time of this map's sweep of earlier runs' request files (nil: done)
-- 0.22
local held         = {}  -- cl_guid -> a loadout with a new look FatBoss sent during play, in effect from the next round
                         --   (false: nothing worn any more); loadouts[] keeps the look on screen meanwhile
local takenAt      = {}  -- cl_guid -> frameTime of the last loadout a panel answer set (an older feed never undoes it)
local justLinked   = {}  -- cl_guid -> true from a /fblink until its first loadout, which shows at once
local toldHeld     = {}  -- clientNum -> true once told this round that a change shows from the next round
local feedJob      = nil -- the feed being read, a few lines a frame: { next, close, fresh, count, lines, fetched, roundStart }
local invJobs      = {}  -- clientNum -> a panel answer in lines being read: { guid, next, tokens, lines, total, name, entry }
local ledger       = {}  -- clientNum -> { t = {}, n = {}, head, tail }: reliable bytes this module sent, for the pacing
local bots         = {}  -- clientNum -> true for a bot (no line to pace)
local frameTime    = 0   -- trap_Milliseconds of the last RunFrame (the clock of everything 0.22 times)
local work         = 0   -- what is left of this frame's COST.frame
local readyFeed    = nil -- a feed read to its "end" line, put in place at the start of the next frame
-- clientNum -> budgetOf, worked out once a frame (at, room, window), and what it is worked out from: the userinfo
-- (info) and the server's cvars (of) a client's line (line: room) and snapshot (snap: ms) were read with
local budgets      = { at = {}, room = {}, window = {}, info = {}, of = {}, line = {}, snap = {} }
-- what goes to everybody during play and waits for room on every line (castNow): queue = graffiti commands in order,
-- since = frameTime the wait began, blocked = something waits this frame, full = clientNum -> true for the lines it
-- waits for this frame (no new panel command starts on them)
local casts        = { queue = {}, since = nil, blocked = false, full = {} }
local lastGamestate, roundStartUntil, publishAt, lastFetchAt = nil, 0, nil, -1
local lastStamp, failedStamp  -- the stamp of the feed in effect, and of the last one that was broken
local entryOf      -- cl_guid -> its loadout in effect (see below: a feed line is read the first time it is needed)
-- in every request file name: trap_Milliseconds starts at 0 again with every server process, so without the time
-- this Lua VM started, a file an earlier run left could have the name of a new request and pass for its answer;
-- the sweep also tells this map's own files by it
local RUN          = os.time()
local inventoryUrl, equipUrl, stattrakUrl
local loadoutPath, loadoutUrl, linkUrl, apiToken, testMode, defaultGraffiti, maxClients, homeDir, spraysPerLife
local nextFetch, nextRead, lastLoadoutText = 0, 0, nil

local function shellQuote(s)
    return "'" .. tostring(s):gsub("'", "'\"'\"'") .. "'"
end

-- the files of one background request (see REQUEST_FILES)
local function removeRequestFiles(base)
    os.remove(base .. ".req")
    os.remove(base .. ".tmp")
    os.remove(base .. ".res")
end

-- a request nobody waits for any more (the player left, no answer in time, a new map): curl still writes the
-- answer, so its files go once that curl is surely over - now, when the answer is already here.
-- pending: { base, started } of a link, panel request or StatTrak report (nil: nothing)
local function abandon(pending)
    if not pending then
        return
    end
    local f = io.open(pending.base .. ".res", "r")
    if f then
        f:close()
        removeRequestFiles(pending.base)
    else
        abandoned[#abandoned + 1] = { base = pending.base, deadline = pending.started + CURL_DONE_MS }
    end
end

-- the files of abandoned requests whose time is up, a few per frame
local function sweepAbandoned(now)
    local i, done = 1, 0
    while abandoned[i] and done < SWEEP_PER_FRAME do
        if now >= abandoned[i].deadline then
            removeRequestFiles(abandoned[i].base)
            table.remove(abandoned, i)
            done = done + 1
        else
            i = i + 1
        end
    end
end

-- Request files left by earlier runs: the last map's Lua VM went with whatever it still waited for, a server can
-- stop mid-request, and 0.16 left every dropped answer behind. RunFrame calls this once, 30 s into the map: one
-- find (and the rm it batches) deletes the request files without this VM's RUN in the name that nobody changed for
-- a minute, so neither a request of this map nor a file a curl still writes. Nothing waits in the background.
local function sweepLeftovers()
    local names = {}
    for _, name in ipairs(REQUEST_FILES) do
        names[#names + 1] = "-name " .. shellQuote(name)
    end
    -- a path that starts with "-" would read as a find option
    local dir = homeDir:sub(1, 1) == "-" and "./" .. homeDir or homeDir
    os.execute(string.format("find %s -maxdepth 1 -type f \\( %s \\) \\( -name '*.req' -o -name '*.tmp' -o -name '*.res' \\) ! -name '*_%d_*' -mmin +%d -exec rm -f {} + >/dev/null 2>&1 &",
        shellQuote(dir), table.concat(names, " -o "), RUN, SWEEP_AGE_MIN))
end

-- design and theme names reach shader paths on the clients: [a-z0-9_] only
local function validName(name)
    return type(name) == "string" and #name > 0 and #name <= 32 and name:match("^[a-z0-9_]+$") ~= nil
end

local function guidOf(clientNum)
    local userinfo = et.trap_GetUserinfo(clientNum)
    return (et.Info_ValueForKey(userinfo, "cl_guid") or ""):upper()
end

local function connected(clientNum)
    return et.gentity_get(clientNum, "pers.connected") == CON_CONNECTED
end

local function isPlaying()
    return et.trap_Cvar_Get("gamestate") == GS_PLAYING
end

-- ------------------------------------------------------------------ pacing (0.22)

-- a reliable command's bytes on the wire, roughly (ET's Huffman coding and the command's header)
local function wireBytes(cmd)
    return math.ceil(#cmd * NET.huff) + NET.cmd
end

local function logBytes(clientNum, bytes)
    local l = ledger[clientNum]
    if not l then
        l = { t = {}, n = {}, head = 1, tail = 0 }
        ledger[clientNum] = l
    end
    local now = et.trap_Milliseconds()
    l.tail = l.tail + 1
    l.t[l.tail], l.n[l.tail] = now, bytes
    while l.head < l.tail and l.t[l.head] <= now - NET.ledger do
        l.t[l.head], l.n[l.head] = nil, nil
        l.head = l.head + 1
    end
end

-- what this module sent the client in the last window ms: what ET may still write into its next snapshot
local function inFlight(clientNum, window)
    local l = ledger[clientNum]
    if not l then
        return 0
    end
    local sum, since = 0, et.trap_Milliseconds() - window
    for i = l.tail, l.head, -1 do
        if l.t[i] <= since then
            break
        end
        sum = sum + l.n[i]
    end
    return sum
end

-- a reliable command to a client (-1: everybody), counted for the pacing
local function send(clientNum, cmd)
    et.trap_SendServerCommand(clientNum, cmd)
    local bytes = wireBytes(cmd)
    if clientNum >= 0 then
        return logBytes(clientNum, bytes)
    end
    for c = 0, maxClients - 1 do
        if connected(c) then
            logBytes(c, bytes)
        end
    end
end

-- Q_atoi: the leading number, 0 for none
local function atoi(text)
    return math.tointeger(tonumber((text or ""):match("^%s*([%-+]?%d+)") or "0") or 0) or 0
end

-- what one snapshot of the client may carry beside the snapshot itself, and how long a command stays unacknowledged
-- (in every snapshot from the first one until the ack comes back: ping + a snapshot). rate and snaps as
-- SV_UserinfoChanged reads the userinfo, sv_maxRate / sv_minRate as SV_RateMsec applies them
local function budgetOf(clientNum)
    if budgets.at[clientNum] == frameTime then
        return budgets.room[clientNum], budgets.window[clientNum]
    end
    -- the server's cvars once a frame (a new table only when one changed), a client's userinfo read again only when
    -- it changed: a full server's budgets cost a frame little (0.22)
    if budgets.cvarsAt ~= frameTime then
        budgets.cvarsAt = frameTime
        local maxRate, minRate, fps = atoi(et.trap_Cvar_Get("sv_maxRate")), atoi(et.trap_Cvar_Get("sv_minRate")), atoi(et.trap_Cvar_Get("sv_fps"))
        local c = budgets.cvars
        if not c or c[1] ~= maxRate or c[2] ~= minRate or c[3] ~= fps then
            budgets.cvars = { maxRate, minRate, fps }
        end
    end
    local userinfo, cvars = et.trap_GetUserinfo(clientNum), budgets.cvars
    if budgets.info[clientNum] ~= userinfo or budgets.of[clientNum] ~= cvars then
        local value = et.Info_ValueForKey(userinfo, "rate") or ""
        local rate = math.max(1000, math.min(90000, value == "" and 5000 or atoi(value)))
        local maxRate, minRate, fps = cvars[1], cvars[2], cvars[3] > 0 and cvars[3] or 20
        if maxRate > 0 then
            rate = math.min(rate, math.max(1000, maxRate))
        end
        if minRate > 0 then
            rate = math.max(rate, math.max(1000, minRate))
        end
        rate = math.max(1000, math.min(90000, rate))
        value = et.Info_ValueForKey(userinfo, "snaps") or ""
        local snapMs = value == "" and NET.snapMs or 1000 // math.max(1, math.min(fps, atoi(value)))
        budgets.info[clientNum], budgets.of[clientNum], budgets.snap[clientNum] = userinfo, cvars, snapMs
        budgets.line[clientNum] = math.min(rate * snapMs / 1000 - NET.overhead, NET.fragment - 1) - NET.reserve
    end
    local ping = math.max(0, math.min(999, tonumber(et.gentity_get(clientNum, "ps.ping")) or 0))
    local room, window = budgets.line[clientNum], ping + budgets.snap[clientNum]
    budgets.at[clientNum], budgets.room[clientNum], budgets.window[clientNum] = frameTime, room, window
    return room, window
end

-- whether a command of so many bytes fits every client's line now (a configstring change goes to everybody); with
-- nothing in flight it always goes, so a slow line still gets everything in the end. full: the clients whose line
-- has no room for it are marked there
local function roomForAll(bytes, full)
    local ok = true
    for c = 0, maxClients - 1 do
        if connected(c) and not bots[c] then
            local room, window = budgetOf(c)
            local busy = inFlight(c, window)
            if busy > 0 and busy + bytes > room then
                if not full then
                    return false
                end
                ok, full[c] = false, true
            end
        end
    end
    return ok
end

-- whether a command of so many bytes for everybody may go now: always outside play; during play when every line has
-- room (roomForAll). Otherwise it waits, and drainOutbox starts no new panel command on the lines it waits for
-- (casts.full), so they empty within a round trip and it goes first; one that waited NET.ledger ms goes anyway (a
-- client that keeps its own line full with its own commands holds nobody up longer)
local function castNow(bytes)
    if not isPlaying() or roomForAll(bytes, casts.full) then
        return true
    end
    if casts.since and frameTime - casts.since >= NET.ledger then
        casts.since = frameTime
        return true
    end
    casts.since, casts.blocked = casts.since or frameTime, true
    return false
end

local function loadoutOf(clientNum)
    local guid = guidOf(clientNum)
    if guid == "" then
        return {}
    end
    return testLoadouts[guid] or entryOf(guid) or {}
end

-- the StatTrak count a slot shows: FatBoss's (or the higher one it confirmed to a report since),
-- plus the kills on their way to it; nil for a copy without StatTrak
local function stattrakCount(loadout, slot)
    local count = loadout.st and loadout.st[slot]
    local id = loadout.ids and loadout.ids[slot]
    if not count or not id then
        return count
    end
    count = math.max(count, stFloor[id] or 0) + (stPending[id] and stPending[id].n or 0)
    return count + (stInflight and stInflight.ids[id] or 0)
end

-- "<knife> <colt> <luger> <thompson> <mp40> <graffiti>", "-" for stock; a skin is "theme:NNN" with the
-- copy's wear x 1000, then ":sN" for a StatTrak count and ":jabcde" for its stickers, one per spot, or
-- ":J0a1b...." with two chars per spot once a design is 36 or more (cgame b21; b12 reads the theme and the wear
-- and skips the rest, b20 skips ":J"); "" for nothing at all (a small gamestate)
local function loadoutString(clientNum)
    local loadout = loadoutOf(clientNum)
    local skins, wear, stk = loadout.skins or {}, loadout.wear or {}, loadout.stk or {}
    local parts, any = {}, false
    for _, slot in ipairs(SLOTS) do
        local theme = skins[slot]
        if theme then
            if wear[slot] then
                theme = string.format("%s:%d", theme, math.min(1000, math.floor(wear[slot] * 1000 + 0.5)))
            end
            local count = stattrakCount(loadout, slot)
            if count then
                theme = string.format("%s:s%d", theme, math.min(count, 999999))
            end
            if stk[slot] and slot ~= "knife" then
                theme = theme .. (#stk[slot] >= 8 and ":J" or ":j") .. stk[slot]
            end
        end
        parts[#parts + 1] = theme or "-"
        any = any or theme ~= nil
    end
    local graffiti = loadout.graffiti or defaultGraffiti
    parts[#parts + 1] = graffiti or "-"
    -- the punishment prop, until its time is up: "p:<prop>:<until, unix time>" (cgame b17; older ones read six tokens)
    local prop = loadout.prop and (loadout.propUntil or 0) > os.time() and loadout.prop or nil
    if prop then
        parts[#parts + 1] = string.format("p:%s:%d", prop, loadout.propUntil)
    end
    if not any and not graffiti and not prop then
        return ""
    end
    return table.concat(parts, " ")
end

local function csCommand(clientNum, value)
    return string.format('cs %d "%s"', FB_CS + clientNum, value)
end

local function setLoadout(clientNum, value)
    if setStrings[clientNum] ~= value then
        setStrings[clientNum] = value
        et.trap_SetConfigstring(FB_CS + clientNum, value)
        -- ET sends the change to every client as a reliable command
        local bytes = wireBytes(csCommand(clientNum, value))
        for c = 0, maxClients - 1 do
            if connected(c) then
                logBytes(c, bytes)
            end
        end
    end
end

-- a player's configstring after a change of their own (a StatTrak kill, a panel answer): at once when it may go
-- (castNow), else from publishStep, which keeps trying
local function publishOne(clientNum)
    local value = loadoutString(clientNum)
    if value == setStrings[clientNum] then
        return
    end
    if castNow(wireBytes(csCommand(clientNum, value))) then
        return setLoadout(clientNum, value)
    end
    publishAt = math.min(publishAt or clientNum, clientNum)
end

-- a command for everybody (a graffiti): at once when it may go (castNow), else in turn from castStep
local function cast(cmd)
    if not casts.queue[1] and castNow(wireBytes(cmd)) then
        return send(-1, cmd)
    end
    casts.queue[#casts.queue + 1] = cmd
end

local function castStep()
    while casts.queue[1] and castNow(wireBytes(casts.queue[1])) do
        send(-1, table.remove(casts.queue, 1))
    end
end

-- the names of a player's worn copies, to their own cgame only (the inspect card shows them);
-- cgames before b13 do not know the command, they never get it
local function sendTags(clientNum)
    if (cgameBuild[clientNum] or 0) < CGAME_TAGS then
        return
    end
    local tags = loadoutOf(clientNum).tags or {}
    local parts = {}
    for _, slot in ipairs(SLOTS) do
        parts[#parts + 1] = '"' .. (tags[slot] or "") .. '"'
    end
    local cmd = "fbtags " .. table.concat(parts, " ")
    if sentTags[clientNum] ~= cmd then
        sentTags[clientNum] = cmd
        send(clientNum, cmd)
    end
end

-- every connected player's loadout into its configstring (only the changed ones go out), a few players a frame from
-- RunFrame (publishStep); now: all of them at once
local function publishLoadouts(now)
    if not now then
        publishAt = 0
        return
    end
    publishAt = nil
    for clientNum = 0, maxClients - 1 do
        if connected(clientNum) then
            setLoadout(clientNum, loadoutString(clientNum))
            sendTags(clientNum)
        end
    end
end

-- PUBLISH_PER_FRAME players a frame at most, within what is left of the frame's work; during play a changed
-- configstring also waits until every client's line has room for it (it goes to everybody: castNow)
local function publishStep()
    local checked = 0
    while publishAt and publishAt < maxClients do
        local c = publishAt
        if connected(c) then
            if checked >= PUBLISH_PER_FRAME or (checked > 0 and work <= 0) then
                return
            end
            checked = checked + 1
            work = work - COST.check
            local value = loadoutString(c)
            if value ~= setStrings[c] then
                work = work - COST.change
                if not castNow(wireBytes(csCommand(c, value))) then
                    return
                end
            end
            setLoadout(c, value)
            sendTags(c)
        end
        publishAt = c + 1
    end
    publishAt = nil
end

-- a name tag as FatBoss allows it: 1-20 of letters, digits, spaces and . , ! ? ' _ -
local function validTag(tag)
    return type(tag) == "string" and #tag >= 1 and #tag <= 20 and tag:match("^[%w .,!?'_%-]+$") ~= nil
end

-- the sticker spots of a gun (five at most; four before FatBoss sent spots), at least one sticker: a base-36
-- design code each or "." for none (4-5 chars), or, once a design is 36 or more, two chars each, high then low,
-- or ".." for none (8 or 10 chars, 0.18)
local function validStickers(codes)
    if type(codes) ~= "string" or not codes:match("[0-9a-z]") then
        return false
    end
    if #codes == 4 or #codes == 5 then
        return codes:match("^[0-9a-z%.]+$") ~= nil
    end
    if #codes ~= 8 and #codes ~= 10 then
        return false
    end
    for i = 1, #codes, 2 do
        local pair = codes:sub(i, i + 1)
        if pair ~= ".." and not pair:match("^[0-9a-z][0-9a-z]$") then
            return false
        end
    end
    return true
end

local function tableOr(t)
    return type(t) == "table" and t or {}
end

local function parseEntry(entry)
    if type(entry) ~= "table" then
        return nil
    end
    local out = {}
    if validName(entry.graffiti) then
        out.graffiti = entry.graffiti
    end
    if type(entry.skins) == "table" then
        out.skins, out.wear, out.ids, out.st, out.stk, out.tags = {}, {}, {}, {}, {}, {}
        local wear, ids, st, stk, tags = tableOr(entry.wear), tableOr(entry.ids), tableOr(entry.st), tableOr(entry.stk), tableOr(entry.tags)
        for _, slot in ipairs(SLOTS) do
            if validName(entry.skins[slot]) then
                out.skins[slot] = entry.skins[slot]
                local w = tonumber(wear[slot])
                if w and w >= 0 and w <= 1 then
                    out.wear[slot] = w
                end
                local id = tonumber(ids[slot])
                if id and id >= 1 and id == math.floor(id) then
                    out.ids[slot] = id
                end
                local n = tonumber(st[slot])
                if n and n >= 0 then
                    out.st[slot] = math.floor(n)
                end
                if validStickers(stk[slot]) then
                    out.stk[slot] = stk[slot]
                end
                if validTag(tags[slot]) then
                    out.tags[slot] = tags[slot]
                end
            end
        end
    end
    local propUntil = tonumber(entry.prop_until)
    if validName(entry.prop) and PROPS[entry.prop] and propUntil then
        out.prop, out.propUntil = entry.prop, math.floor(propUntil)
    end
    return out
end

-- ------------------------------------------------------------------ the line format (0.22)

-- a %-encoded field (name tags, the account name) back to its bytes
local function decodeTag(text)
    return (text:gsub("%%(%x%x)", function(hex)
        return string.char(tonumber(hex, 16))
    end))
end

-- the fields of a feed line (without the cl_guid) as the JSON entry they stand for: parseEntry checks them all
local function lineEntry(graffiti, prop, propUntil, ...)
    if not graffiti then
        return nil
    end
    local entry = { skins = {}, wear = {}, ids = {}, st = {}, stk = {}, tags = {} }
    if graffiti ~= "-" then
        entry.graffiti = graffiti
    end
    if prop ~= "-" then
        entry.prop, entry.prop_until = prop, tonumber(propUntil)
    end
    for i, field in ipairs({ ... }) do
        local slot = SLOTS[i]
        local theme, wear, id, st, stk, tag = field:match(LINES.slot)
        if slot and theme then
            entry.skins[slot] = theme
            entry.wear[slot] = wear ~= "-" and (tonumber(wear) or -1) / 1000 or nil
            entry.ids[slot] = id ~= "-" and tonumber(id) or nil
            entry.st[slot] = st ~= "-" and tonumber(st) or nil
            entry.stk[slot] = stk ~= "-" and stk or nil
            entry.tags[slot] = tag ~= "-" and decodeTag(tag) or nil
        end
    end
    return entry
end

-- a feed line read into a loadout (nil for a broken one)
local function lineLoadout(line)
    local _, graffiti, prop, propUntil, knife, colt, luger, thompson, mp40 = line:match(LINES.line)
    return parseEntry(lineEntry(graffiti, prop, propUntil, knife, colt, luger, thompson, mp40))
end

-- what a player sees of a loadout, and the cgame loads textures for: theme, wear, which copy (a StatTrak one or
-- not), stickers, name tag, graffiti. Not in it: the StatTrak count and the punishment prop, which go out at once.
-- Worked out once per loadout and kept in it (look): a loadout's fields never change once it is made (a kill on a
-- copy without an id changes the count, which is not in the look), so the frame that puts a feed in place only
-- compares strings, however many players are on the server
local function lookOf(entry)
    entry = entry or {}
    if entry.look then
        return entry.look
    end
    local skins, wear, ids, st, stk, tags = entry.skins or {}, entry.wear or {}, entry.ids or {}, entry.st or {}, entry.stk or {}, entry.tags or {}
    local parts = { entry.graffiti or "-" }
    for _, slot in ipairs(SLOTS) do
        parts[#parts + 1] = skins[slot] and string.format("%s/%s/%s/%s/%s/%s", skins[slot], tostring(wear[slot]), tostring(ids[slot]),
            st[slot] and "st" or "", stk[slot] or "", tags[slot] or "") or "-"
    end
    entry.look = table.concat(parts, " ")
    return entry.look
end

-- The feed keeps the line of every computer that is not on the server as it came, and reads it the first time it is
-- needed (the player joins): a feed of hundreds of computers costs the frames little, and every line is checked
-- the same way, only later
entryOf = function(guid)
    local entry = loadouts[guid]
    if type(entry) == "string" then
        entry = lineLoadout(entry)
        loadouts[guid] = entry
        lookOf(entry)       -- (a player joins: the next feed's frame only compares it)
    end
    return entry
end

-- the loadout on screen while a newer look waits for the next round: its look, the newer one's StatTrak counts (of
-- the same copies) and punishment prop
local function keepLook(shown, newer)
    local out = {}
    for k, v in pairs(shown) do
        out[k] = v
    end
    out.prop, out.propUntil = newer.prop, newer.propUntil
    if shown.st then
        out.st = {}
        for slot, n in pairs(shown.st) do
            local id = shown.ids and shown.ids[slot]
            out.st[slot] = id and newer.ids and newer.ids[slot] == id and newer.st and newer.st[slot] or n
        end
    end
    return out
end

-- the cl_guids of the players on the server
local function shownGuids()
    local out = {}
    for c = 0, maxClients - 1 do
        if connected(c) then
            local guid = guidOf(c)
            if guid ~= "" then
                out[guid] = true
            end
        end
    end
    return out
end

-- a whole feed read: in place of the old one. During play a player on the server whose look changed keeps the old
-- look until the next round (held); what a panel answer set after this feed was asked for stays
local function applyFeed(fresh, count, fetchedAt, roundStart)
    local hold = isPlaying() and not roundStart
    local shown = shownGuids()
    work = work - COST.swap
    for guid in pairs(shown) do
        work = work - COST.swap
        local now, newer = entryOf(guid), fresh[guid]
        if type(newer) == "string" then
            newer = lineLoadout(newer)          -- a player who joined while the feed was being read
            fresh[guid] = newer
        end
        if (takenAt[guid] or -1) >= fetchedAt then
            fresh[guid] = now
        elseif hold and not justLinked[guid] and lookOf(now) ~= lookOf(newer) then
            held[guid] = newer or false
            fresh[guid] = keepLook(now or {}, newer or {})
        else
            held[guid] = nil
        end
        if newer then
            justLinked[guid] = nil
        end
    end
    for guid in pairs(held) do
        if not shown[guid] then
            held[guid] = nil         -- nobody shows it: the feed's newest is in effect already
        end
    end
    loadouts = fresh
    et.G_LogPrint(string.format("%s: %d loadouts\n", MODNAME, count))
    publishLoadouts()
end

-- an old bot's JSON feed (or a hand-written file), all at once as 0.21 read it; a broken one keeps the last good table
local function readJsonFeed(text, fetchedAt, roundStart)
    if not text or text == lastLoadoutText then
        return
    end
    local data = json.decode(text)
    if type(data) ~= "table" then
        et.G_LogPrint(string.format("%s: ignored an unreadable loadout file\n", MODNAME))
        return
    end
    local fresh, count = {}, 0
    for guid, entry in pairs(data) do
        local parsed = type(guid) == "string" and parseEntry(entry)
        if parsed then
            fresh[guid:upper()] = parsed
            count = count + 1
        end
    end
    lastLoadoutText, lastStamp = text, nil
    applyFeed(fresh, count, fetchedAt, roundStart)
end

local function stopFeed()
    if feedJob then
        feedJob.close()
        feedJob = nil
    end
end

-- the feed being read, within what is left of the frame's work; a feed read to its end goes in place at the start of
-- the next frame (swapFeed)
local function feedStep()
    local job = feedJob
    while work > 0 do
        local line = job.next()
        if not line then
            stopFeed()
            failedStamp = job.stamp
            et.G_LogPrint(string.format("%s: ignored a loadout feed that ended early\n", MODNAME))
            return
        end
        work = work - COST.line
        local lines = line:match("^end (%d+)$")
        if lines then
            stopFeed()
            if tonumber(lines) ~= job.lines then
                failedStamp = job.stamp
                et.G_LogPrint(string.format("%s: ignored a loadout feed of %d lines that says %s\n", MODNAME, job.lines, lines))
            else
                readyFeed = job
            end
            return
        end
        job.lines = job.lines + 1
        local guid = line:match("^(%w+) ")
        if guid and #guid <= 64 then
            guid = guid:upper()
            if job.shown[guid] then
                -- a player on the server: read now, with its look (the feed's end compares it with what is shown)
                local loadout = lineLoadout(line)
                job.fresh[guid] = loadout
                lookOf(loadout)
                work = work - COST.parse
            else
                job.fresh[guid] = line
            end
            job.count = job.count + 1
        end
    end
end

local function swapFeed()
    local job = readyFeed
    readyFeed = nil
    lastStamp, lastLoadoutText = job.stamp, nil
    applyFeed(job.fresh, job.count, job.fetched, job.roundStart)
end

-- the loadout file, when it changed. In lines, its first line carries the feed's stamp (a hash of the rest): an
-- unchanged feed costs one short read; a new one is read a few lines a frame from the same open file (a feed still
-- being read is dropped: this one is newer). JSON (a bot before 19.10, a hand-written file) is read whole and
-- compared with the last one, as 0.21 did. now: the whole feed in this call (the map is loading)
local function readLoadouts(now)
    local f = io.open(loadoutPath, "r")
    if not f then
        return
    end
    local first = f:read("l") or ""
    local stamp = first:match(LINES.feed)
    -- a download is as new as the moment it was asked for; a hand-written file as the moment it is read
    local fetchedAt = now and -1 or (loadoutUrl and loadoutUrl ~= "" and lastFetchAt or frameTime)
    local roundStart = now or frameTime < roundStartUntil
    if stamp then
        if stamp == lastStamp or stamp == failedStamp or (feedJob and feedJob.stamp == stamp) then
            f:close()
            return
        end
        stopFeed()
        readyFeed = nil
        feedJob = { next = function() return f:read("l") end, close = function() f:close() end, stamp = stamp, fresh = {},
                    count = 0, lines = 0, fetched = fetchedAt, roundStart = roundStart, shown = shownGuids() }
        if now then
            work = math.huge
            feedStep()
            if readyFeed then
                swapFeed()
            end
            work = 0
        end
        return
    end
    local rest = f:read("a")
    f:close()
    readJsonFeed(first .. "\n" .. (rest or ""), fetchedAt, roundStart)
end

-- background download (in lines, see the top); the file is swapped in only when curl succeeds. extra: another
-- background command (the StatTrak report) that goes out in the same shell, so the server forks once a minute
local function fetchLoadouts(extra)
    if not loadoutUrl or loadoutUrl == "" then
        if extra then
            os.execute(extra)
        end
        return
    end
    lastFetchAt = frameTime
    local tmp = loadoutPath .. ".tmp"
    local auth = ""
    if apiToken and apiToken ~= "" then
        auth = " -H " .. shellQuote("Authorization: Bearer " .. apiToken)
    end
    local url = loadoutUrl .. (loadoutUrl:find("?", 1, true) and "&" or "?") .. LINES.query
    os.execute(string.format("(curl -fsS --max-time %d%s -o %s %s && mv -f %s %s) >/dev/null 2>&1 &%s",
        CURL_MAX_S, auth, shellQuote(tmp), shellQuote(url), shellQuote(tmp), shellQuote(loadoutPath), extra and (" " .. extra) or ""))
end

-- a download for the loadout file a new Lua VM reads (a map_restart, the next map: 0.22). What it brings does not
-- count as newer than a panel change for takenAt (lastFetchAt stays): a download asked for before that change may
-- still land after this one
local function refreshFile()
    local asked = lastFetchAt
    fetchLoadouts()
    lastFetchAt = asked
end

local function refuse(clientNum, levelTime, text)
    if lastMessage[clientNum] and levelTime - lastMessage[clientNum] < MESSAGE_GAP_MS then
        return
    end
    lastMessage[clientNum] = levelTime
    send(clientNum, string.format('cpm "^3FatBoss:^7 %s"', text))
end

local function vma(a, s, b)
    return { a[1] + s * b[1], a[2] + s * b[2], a[3] + s * b[3] }
end

local function dot(a, b)
    return a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
end

local function cross(a, b)
    return { a[2] * b[3] - a[3] * b[2], a[3] * b[1] - a[1] * b[3], a[1] * b[2] - a[2] * b[1] }
end

local function normalize(a)
    local l = math.sqrt(dot(a, a))
    if l < 0.0001 then return nil end
    return { a[1] / l, a[2] / l, a[3] / l }
end

-- the whole square must lie on the same wall: probe a 3x3 grid across it
local function squareFits(center, n, up, right, half, clientNum)
    for _, a in ipairs({ -0.95, 0, 0.95 }) do
        for _, b in ipairs({ -0.95, 0, 0.95 }) do
            local p = vma(vma(center, a * half, right), b * half, up)
            local tr = et.trap_Trace(vma(p, 8, n), nil, nil, vma(p, -8, n), clientNum, et.MASK_SOLID)
            if not tr or tr.fraction >= 1 or tr.startsolid or tr.entityNum ~= ENTITYNUM_WORLD
                or (tr.surfaceFlags & (SURF_SKY | SURF_NOMARKS | SURF_NODRAW)) ~= 0 or dot(tr.plane.normal, n) < 0.7 then
                return false
            end
        end
    end
    return true
end

-- the largest nearby placement where the whole graffiti is on the wall
local function fitGraffiti(hit, n, up, clientNum)
    local u = normalize(vma(up, -dot(up, n), n)) or { 0, 0, 1 }
    local r = normalize(cross(u, n))
    if not r then return nil end
    for _, scale in ipairs(SPRAY_SCALES) do
        local half = SPRAY_RADIUS * scale
        for _, shift in ipairs(SPRAY_SHIFTS) do
            local c = vma(vma(hit, shift[1] * half, r), shift[2] * half, u)
            if squareFits(c, n, u, r, half, clientNum) then
                return c, half
            end
        end
    end
    return nil
end

local function spray(clientNum)
    local levelTime = et.trap_Milliseconds()
    local team = et.gentity_get(clientNum, "sess.sessionTeam")
    if team ~= TEAM_AXIS and team ~= TEAM_ALLIES then
        return refuse(clientNum, levelTime, "join a team to spray.")
    end
    if (et.gentity_get(clientNum, "health") or 0) <= 0 then
        return refuse(clientNum, levelTime, "you can spray only while alive.")
    end
    if (sprayCount[clientNum] or 0) >= spraysPerLife then
        return refuse(clientNum, levelTime, spraysPerLife == 1 and "one graffiti per life."
            or string.format("%d graffiti per life - the next ones after you respawn.", spraysPerLife))
    end
    if lastSpray[clientNum] and levelTime - lastSpray[clientNum] < SPRAY_GAP_MS then
        return refuse(clientNum, levelTime, "shake the can a moment.")
    end
    if lastTry[clientNum] and levelTime - lastTry[clientNum] < SPRAY_TRY_MS then
        return refuse(clientNum, levelTime, "shake the can a moment.")
    end
    lastTry[clientNum] = levelTime
    local design = loadoutOf(clientNum).graffiti or defaultGraffiti
    if not design then
        return refuse(clientNum, levelTime, "no graffiti equipped - get one from FatBoss crates.")
    end

    -- trace from the eyes along the view
    local origin = et.gentity_get(clientNum, "ps.origin")
    local angles = et.gentity_get(clientNum, "ps.viewangles")
    local eye = { origin[1], origin[2], origin[3] + (et.gentity_get(clientNum, "ps.viewheight") or 0) }
    local pitch, yaw = math.rad(angles[1]), math.rad(angles[2])
    local forward = { math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), -math.sin(pitch) }
    local finish = {
        eye[1] + forward[1] * SPRAY_RANGE,
        eye[2] + forward[2] * SPRAY_RANGE,
        eye[3] + forward[3] * SPRAY_RANGE,
    }
    local tr = et.trap_Trace(eye, nil, nil, finish, clientNum, et.MASK_SOLID)
    if not tr or tr.fraction >= 1 or tr.startsolid then
        return refuse(clientNum, levelTime, "get closer to a wall or the floor.")
    end
    if tr.entityNum ~= ENTITYNUM_WORLD or (tr.surfaceFlags & (SURF_SKY | SURF_NOMARKS | SURF_NODRAW)) ~= 0 then
        return refuse(clientNum, levelTime, "you can't spray here.")
    end

    -- image up: world up on walls; away from the player on floors and ceilings
    local n = tr.plane.normal
    local up
    if math.abs(n[3]) < 0.7 then
        up = { 0, 0, 1 }
    else
        up = { forward[1], forward[2], 0 }
    end

    local center, half = fitGraffiti(tr.endpos, n, up, clientNum)
    if not center then
        return refuse(clientNum, levelTime, "not enough room here - find a bigger, flatter wall.")
    end

    local cmd = string.format("fbspray %d %s %.1f %.1f %.1f %.4f %.4f %.4f %.4f %.4f %.4f %.1f",
        clientNum, design, center[1], center[2], center[3], n[1], n[2], n[3], up[1], up[2], up[3], half)
    -- to everybody: during play when every line has room for it (0.22), usually at once
    cast(cmd .. " 1")
    -- the cgame keeps one graffiti per player: this one takes the place of the last
    sprays[clientNum] = cmd .. " 0"
    sprayCount[clientNum] = (sprayCount[clientNum] or 0) + 1
    lastSpray[clientNum] = levelTime
    et.G_LogPrint(string.format("%s: spray %d %s %s\n", MODNAME, clientNum, guidOf(clientNum), design))
end

local function tell(clientNum, text)
    send(clientNum, string.format('print "^3FatBoss:^7 %s\n"', text))
    send(clientNum, string.format('cpm "^3FatBoss:^7 %s"', text))
end

-- /fblink CODE: the code from the FatBoss profile ties this computer (cl_guid) to the account
local function link(clientNum)
    local now = et.trap_Milliseconds()
    local code = (et.trap_Argv(1) or ""):upper():gsub("[^A-Z0-9]", "")
    if not linkUrl or linkUrl == "" then
        return tell(clientNum, "this server is not connected to FatBoss.")
    end
    if code == "" then
        return tell(clientNum, "copy the /fblink command from your FatBoss profile and paste it here.")
    end
    if links[clientNum] or (lastLink[clientNum] and now - lastLink[clientNum] < LINK_GAP_MS) then
        return tell(clientNum, "one moment, the last link is still on its way.")
    end
    local guid = guidOf(clientNum)
    if not guid:match("^[0-9A-F]+$") or #guid ~= 32 then
        return tell(clientNum, "your game has no valid cl_guid. Restart the game and try again.")
    end
    lastLink[clientNum] = now
    local userinfo = et.trap_GetUserinfo(clientNum)
    local name = (et.Info_ValueForKey(userinfo, "name") or ""):gsub("%^.", "")
    local server = (et.trap_Cvar_Get("sv_hostname") or ""):gsub("%^.", "")
    local base = string.format("%s/fatboss_link_%d_%d_%d", homeDir, clientNum, RUN, now)
    local body = io.open(base .. ".req", "w")
    if not body then
        return tell(clientNum, "the server could not write the request. Tell an admin.")
    end
    body:write(json.encode({ code = code, guid = guid, name = name:sub(1, 64), server = server:sub(1, 64) }))
    body:close()
    local auth = ""
    if apiToken and apiToken ~= "" then
        auth = " -H " .. shellQuote("Authorization: Bearer " .. apiToken)
    end
    -- the answer lands in .res (FatBoss answers 400 with a reason, so no -f); RunFrame picks it up
    os.execute(string.format("(curl -sS --max-time %d%s -H 'Content-Type: application/json' --data @%s -o %s.tmp %s; mv -f %s.tmp %s.res; rm -f %s) >/dev/null 2>&1 &",
        CURL_MAX_S, auth, shellQuote(base .. ".req"), shellQuote(base), shellQuote(linkUrl), shellQuote(base), shellQuote(base), shellQuote(base .. ".req")))
    links[clientNum] = { file = base .. ".res", base = base, started = now, guid = guid, deadline = now + LINK_WAIT_MS }
    tell(clientNum, "linking this computer to your FatBoss account...")
end

local function checkLinks(now)
    for clientNum, pending in pairs(links) do
        local f = io.open(pending.file, "r")
        if f then
            local text = f:read("*a")
            f:close()
            os.remove(pending.file)
            links[clientNum] = nil
            local answer = json.decode(text or "")
            if type(answer) == "table" and answer.ok then
                -- two lines: the cgame cuts a cpm popup at 127 chars (MAX_LOC_LEN)
                tell(clientNum, string.format("^2linked^7 to %s. Your graffiti works now.", tostring(answer.name or "your account")))
                tell(clientNum, "Your skins show after /reconnect or on the next map (fb_loadskins loads them now).")
                et.G_LogPrint(string.format("%s: linked %d %s\n", MODNAME, clientNum, pending.guid))
                nextFetch = 0          -- fetch the loadouts right away
                justLinked[pending.guid] = true    -- and show this computer's at once, also during play (0.22)
            elseif type(answer) == "table" and answer.error then
                tell(clientNum, "^1not linked:^7 " .. tostring(answer.error))
            else
                tell(clientNum, "^1not linked:^7 FatBoss did not answer properly. Try again in a minute.")
            end
        elseif now > pending.deadline then
            links[clientNum] = nil
            abandon(pending)
            tell(clientNum, "^1not linked:^7 no answer from FatBoss. Try again in a minute.")
        end
    end
end

-- /fbequip <knife|colt|luger|thompson|mp40|graffiti> <name|-> [wear 0..1 or fn|mw|ft|ww|bs]  (test servers only)
-- /fbequip prop <dong|-> [minutes]: the punishment prop on your own helmet
local function equip(clientNum)
    local guid = guidOf(clientNum)
    local slot = string.lower(et.trap_Argv(1) or "")
    local name = string.lower(et.trap_Argv(2) or "")
    local wearArg = string.lower(et.trap_Argv(3) or "")
    local wear = CONDITION_WEAR[wearArg] or tonumber(wearArg)
    -- the extras after the wear: st or st=N (StatTrak), k=abcde (a sticker per spot), n=Name_with_underscores
    local st, stk, tag, extrasOk = nil, nil, nil, true
    for i = 4, 6 do
        local a = et.trap_Argv(i) or ""
        if a ~= "" then
            local low = string.lower(a)
            if low == "st" then
                st = 0
            elseif low:match("^st=%d+$") then
                st = math.min(999999, tonumber(low:sub(4)))
            elseif low:match("^k=") and validStickers(low:sub(3)) then
                stk = low:sub(3)
            elseif low:match("^n=") and validTag((a:sub(3):gsub("_", " "))) then
                tag = a:sub(3):gsub("_", " ")
            else
                extrasOk = false
            end
        end
    end
    local say = function(text)
        send(clientNum, string.format('print "^3FatBoss:^7 %s\n"', text))
    end
    if guid == "" then
        return say("no cl_guid, nothing to equip.")
    end
    local isProp = slot == "prop"
    local valid = slot == "graffiti" or isProp
    for _, s in ipairs(SLOTS) do
        valid = valid or s == slot
    end
    local minutes = isProp and tonumber(wearArg ~= "" and wearArg or "60") or nil
    if not valid or (name ~= "-" and not validName(name)) or (isProp and name ~= "-" and not PROPS[name])
        or (isProp and (not minutes or minutes < 1 or minutes > 10080))
        or (not isProp and wearArg ~= "" and (not wear or wear < 0 or wear > 1)) or not extrasOk then
        say("usage: /fbequip <knife|colt|luger|thompson|mp40> <theme|-> [wear] [st[=N]] [k=abcde] [n=Name]   or   /fbequip graffiti <design>")
        say("or /fbequip prop <dong|-> [minutes, 60 by default]: the punishment prop on your helmet (cgame b17)")
        say("wear: 0 (Factory New) .. 1 (Battle-Scarred), or fn mw ft ww bs; st: a StatTrak copy (N kills);")
        say("k=abcde: a sticker on each spot (a design code each, . for none; pistols have four spots), or two chars")
        say("per spot once a design is 36 or more (k=0a1b...., .. for none; cgame b21); n=Name: a name tag (_ for spaces)")
        -- the lists in lines of 400 characters at most: the server drops a command over 1022
        local function sayList(label, list)
            local line = label
            for word in list:gmatch("%S+") do
                if #line + #word + 1 > 400 then
                    say(line)
                    line = " "
                end
                line = line .. " " .. word
            end
            return say(line)
        end
        sayList("themes:", THEMES_HELP)
        return sayList("graffiti:", GRAFFITI_HELP)
    end
    local entry = testLoadouts[guid]
    if not entry then
        -- start from the real loadout, so one slot changes at a time
        local base = entryOf(guid) or {}
        entry = { graffiti = base.graffiti, prop = base.prop, propUntil = base.propUntil, skins = {}, wear = {}, st = {}, stk = {}, tags = {} }
        for _, key in ipairs({ "skins", "wear", "st", "stk", "tags" }) do
            for k, v in pairs(base[key] or {}) do
                entry[key][k] = v
            end
        end
        testLoadouts[guid] = entry
    end
    if isProp then
        entry.prop = name ~= "-" and name or nil
        entry.propUntil = name ~= "-" and os.time() + math.floor(minutes * 60) or nil
        say(string.format("prop = %s%s (shows at once with cgame b17)", name, name ~= "-" and string.format(" for %d min", math.floor(minutes)) or ""))
        setLoadout(clientNum, loadoutString(clientNum))
        return
    end
    if slot == "graffiti" then
        entry.graffiti = name ~= "-" and name or nil
    else
        entry.skins[slot] = name ~= "-" and name or nil
        entry.wear[slot] = name ~= "-" and (wear or entry.wear[slot]) or nil
        -- a test copy has no id: its kills count here and are never reported
        entry.st[slot] = name ~= "-" and st or nil
        entry.stk[slot] = name ~= "-" and stk or nil
        entry.tags[slot] = name ~= "-" and tag or nil
    end
    local worn = slot ~= "graffiti" and entry.wear[slot] and string.format(" (wear %.3f)", entry.wear[slot]) or ""
    say(string.format("%s = %s%s (shows after /reconnect, on the next map or at the intermission; fb_loadskins loads it now)", slot, name, worn))
    setLoadout(clientNum, loadoutString(clientNum))
    sendTags(clientNum)
end

-- ------------------------------------------------------------------ in-game Arsenal panel

-- text inside a quoted server command: no quotes, backslashes or line breaks
local function plain(text)
    return (tostring(text or ""):gsub('[%c"\\]', " "):sub(1, 200))
end

local function panelError(clientNum, text)
    send(clientNum, string.format('fbpanel_err "%s"', plain(text)))
end

local function isSlot(slot)
    if slot == "graffiti" then
        return true
    end
    for _, s in ipairs(SLOTS) do
        if s == slot then
            return true
        end
    end
    return false
end

-- POSTs body to url in the background; the answer lands in <base>.res (FatBoss answers 400 with a reason, so no -f).
-- With deferred it returns the shell command instead of running it (to go out with another one).
local function postAsync(url, body, base, deferred)
    local f = io.open(base .. ".req", "w")
    if not f then
        return false
    end
    f:write(json.encode(body))
    f:close()
    local auth = ""
    if apiToken and apiToken ~= "" then
        auth = " -H " .. shellQuote("Authorization: Bearer " .. apiToken)
    end
    local cmd = string.format("(curl -sS --max-time %d%s -H 'Content-Type: application/json' --data @%s -o %s.tmp %s; mv -f %s.tmp %s.res; rm -f %s) >/dev/null 2>&1 &",
        CURL_MAX_S, auth, shellQuote(base .. ".req"), shellQuote(base), shellQuote(url), shellQuote(base), shellQuote(base), shellQuote(base .. ".req"))
    if deferred then
        return cmd
    end
    os.execute(cmd)
    return true
end

-- common checks of fbinv and fbwear; returns the player's cl_guid when the request may go out
local function panelStart(clientNum, url, kind)
    local now = et.trap_Milliseconds()
    if not url then
        panelError(clientNum, "This server is not connected to FatBoss.")
        return nil
    end
    -- the panel opened again while its list is on its way (asked, being read or being sent): that list ends with
    -- fbinv_end, which ends this open's wait too, and cgame b22 keeps taking its items; a refusal (fbpanel_err) would
    -- make it drop the rest (0.22)
    if kind == "inv" and (invJobs[clientNum] or outbox[clientNum] or (requests[clientNum] and requests[clientNum].kind == "inv")) then
        return nil
    end
    if requests[clientNum] or outbox[clientNum] or invJobs[clientNum] or (lastPanel[clientNum] and now - lastPanel[clientNum] < PANEL_GAP_MS) then
        panelError(clientNum, "One moment, the last request is still on its way.")
        return nil
    end
    local guid = guidOf(clientNum)
    if not guid:match("^[0-9A-F]+$") or #guid ~= 32 then
        panelError(clientNum, "Your game has no valid cl_guid. Restart the game and try again.")
        return nil
    end
    lastPanel[clientNum] = now
    return guid, now
end

local function panelSend(clientNum, url, body, kind)
    local guid, now = panelStart(clientNum, url, kind)
    if not guid then
        return
    end
    body.guid = guid
    local base = string.format("%s/fatboss_panel_%d_%d_%d", homeDir, clientNum, RUN, now)
    if not postAsync(url, body, base) then
        return panelError(clientNum, "The server could not write the request. Tell an admin.")
    end
    requests[clientNum] = { file = base .. ".res", base = base, started = now, guid = guid, kind = kind, deadline = now + PANEL_WAIT_MS }
end

-- fbinv: the panel opened, it wants the player's items
local function panelInventory(clientNum)
    panelSend(clientNum, inventoryUrl and inventoryUrl .. "?" .. LINES.query, {}, "inv")
end

-- fbwear <id> | fbwear off <slot>
local function panelWear(clientNum)
    local a1, a2 = string.lower(et.trap_Argv(1) or ""), string.lower(et.trap_Argv(2) or "")
    if a1 == "off" then
        if not isSlot(a2) then
            return panelError(clientNum, "Unknown slot.")
        end
        return panelSend(clientNum, equipUrl, { slot = a2 }, "wear")
    end
    local id = tonumber(a1)
    if not id or id < 1 or id ~= math.floor(id) then
        return panelError(clientNum, "Unknown item.")
    end
    panelSend(clientNum, equipUrl, { id = math.floor(id) }, "wear")
end

-- a loadout FatBoss just sent for this player (a panel answer): in effect now instead of at the next feed, or, when
-- it changes the look during play, from the next round (returns true then). During play no feed download follows
-- (0.22): the player's own loadout is all that changed, and an older feed landing later does not undo it (takenAt).
-- Outside play a new look the player wore (worn: an fbwear answer) also brings a download (as in 0.21): a map_restart
-- may come any moment, and the new Lua VM reads the loadout file, which must have it then (during play the countdown
-- and the intermission fetch it; a panel opened brings no download, its loadout is what FatBoss already had)
local function takeEntry(clientNum, guid, entry, worn)
    if type(entry) ~= "table" then
        return false
    end
    local newer = parseEntry(entry) or {}
    local before = entryOf(guid)
    local later = false
    takenAt[guid] = frameTime
    if testLoadouts[guid] then
        testLoadouts[guid] = nil      -- a real choice replaces an /fbequip test loadout (test servers: at once)
        loadouts[guid], held[guid] = newer, nil
    elseif isPlaying() and not justLinked[guid] and lookOf(before) ~= lookOf(newer) then
        held[guid] = newer
        loadouts[guid] = keepLook(before or {}, newer)
        later = true
    else
        loadouts[guid], held[guid] = newer, nil
    end
    if worn and not isPlaying() and lookOf(before) ~= lookOf(newer) then
        refreshFile()
    end
    justLinked[guid] = nil
    publishOne(clientNum)
    sendTags(clientNum)
    return later
end

-- the looks that waited for the round to end: in effect now (the round ended, a warmup or the intermission began)
local function applyHeld()
    for guid, entry in pairs(held) do
        loadouts[guid] = entry or nil
    end
    held, toldHeld = {}, {}
    publishLoadouts()
end

-- a name inside an item token: nothing but [A-Za-z0-9_.!?'-] as it is, the rest as %XX
local function encodeTag(tag)
    if not validTag(tag) then
        return "-"
    end
    return (tag:gsub("[^%w_%.!%?'%-]", function(c)
        return string.format("%%%02X", c:byte())
    end))
end

-- one item as the panel gets it, nil for one it cannot show:
-- "id,slot,value,wear,serial,flags,stattrak,stickers,name" - wear is the float x 1000 or -1 (graffiti);
-- flags: 1 worn, 2 on the market, 4 bound; stattrak the count or -1; stickers a code per spot or "-";
-- name %-encoded or "-". Cgame b12 reads the first six and skips the rest.
local function itemToken(clientNum, it)
    local id, serial, wear
    if type(it) == "table" then
        id, serial, wear = tonumber(it.id), tonumber(it.serial) or 0, tonumber(it.wear)
        id, serial = id and math.tointeger(math.floor(id)), math.tointeger(math.floor(serial)) or 0
    end
    if not id or not isSlot(it.slot) or not validName(it.value) then
        return nil
    end
    local flags = (it.worn and 1 or 0) + (it.sale and 2 or 0) + (it.bound and 4 or 0)
    wear = wear and math.max(0, math.min(1000, math.floor(wear))) or -1
    local st = tonumber(it.stattrak)
    st = st and st >= 0 and math.min(999999, math.floor(st)) or -1
    -- two-char codes only to a cgame that reads them (b21): b20 would show wrong stickers
    local stk = validStickers(it.stickers) and (#it.stickers < 8 or (cgameBuild[clientNum] or 0) >= CGAME_WIDE_STK)
        and it.stickers or "-"
    return string.format("%d,%s,%s,%d,%d,%d,%d,%s,%s", id, it.slot, it.value, wear, serial, flags, st, stk, encodeTag(it.name_tag))
end

-- the list into the player's outbox: fbinv_begin, the tokens in fbinv_items commands that each fit one snapshot of
-- the player's line (PANEL_MIN_CHUNK..PANEL_CHUNK chars; the first one leaves room for fbinv_begin, which goes in
-- the same frame), fbinv_end
local function queueInventory(clientNum, tokens, total, name)
    total = math.tointeger(math.floor(tonumber(total) or #tokens)) or #tokens
    local queue = { string.format('fbinv_begin %d %d "%s"', #tokens, total, plain(name)) }
    local room = budgetOf(clientNum)
    local chunk = math.floor((room - NET.cmd) / NET.huff) - #"fbinv_items "
    local limit = math.max(PANEL_MIN_CHUNK, math.min(PANEL_CHUNK, chunk - wireBytes(queue[1])))
    chunk = math.max(PANEL_MIN_CHUNK, math.min(PANEL_CHUNK, chunk))
    local line, len = {}, 0
    for _, tok in ipairs(tokens) do
        if len + #tok + 1 > limit and #line > 0 then
            queue[#queue + 1] = "fbinv_items " .. table.concat(line, " ")
            line, len, limit = {}, 0, chunk
        end
        line[#line + 1] = tok
        len = len + #tok + 1
    end
    if #line > 0 then
        queue[#queue + 1] = "fbinv_items " .. table.concat(line, " ")
    end
    queue[#queue + 1] = "fbinv_end"
    outbox[clientNum] = queue
end

-- an old bot's JSON answer: everything at once, as 0.21 did
local function sendInventory(clientNum, guid, answer)
    takeEntry(clientNum, guid, answer.entry)
    local tokens = {}
    for _, it in ipairs(type(answer.items) == "table" and answer.items or {}) do
        tokens[#tokens + 1] = itemToken(clientNum, it)
    end
    queueInventory(clientNum, tokens, answer.total, answer.name)
end

-- a panel answer in lines, within what is left of the frame's work
local function inventoryStep(clientNum, job)
    while work > 0 do
        local line = job.next()
        if not line then
            invJobs[clientNum] = nil
            panelError(clientNum, "FatBoss did not answer properly. Try again in a minute.")
            return
        end
        work = work - COST.item
        local lines = line:match("^end (%d+)$")
        if lines then
            invJobs[clientNum] = nil
            if tonumber(lines) ~= job.lines then
                panelError(clientNum, "FatBoss did not answer properly. Try again in a minute.")
            elseif connected(clientNum) and guidOf(clientNum) == job.guid then
                takeEntry(clientNum, job.guid, job.entry)
                queueInventory(clientNum, job.tokens, job.total, job.name)
            end
            return
        end
        job.lines = job.lines + 1
        local id, slot, value, wear, serial, flags, st, stk, name = line:match(LINES.item)
        if id then
            flags = math.tointeger(tonumber(flags)) or 0
            job.tokens[#job.tokens + 1] = itemToken(clientNum, { id = tonumber(id), slot = slot, value = value,
                wear = wear ~= "-1" and tonumber(wear) or nil, serial = tonumber(serial), worn = flags & 1 ~= 0,
                sale = flags & 2 ~= 0, bound = flags & 4 ~= 0, stattrak = tonumber(st), stickers = stk ~= "-" and stk or nil,
                name_tag = name ~= "-" and decodeTag(name) or nil })
        elseif line:sub(1, 8) == "account " then
            local total, account = line:match("^account (%d+) (%S+)$")
            job.total, job.name = tonumber(total), account and account ~= "-" and decodeTag(account) or ""
        elseif line:sub(1, 6) == "entry " then
            job.entry = lineEntry(line:match(LINES.entry))
        end
    end
end

-- a feed read last frame goes in place; then the lines of every answer being read, the panels' first (a player waits
-- for them), within the frame's work
local function readJobs()
    if readyFeed then
        swapFeed()
    end
    for clientNum, job in pairs(invJobs) do
        if work <= 0 then
            return
        end
        inventoryStep(clientNum, job)
    end
    if feedJob and work > 0 then
        feedStep()
    end
end

-- the waiting item lists, as fast as each player's line carries them: a command goes when it and what was sent in
-- the last ping + snapshot fit one snapshot's room (budgetOf), or when nothing is on its way. fbinv_begin and
-- fbinv_end (a few bytes) go in the frame of the first and the last items, not a round trip apart. A line that
-- something for everybody waits for (casts.full: a configstring, a graffiti) starts nothing new until it went
local function drainOutbox()
    for clientNum, queue in pairs(outbox) do
        if not connected(clientNum) then
            outbox[clientNum] = nil
        elseif not casts.full[clientNum] then
            local room, window = budgetOf(clientNum)
            local busy = inFlight(clientNum, window)
            local sent = 0
            while queue[1] do
                local bytes = wireBytes(queue[1])
                if busy > 0 and busy + bytes > room and not (sent > 0 and queue[1] == "fbinv_end") then
                    break
                end
                send(clientNum, table.remove(queue, 1))
                busy, sent = busy + bytes, sent + 1
            end
            if not queue[1] then
                outbox[clientNum] = nil
            end
        end
    end
end

local function checkRequests(now)
    for clientNum, pending in pairs(requests) do
        local f = io.open(pending.file, "r")
        if f then
            local text = f:read("a") or ""
            f:close()
            os.remove(pending.file)
            requests[clientNum] = nil
            if not connected(clientNum) or guidOf(clientNum) ~= pending.guid then
                -- the player left, or somebody else has the slot now: nothing to tell
            elseif pending.kind == "inv" and text:sub(1, #LINES.inv + 1) == LINES.inv .. "\n" then
                local lines = text:gmatch("([^\n]*)\n")
                lines()
                invJobs[clientNum] = { guid = pending.guid, next = lines, tokens = {}, lines = 0 }
            else
                local answer = json.decode(text)
                if type(answer) ~= "table" then
                    panelError(clientNum, "FatBoss did not answer properly. Try again in a minute.")
                elseif not answer.ok then
                    panelError(clientNum, tostring(answer.error or "FatBoss said no."))
                elseif pending.kind == "inv" then
                    sendInventory(clientNum, pending.guid, answer)
                else
                    local later = takeEntry(clientNum, pending.guid, answer.entry, true)
                    send(clientNum, "fbwear_ok " .. (isSlot(answer.slot) and answer.slot or "-"))
                    if later and not toldHeld[clientNum] then
                        toldHeld[clientNum] = true
                        tell(clientNum, "saved - it shows from the next round.")
                    end
                    et.G_LogPrint(string.format("%s: wear %d %s %s%s\n", MODNAME, clientNum, pending.guid,
                        tostring(answer.label or answer.slot), later and " (from the next round)" or ""))
                end
            end
        elseif now > pending.deadline then
            requests[clientNum] = nil
            abandon(pending)
            panelError(clientNum, "No answer from FatBoss. Try again in a minute.")
        end
    end
end

-- ------------------------------------------------------------------ StatTrak

-- whether the knife of a knife kill shows the worn knife theme (0.21). team: the killer's, for a backstab whose
-- s.weapon is no knife (Weapon_Knife is the only source of MOD_BACKSTAB, so never seen): Allies carry the KA-BAR
local function knifeShowsTheme(theme, killer, meansOfDeath, team)
    local cover = KNIFE_COVER[theme]
    if not cover then
        return true
    end
    local knife = MOD_KNIFE_USED[meansOfDeath] or WP_KNIFE_USED[et.gentity_get(killer, "s.weapon")]
        or (team == TEAM_ALLIES and "kabar" or "knife")
    return cover[knife] == true
end

-- an enemy killed with the weapon of a StatTrak copy the killer wears, in a real game
local function countKill(victim, killer, meansOfDeath)
    local slot = MOD_SLOT[meansOfDeath]
    if not slot or killer == victim or killer < 0 or killer >= maxClients or victim < 0 or victim >= maxClients then
        return
    end
    if et.trap_Cvar_Get("gamestate") ~= GS_PLAYING then
        return
    end
    local kt, vt = et.gentity_get(killer, "sess.sessionTeam"), et.gentity_get(victim, "sess.sessionTeam")
    if kt == vt or (kt ~= TEAM_AXIS and kt ~= TEAM_ALLIES) or (vt ~= TEAM_AXIS and vt ~= TEAM_ALLIES) then
        return
    end
    local guid = guidOf(killer)
    if guid == "" then
        return
    end
    local loadout = testLoadouts[guid] or entryOf(guid)
    if not loadout or not loadout.st or not loadout.st[slot] then
        return
    end
    -- a WuT knife counts KA-BAR kills only: on the Axis knife its skin never shows
    if slot == "knife" and not knifeShowsTheme(loadout.skins and loadout.skins.knife, killer, meansOfDeath, kt) then
        return
    end
    local id = loadout.ids and loadout.ids[slot]
    if id and not testLoadouts[guid] then
        local p = stPending[id]
        if not p or p.guid ~= guid then
            p = { guid = guid, n = 0 }
            stPending[id] = p
        end
        p.n = p.n + 1
    else
        loadout.st[slot] = loadout.st[slot] + 1      -- a test copy: counted here only
    end
    -- the count goes to everybody when every line has room for it (0.22): a panel list being sent waits for it
    publishOne(killer)
end

-- the kills since the last report to FatBoss, in the background; final: the map ends, nobody waits for the
-- answer (a later map's sweep removes it). Not final, it returns the shell command for fetchLoadouts to run
-- with the download. Every report has files of its own, so a late answer is never taken for the next one's.
local function reportKills(now, final)
    if not next(stPending) or testMode or not stattrakUrl or (stInflight and not final) then
        return nil
    end
    local kills, ids = {}, {}
    for id, p in pairs(stPending) do
        kills[#kills + 1] = { guid = p.guid, id = id, n = p.n }
        ids[id] = p.n
    end
    local base = string.format("%s/fatboss_stattrak%s_%d_%d", homeDir, final and "_end" or "", RUN, now)
    local cmd = postAsync(stattrakUrl, { kills = kills }, base, not final)
    if not cmd then
        return nil
    end
    stPending = {}
    if not final then
        stInflight = { file = base .. ".res", base = base, started = now, deadline = now + REPORT_WAIT_MS, ids = ids }
        return cmd
    end
    return nil
end

-- FatBoss's answer: the counts it has now; a report without an answer is lost (never counted twice)
local function checkReport(now)
    local f = io.open(stInflight.file, "r")
    if f then
        local text = f:read("*a")
        f:close()
        os.remove(stInflight.file)
        local answer = json.decode(text or "")
        if type(answer) == "table" and answer.ok and type(answer.counts) == "table" then
            for id, count in pairs(answer.counts) do
                id, count = tonumber(id), tonumber(count)
                if id and count then
                    stFloor[id] = math.max(stFloor[id] or 0, count)
                end
            end
        else
            et.G_LogPrint(string.format("%s: FatBoss refused a StatTrak report: %s\n", MODNAME,
                plain(type(answer) == "table" and answer.error or text)))
        end
        stInflight = nil
        publishLoadouts()
    elseif now > stInflight.deadline then
        et.G_LogPrint(string.format("%s: no answer to a StatTrak report\n", MODNAME))
        abandon(stInflight)
        stInflight = nil
        publishLoadouts()
    end
end

-- the graffiti already on the map, to one client (without the sound)
local function syncClient(clientNum)
    for _, cmd in pairs(sprays) do
        send(clientNum, cmd)
    end
end

-- The FatBoss cgame asks for the graffiti again when it restarts (vid_restart
-- forgets what the server sent when the player joined).
local function resync(clientNum)
    -- a list being sent went to the cgame that is gone: the new one never got its fbinv_begin, so the rest would end
    -- as an empty list; its next fbinv gets the whole list again (0.22)
    outbox[clientNum] = nil
    local build = tonumber(et.trap_Argv(1) or "")
    if build and build >= 1 and build == math.floor(build) then
        cgameBuild[clientNum] = build
        sentTags[clientNum] = nil
        sendTags(clientNum)
    end
    local now = et.trap_Milliseconds()
    if not synced[clientNum] or (lastSync[clientNum] and now - lastSync[clientNum] < SYNC_GAP_MS) then
        return
    end
    lastSync[clientNum] = now
    syncClient(clientNum)
end

-- a map_restart: every cgame build this map heard, with its player's cl_guid, into the slot's cvar (see BUILD_CVAR);
-- an odd guid or build (a client can send anything) is not kept, that player sends fbsync with the next cgame start
local function keepBuilds()
    for clientNum, build in pairs(cgameBuild) do
        local guid = guidOf(clientNum)
        if build < 100000 and #guid <= 64 and guid:match("^%x+$") then
            et.trap_Cvar_Set(BUILD_CVAR .. clientNum, string.format("%d %s", build, guid))
        end
    end
end

function et_InitGame(levelTime, randomSeed, restart)
    et.RegisterModname(MODNAME .. " " .. VERSION)
    maxClients = tonumber(et.trap_Cvar_Get("sv_maxclients")) or 64
    homeDir = et.trap_Cvar_Get("fs_homepath") .. "/legacy"
    loadoutPath = homeDir .. "/fatboss_loadouts.json"
    loadoutUrl = os.getenv("FATBOSS_LOADOUT_URL")
    linkUrl = os.getenv("FATBOSS_LINK_URL")
    if (not linkUrl or linkUrl == "") and loadoutUrl and loadoutUrl:match("/loadouts$") then
        linkUrl = loadoutUrl:gsub("/loadouts$", "/link")
    end
    -- the panel's two calls sit next to the loadout URL (or the link URL)
    local apiBase = (loadoutUrl and loadoutUrl:match("^(.+)/loadouts$")) or (linkUrl and linkUrl:match("^(.+)/link$"))
    inventoryUrl = apiBase and apiBase .. "/inventory" or nil
    equipUrl = apiBase and apiBase .. "/equip" or nil
    stattrakUrl = apiBase and apiBase .. "/stattrak" or nil
    apiToken = os.getenv("FATBOSS_API_TOKEN")
    testMode = os.getenv("FATBOSS_TEST") == "1"
    defaultGraffiti = os.getenv("FATBOSS_DEFAULT_GRAFFITI")
    if not validName(defaultGraffiti) then
        defaultGraffiti = testMode and "fatboss" or nil
    end
    spraysPerLife = math.floor(tonumber(os.getenv("FATBOSS_SPRAYS_PER_LIFE") or "") or 3)
    spraysPerLife = math.max(1, math.min(10, spraysPerLife))
    -- ET: Legacy starts every map in a fresh Lua VM, so nothing waits here yet; should a VM ever see a second
    -- map, what it still waited for is dropped like any abandoned request
    for _, pending in pairs(links) do
        abandon(pending)
    end
    for _, pending in pairs(requests) do
        abandon(pending)
    end
    abandon(stInflight)
    -- a new map starts with empty configstrings; a map_restart keeps them (setting the same value again sends nothing)
    setStrings, synced, sprays, links, sprayCount, lastSpray = {}, {}, {}, {}, {}, {}
    lastTry = {}
    requests, lastPanel, outbox = {}, {}, {}
    stPending, stInflight, stFloor, cgameBuild, sentTags = {}, nil, {}, {}, {}
    stopFeed()
    readyFeed = nil
    held, takenAt, justLinked, toldHeld, invJobs, ledger, bots = {}, {}, {}, {}, {}, {}, {}
    budgets = { at = {}, room = {}, window = {}, info = {}, of = {}, line = {}, snap = {} }
    casts.queue, casts.since, casts.blocked, casts.full = {}, nil, false, {}
    frameTime, publishAt, lastFetchAt = et.trap_Milliseconds(), nil, -1
    -- the round starts here: what FatBoss says until the feed this start downloads is read shows at once
    lastGamestate, roundStartUntil = et.trap_Cvar_Get("gamestate"), frameTime + ROUND_START_MS
    -- the builds a map_restart kept come back in et_ClientConnect; any other start only clears what an earlier map kept
    keptBuilds = {}
    for clientNum = 0, MAX_SLOTS - 1 do
        local value = et.trap_Cvar_Get(BUILD_CVAR .. clientNum) or ""
        if value ~= "" then
            et.trap_Cvar_Set(BUILD_CVAR .. clientNum, "")
            local build, guid = value:match("^(%d%d?%d?%d?%d?) (%x+)$")
            if restart == 1 and build and tonumber(build) >= 1 then
                keptBuilds[clientNum] = { build = tonumber(build), guid = guid }
            end
        end
    end
    -- what earlier runs left goes 30 s into the map, when every curl of the last map is surely over
    sweepAt = et.trap_Milliseconds() + CURL_DONE_MS
    -- the last feed, whole, now: the map is loading, and the configstrings the players connect with need it
    lastStamp, failedStamp = nil, nil
    readLoadouts(true)
    fetchLoadouts()
    nextFetch = levelTime + FETCH_MS
    nextRead = levelTime + READ_MS
    et.G_LogPrint(string.format("%s: loadouts from %s, links %s%s\n", MODNAME,
        (loadoutUrl and loadoutUrl ~= "") and "FatBoss" or "the local file", (linkUrl and linkUrl ~= "") and "on" or "off",
        testMode and ", test mode (/fbequip on)" or ""))
end

-- download every minute (with the StatTrak report), pick up the downloaded file every few seconds; the looks that
-- waited for the round's end go out when the game leaves play
function et_RunFrame(levelTime)
    frameTime, work, casts.blocked = et.trap_Milliseconds(), COST.frame, false
    if next(casts.full) then
        casts.full = {}
    end
    local gamestate = et.trap_Cvar_Get("gamestate")
    if gamestate ~= lastGamestate then
        lastGamestate = gamestate
        if gamestate ~= GS_PLAYING and next(held) ~= nil then
            applyHeld()
        end
        -- a new Lua VM is near (see GS_RESTARTS): the loadout file it reads gets what FatBoss says now (0.22)
        if GS_RESTARTS[gamestate] then
            refreshFile()
        end
    end
    if levelTime >= nextFetch then
        nextFetch = levelTime + FETCH_MS
        fetchLoadouts(reportKills(et.trap_Milliseconds(), false))
        publishLoadouts()             -- a punishment prop whose time is up comes off (only changed strings go out)
    end
    if levelTime >= nextRead then
        nextRead = levelTime + READ_MS
        readLoadouts()
    end
    if next(links) then
        checkLinks(et.trap_Milliseconds())
    end
    if next(requests) then
        checkRequests(et.trap_Milliseconds())
    end
    if readyFeed or feedJob or next(invJobs) then
        readJobs()
    end
    if stInflight then
        checkReport(et.trap_Milliseconds())
    end
    -- what goes to everybody first; while some of it waits for room, no new panel command starts on the lines it
    -- waits for (castNow)
    if casts.queue[1] then
        castStep()
    end
    if publishAt then
        publishStep()
    end
    if not casts.blocked then
        casts.since = nil
    end
    if next(outbox) then
        drainOutbox()
    end
    if abandoned[1] then
        sweepAbandoned(et.trap_Milliseconds())
    end
    if sweepAt and et.trap_Milliseconds() >= sweepAt then
        sweepAt = nil
        sweepLeftovers()
    end
end

-- the kills of the last seconds go to FatBoss before the map (and this Lua VM) ends; a map_restart keeps the builds
function et_ShutdownGame(restart)
    stopFeed()
    reportKills(et.trap_Milliseconds(), true)
    if restart == 1 then
        keepBuilds()
    end
end

-- returns nothing: a string would replace the game's obituary message
function et_Obituary(victim, killer, meansOfDeath)
    countKill(victim, killer, meansOfDeath)
end

function et_ClientCommand(clientNum, command)
    command = string.lower(command or "")
    if command == "spray" then
        spray(clientNum)
        return 1
    end
    if command == "fblink" then
        link(clientNum)
        return 1
    end
    if command == "fbsync" then
        resync(clientNum)
        return 1
    end
    if command == "fbinv" then
        panelInventory(clientNum)
        return 1
    end
    if command == "fbwear" then
        panelWear(clientNum)
        return 1
    end
    if command == "fbequip" and testMode then
        equip(clientNum)
        return 1
    end
    return 0
end

-- a full respawn starts a new life; a revive does not
function et_ClientSpawn(clientNum, revived, teamChange, restoreHealth)
    if revived ~= 1 then
        sprayCount[clientNum] = nil
    end
end

-- Before the gamestate goes out: the connecting player's loadout is in it, so their
-- own cgame and everybody else's (a configstring update) know it from the start.
function et_ClientConnect(clientNum, firstTime, isBot)
    -- after a map_restart the engine connects everybody again (firstTime 0): the same player gets the kept build back,
    -- a new connection or another cl_guid in the slot does not
    local kept = keptBuilds[clientNum]
    keptBuilds[clientNum] = nil
    if kept and firstTime == 0 and kept.guid == guidOf(clientNum) then
        cgameBuild[clientNum] = kept.build
    end
    bots[clientNum] = isBot == 1 or nil
    setLoadout(clientNum, loadoutString(clientNum))
    return nil
end

-- Runs on joining and again on every team change. The first time, the client
-- gets the graffiti already on the map (without the sound).
function et_ClientBegin(clientNum)
    setLoadout(clientNum, loadoutString(clientNum))
    if not synced[clientNum] then
        synced[clientNum] = true
        lastSync[clientNum] = et.trap_Milliseconds()
        syncClient(clientNum)
    end
end

function et_ClientDisconnect(clientNum)
    -- the answers of the player's requests still come; their files go once nobody can need them
    abandon(requests[clientNum])
    abandon(links[clientNum])
    requests[clientNum] = nil
    outbox[clientNum] = nil
    invJobs[clientNum] = nil
    ledger[clientNum] = nil
    toldHeld[clientNum] = nil
    bots[clientNum] = nil
    lastPanel[clientNum] = nil
    sprayCount[clientNum] = nil
    lastSpray[clientNum] = nil
    lastTry[clientNum] = nil
    lastMessage[clientNum] = nil
    synced[clientNum] = nil
    links[clientNum] = nil
    lastLink[clientNum] = nil
    lastSync[clientNum] = nil
    cgameBuild[clientNum] = nil
    keptBuilds[clientNum] = nil
    sentTags[clientNum] = nil
    setLoadout(clientNum, "")
end

