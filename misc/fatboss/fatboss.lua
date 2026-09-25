--[[
    fatboss.lua - FatBoss cosmetics on the official ET: Legacy server.

    Works with the FatBoss cgame (zzz_fatboss_*.pk3) and its skins pack
    (zzz_fatboss_skins_*.pk3), which draw everything; this module decides who
    wears what and tells every client.

    Weapon skins: each player's FatBoss loadout picks a theme for the knife,
    colt, luger, thompson and mp40. Everybody sees everybody's skins. The
    loadout (and the graffiti design) sits in a configstring of its own,
    FB_CS + client number, so it reaches every client with the gamestate and
    the cgame loads all textures on the loading screen; a change during the map
    is a configstring update the cgame applies at the intermission, on the next
    map or after /reconnect.

    Graffiti: a player binds "spray" (bind t spray). One graffiti per life, and
    each player's newest graffiti replaces the older one.

    Loadouts come from FatBoss. With FATBOSS_LOADOUT_URL set, the module
    fetches this every minute in the background (FATBOSS_API_TOKEN is sent as
    a bearer token):
        {"<cl_guid>": {"graffiti": "gg",
                       "skins": {"knife": "damascus", "colt": "gold", "luger": "neon",
                                 "thompson": "wut", "mp40": "camo"}}, ...}
    Without the URL, the same JSON is read from <fs_homepath>/legacy/fatboss_loadouts.json.

    Game link: the FatBoss profile shows "/fblink CODE"; a player pastes it in
    the console and the module posts {code, guid, name, server} to
    FATBOSS_LINK_URL (by default the loadout URL with /loadouts replaced by
    /link), then tells the player how it went.

    FATBOSS_DEFAULT_GRAFFITI=fatboss lets players without a graffiti of their
    own spray that design (the FatBoss starter everybody gets).

    FATBOSS_TEST=1 (test servers only): everybody gets the "fatboss" graffiti,
    and /fbequip <slot> <theme> tries any skin or graffiti without FatBoss.

    Runs next to Oksii's stats.lua and combinedfixes.lua in its own Lua VM and
    handles only its own commands ("spray", "fblink", "fbsync", and "fbequip" in test mode).
    fbsync (a cgame restart) gets the graffiti on the map again; skins need nothing.
]]

local json = require("dkjson")

local MODNAME = "fatboss"
local VERSION = "0.8"

local SLOTS           = { "knife", "colt", "luger", "thompson", "mp40" }   -- order in the configstring
-- first configstring past CS_MAX of ET: Legacy 2.86 (bg_public.h); the FatBoss cgame reads FB_CS + client
local FB_CS           = 943
local THEMES_HELP     = "gold polska neon camo cyber plasma airstrike damascus (knives) defender (colt) wut (thompson, kabar)"
local SPRAY_RANGE     = 128
local SPRAY_RADIUS    = 28      -- half the side of the graffiti square, in game units
local SPRAY_SCALES    = { 1.0, 0.8, 0.6 }
local SPRAY_SHIFTS    = { { 0, 0 }, { 0.35, 0 }, { -0.35, 0 }, { 0, 0.35 }, { 0, -0.35 },
                          { 0.3, 0.3 }, { -0.3, 0.3 }, { 0.3, -0.3 }, { -0.3, -0.3 } }
local ENTITYNUM_WORLD = (et.MAX_GENTITIES or 1024) - 2
local SURF_SKY        = 0x4
local SURF_NOMARKS    = 0x20
local TEAM_AXIS       = 1
local TEAM_ALLIES     = 2
local CON_CONNECTED   = 2
local FETCH_MS        = 60000
local READ_MS         = 5000
local MESSAGE_GAP_MS  = 1500
local LINK_WAIT_MS    = 15000   -- how long a /fblink waits for FatBoss to answer
local LINK_GAP_MS     = 5000    -- one /fblink per player every few seconds
local SYNC_GAP_MS     = 3000    -- one fbsync (a cgame restart) per player every few seconds

local loadouts     = {}  -- cl_guid (upper case) -> { graffiti = design, skins = { slot = theme } }
local testLoadouts = {}  -- the same, set with /fbequip in test mode; wins over loadouts
local setStrings   = {}  -- clientNum -> loadout configstring last set
local synced       = {}  -- clientNum -> true once the client got the graffiti on the map
local sprays       = {}  -- clientNum -> fbspray command without the sound flag
local usedThisLife = {}  -- clientNum -> true once sprayed in the current life
local lastMessage  = {}  -- clientNum -> level time of the last refusal
local links        = {}  -- clientNum -> { file, guid, deadline } of a /fblink waiting for FatBoss
local lastLink     = {}  -- clientNum -> time of the last /fblink
local lastSync     = {}  -- clientNum -> time the client last got everything
local loadoutPath, loadoutUrl, linkUrl, apiToken, testMode, defaultGraffiti, maxClients, homeDir
local nextFetch, nextRead, lastLoadoutText = 0, 0, nil

