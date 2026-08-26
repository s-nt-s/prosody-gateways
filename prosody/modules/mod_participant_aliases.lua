local json = require "util.json"
local jid = require "prosody.util.jid"

local aliases_file = module:get_option_string(
    "roster_aliases_file",
    "/var/lib/prosody/roster-names.json"
)

module:log("info", "participant_aliases loaded on host %s", module.host)

local function load_aliases()
    local file = io.open(aliases_file, "r")
    if not file then
        return {}
    end
    local content = file:read("*a")
    file:close()
    local decoded, err = json.decode(content)
    if type(decoded) == "table" then
        return decoded
    end
    module:log("error", "Could not read %s: %s", aliases_file, err or "invalid JSON")
    return {}
end

local function find_alias(aliases, item, stanza)
    local bare_jid = item and item.attr.jid
    if bare_jid then
        local alias = aliases[bare_jid] or aliases[jid.bare(bare_jid)]
        if alias then
            return alias, bare_jid
        end
    end
    if not bare_jid and stanza.attr.from then
        local _, room_host, participant_resource = jid.split(stanza.attr.from)
        if room_host and participant_resource then
            bare_jid = participant_resource .. "@" .. room_host
            if aliases[bare_jid] then
                return aliases[bare_jid], bare_jid
            end
        end
    end
    if item and item.attr.jid then
        local item_node, item_host = jid.split(item.attr.jid)
        if item_node and item_host then
            for alias_jid, candidate in pairs(aliases) do
                local alias_node, alias_host = jid.split(alias_jid)
                if alias_node == item_node and alias_host == item_host then
                    return candidate, item.attr.jid
                end
            end
        end
    end
    return nil, bare_jid
end

local function apply_participant_alias(event)
    local stanza = event.stanza
    if not event.origin or event.origin.type ~= "component" then
        return
    end
    local muc_user = stanza:get_child(
        "x", "http://jabber.org/protocol/muc#user"
    )
    local item = muc_user and muc_user:get_child("item")
    local user_nick = stanza:get_child(
        "nick", "http://jabber.org/protocol/nick"
    )
    local alias, bare_jid = find_alias(load_aliases(), item, stanza)
    if type(alias) ~= "table"
        or alias.name == json.null
        or type(alias.name) ~= "string" then
        return
    end
    if item then
        item.attr.nick = alias.name
    end
    local from_room = stanza.attr.from and stanza.attr.from:match("^([^/]+)")
    if from_room then
        stanza.attr.from = from_room .. "/" .. alias.name
    end
    if user_nick then
        user_nick[1] = alias.name
    else
        stanza:tag("nick", { xmlns = "http://jabber.org/protocol/nick" })
            :text(alias.name)
            :up()
    end
    module:log("info", "Participant alias applied: %s -> %s", bare_jid or "nil", alias.name)
end

module:hook("presence/full", apply_participant_alias, 100)
module:hook("presence/bare", apply_participant_alias, 100)
module:hook("presence/host", apply_participant_alias, 100)