local json = require "util.json"
local base64 = require "util.encodings".base64
local jid = require "util.jid"
local usermanager = require "core.usermanager"

module:depends("http")

local room_service = module:get_option_string("rooms_service")
local username_host = module.host

local function response(status_code, body, headers)
    return {
        status_code = status_code,
        headers = headers or { content_type = "application/json; charset=utf-8" },
        body = json.encode(body),
    }
end

local function unauthorized()
    return response(401, { error = "authentication required" }, {
        content_type = "application/json; charset=utf-8",
        www_authenticate = 'Basic realm="Prosody rooms"',
    })
end

local function authenticate(request)
    local header = request.headers.authorization
    local encoded = header and header:match("^[Bb]asic%s+(.+)$")
    if not encoded then
        return nil
    end

    local decoded = base64.decode(encoded)
    if not decoded then
        return nil
    end

    local username, password = decoded:match("^([^:]+):(.*)$")
    if not username or not password then
        return nil
    end

    local account, host = jid.split(username)
    if not account then
        account, host = username, username_host
    end
    if not host or host ~= username_host then
        return nil
    end

    if usermanager.test_password(account, host, password) then
        return account .. "@" .. host
    end
    return nil
end

local function get_muc_module()
    local host = prosody.hosts[room_service]
    return host and host.modules and host.modules.muc
end

local function get_affiliations(room)
    local affiliations = {}
    for contact_jid, affiliation in room:each_affiliation() do
        affiliations[#affiliations + 1] = {
            jid = contact_jid,
            affiliation = affiliation or "none",
        }
    end
    table.sort(affiliations, function(left, right)
        return left.jid < right.jid
    end)
    return affiliations
end

local function visible_to_user(room, user_jid)
    return room:get_public() or (room:get_affiliation(user_jid) or "none") ~= "none"
end

local function list_rooms(user_jid)
    local muc = get_muc_module()
    if not muc or not muc.all_rooms then
        return nil, "MUC service is not available"
    end

    local rooms = {}
    for room in muc.all_rooms() do
        if visible_to_user(room, user_jid) then
            rooms[#rooms + 1] = {
                jid = room.jid,
                name = room:get_name(),
                public = room:get_public(),
                persistent = room:get_persistent(),
                members_only = room:get_members_only(),
                affiliations = get_affiliations(room),
            }
        end
    end
    table.sort(rooms, function(left, right)
        return left.jid < right.jid
    end)
    return rooms
end

local function handle_rooms(event)
    local user_jid = authenticate(event.request)
    if not user_jid then
        return unauthorized()
    end

    local rooms, err = list_rooms(user_jid)
    if not rooms then
        return response(503, { error = err })
    end
    return response(200, { rooms = rooms })
end

module:provides("http", {
    route = {
        ["GET"] = handle_rooms,
    },
})