local function shellQuote(s)
    return "'" .. tostring(s):gsub("'", "'\"'\"'") .. "'"
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

local function loadoutOf(clientNum)
    local guid = guidOf(clientNum)
    if guid == "" then
        return {}
    end
    return testLoadouts[guid] or loadouts[guid] or {}
end

-- "<knife> <colt> <luger> <thompson> <mp40> <graffiti>", "-" for stock; "" for nothing at all (a small gamestate)
local function loadoutString(clientNum)
    local loadout = loadoutOf(clientNum)
    local skins = loadout.skins or {}
    local parts, any = {}, false
    for _, slot in ipairs(SLOTS) do
        parts[#parts + 1] = skins[slot] or "-"
        any = any or skins[slot] ~= nil
    end
    local graffiti = loadout.graffiti or defaultGraffiti
    parts[#parts + 1] = graffiti or "-"
    if not any and not graffiti then
        return ""
    end
    return table.concat(parts, " ")
end

local function setLoadout(clientNum, value)
    if setStrings[clientNum] ~= value then
        setStrings[clientNum] = value
        et.trap_SetConfigstring(FB_CS + clientNum, value)
    end
end

-- every connected player's loadout into its configstring (only the changed ones go out)
local function publishLoadouts()
    for clientNum = 0, maxClients - 1 do
        if connected(clientNum) then
            setLoadout(clientNum, loadoutString(clientNum))
        end
    end
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
        out.skins = {}
        for _, slot in ipairs(SLOTS) do
            if validName(entry.skins[slot]) then
                out.skins[slot] = entry.skins[slot]
            end
        end
    end
    return out
end

-- reads the loadout file when it changed; a broken file keeps the last good table
local function readLoadouts()
    local f = io.open(loadoutPath, "r")
    if not f then
        return
    end
    local text = f:read("*a")
    f:close()
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
    loadouts, lastLoadoutText = fresh, text
    et.G_LogPrint(string.format("%s: %d loadouts\n", MODNAME, count))
    publishLoadouts()
end

-- background download; the file is swapped in only when curl succeeds
local function fetchLoadouts()
    if not loadoutUrl or loadoutUrl == "" then
        return
    end
    local tmp = loadoutPath .. ".tmp"
    local auth = ""
    if apiToken and apiToken ~= "" then
        auth = " -H " .. shellQuote("Authorization: Bearer " .. apiToken)
    end
    os.execute(string.format("(curl -fsS --max-time 10%s -o %s %s && mv -f %s %s) >/dev/null 2>&1 &",
        auth, shellQuote(tmp), shellQuote(loadoutUrl), shellQuote(tmp), shellQuote(loadoutPath)))
end

local function refuse(clientNum, levelTime, text)
    if lastMessage[clientNum] and levelTime - lastMessage[clientNum] < MESSAGE_GAP_MS then
        return
    end
    lastMessage[clientNum] = levelTime
    et.trap_SendServerCommand(clientNum, string.format('cpm "^3FatBoss:^7 %s"', text))
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
                or (tr.surfaceFlags & (SURF_SKY | SURF_NOMARKS)) ~= 0 or dot(tr.plane.normal, n) < 0.7 then
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
    if usedThisLife[clientNum] then
        return refuse(clientNum, levelTime, "one graffiti per life.")
    end
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
    if tr.entityNum ~= ENTITYNUM_WORLD or (tr.surfaceFlags & (SURF_SKY | SURF_NOMARKS)) ~= 0 then
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
    et.trap_SendServerCommand(-1, cmd .. " 1")
    sprays[clientNum] = cmd .. " 0"
    usedThisLife[clientNum] = true
    et.G_LogPrint(string.format("%s: spray %d %s %s\n", MODNAME, clientNum, guidOf(clientNum), design))
end

local function tell(clientNum, text)
    et.trap_SendServerCommand(clientNum, string.format('print "^3FatBoss:^7 %s\n"', text))
    et.trap_SendServerCommand(clientNum, string.format('cpm "^3FatBoss:^7 %s"', text))
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
    local base = string.format("%s/fatboss_link_%d_%d", homeDir, clientNum, now)
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
    os.execute(string.format("(curl -sS --max-time 10%s -H 'Content-Type: application/json' --data @%s -o %s.tmp %s; mv -f %s.tmp %s.res; rm -f %s) >/dev/null 2>&1 &",
        auth, shellQuote(base .. ".req"), shellQuote(base), shellQuote(linkUrl), shellQuote(base), shellQuote(base), shellQuote(base .. ".req")))
    links[clientNum] = { file = base .. ".res", guid = guid, deadline = now + LINK_WAIT_MS }
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
                tell(clientNum, string.format("^2linked^7 to %s. Your FatBoss loadout shows up within a minute.", tostring(answer.name or "your account")))
                et.G_LogPrint(string.format("%s: linked %d %s\n", MODNAME, clientNum, pending.guid))
                nextFetch = 0          -- fetch the loadouts right away
            elseif type(answer) == "table" and answer.error then
                tell(clientNum, "^1not linked:^7 " .. tostring(answer.error))
            else
                tell(clientNum, "^1not linked:^7 FatBoss did not answer properly. Try again in a minute.")
            end
        elseif now > pending.deadline then
            links[clientNum] = nil
            tell(clientNum, "^1not linked:^7 no answer from FatBoss. Try again in a minute.")
        end
    end
end

-- /fbequip <knife|colt|luger|thompson|mp40|graffiti> <name|->  (test servers only)
local function equip(clientNum)
    local guid = guidOf(clientNum)
    local slot = string.lower(et.trap_Argv(1) or "")
    local name = string.lower(et.trap_Argv(2) or "")
    local say = function(text)
        et.trap_SendServerCommand(clientNum, string.format('print "^3FatBoss:^7 %s\n"', text))
    end
    if guid == "" then
        return say("no cl_guid, nothing to equip.")
    end
    local valid = slot == "graffiti"
    for _, s in ipairs(SLOTS) do
        valid = valid or s == slot
    end
    if not valid or (name ~= "-" and not validName(name)) then
        say("usage: /fbequip <knife|colt|luger|thompson|mp40> <theme|->   or   /fbequip graffiti <design>")
        say("themes: " .. THEMES_HELP)
        return say("graffiti: fatboss poland_et gg ez gibbed noob nice_try cloudy skill_issue jebac_axis jebac_allies kurwa_mac wut_1112 sprzedam_opla nastepny_przystanek next_stop skill_404 rip_bozo lagging get_rekt")
    end
    local entry = testLoadouts[guid]
    if not entry then
        -- start from the real loadout, so one slot changes at a time
        local base = loadouts[guid] or {}
        entry = { graffiti = base.graffiti, skins = {} }
        for k, v in pairs(base.skins or {}) do
            entry.skins[k] = v
        end
        testLoadouts[guid] = entry
    end
    if slot == "graffiti" then
        entry.graffiti = name ~= "-" and name or nil
    else
        entry.skins[slot] = name ~= "-" and name or nil
    end
    say(string.format("%s = %s (shows after /reconnect, on the next map or at the intermission; fb_loadskins loads it now)", slot, name))
    setLoadout(clientNum, loadoutString(clientNum))
end

-- the graffiti already on the map, to one client (without the sound)
local function syncClient(clientNum)
    for _, cmd in pairs(sprays) do
        et.trap_SendServerCommand(clientNum, cmd)
    end
end

-- The FatBoss cgame asks for the graffiti again when it restarts (vid_restart
-- forgets what the server sent when the player joined).
local function resync(clientNum)
    local now = et.trap_Milliseconds()
    if not synced[clientNum] or (lastSync[clientNum] and now - lastSync[clientNum] < SYNC_GAP_MS) then
        return
    end
    lastSync[clientNum] = now
    syncClient(clientNum)
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
    apiToken = os.getenv("FATBOSS_API_TOKEN")
    testMode = os.getenv("FATBOSS_TEST") == "1"
    defaultGraffiti = os.getenv("FATBOSS_DEFAULT_GRAFFITI")
    if not validName(defaultGraffiti) then
        defaultGraffiti = testMode and "fatboss" or nil
    end
    -- a new map starts with empty configstrings; a map_restart keeps them (setting the same value again sends nothing)
    setStrings, synced, sprays, links, usedThisLife = {}, {}, {}, {}, {}
    readLoadouts()
    fetchLoadouts()
    nextFetch = levelTime + FETCH_MS
    nextRead = levelTime + READ_MS
    et.G_LogPrint(string.format("%s: loadouts from %s, links %s%s\n", MODNAME,
        (loadoutUrl and loadoutUrl ~= "") and "FatBoss" or "the local file", (linkUrl and linkUrl ~= "") and "on" or "off",
        testMode and ", test mode (/fbequip on)" or ""))
end

-- download every minute, pick up the downloaded file every few seconds
function et_RunFrame(levelTime)
    if levelTime >= nextFetch then
        nextFetch = levelTime + FETCH_MS
        fetchLoadouts()
    end
    if levelTime >= nextRead then
        nextRead = levelTime + READ_MS
        readLoadouts()
    end
    if next(links) then
        checkLinks(et.trap_Milliseconds())
    end
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
    if command == "fbequip" and testMode then
        equip(clientNum)
        return 1
    end
    return 0
end

-- a full respawn starts a new life; a revive does not
function et_ClientSpawn(clientNum, revived, teamChange, restoreHealth)
    if revived ~= 1 then
        usedThisLife[clientNum] = nil
    end
end

-- Before the gamestate goes out: the connecting player's loadout is in it, so their
-- own cgame and everybody else's (a configstring update) know it from the start.
function et_ClientConnect(clientNum, firstTime, isBot)
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
    usedThisLife[clientNum] = nil
    lastMessage[clientNum] = nil
    synced[clientNum] = nil
    links[clientNum] = nil
    lastLink[clientNum] = nil
    lastSync[clientNum] = nil
    setLoadout(clientNum, "")
end

