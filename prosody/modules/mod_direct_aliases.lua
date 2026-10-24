local json = require "util.json"
local jid = require "prosody.util.jid"
local roster_manager = require "prosody.core.rostermanager"

local aliases_file = module:get_option_string(
    "roster_aliases_file",
    "/var/lib/prosody/roster-names.json"
)

module:log("info", "direct_aliases loaded on host %s", module.host)

local function load_aliases()
    local file = io.open(aliases_file, "r")
    if not file then
        return {}
    end
    local content = file:read("*a")
    file:close()
    local aliases, err = json.decode(content)
    if type(aliases) == "table" then
        return aliases
    end
    module:log("error", "Could not read %s: %s", aliases_file, err or "invalid JSON")
    return {}
end

local function find_alias(aliases, from)
    local bare_from = jid.bare(from)
    local alias = aliases[from] or aliases[bare_from]
    if type(alias) == "table"
        and alias.name ~= json.null
        and type(alias.name) == "string" then
        return alias.name
    end
    return nil
end

local function is_in_recipient_roster(stanza, from)
    if not stanza.attr.to then
        return false
    end
    local username, host = jid.split(jid.bare(stanza.attr.to))
    if not username or not host then
        return false
    end
    local roster = roster_manager.load_roster(username, host)
    return roster and roster[jid.prep(jid.bare(from))] ~= nil
end

local function apply_direct_alias(event)
    local stanza = event.stanza
    if not event.origin or event.origin.type ~= "component"
        or not stanza.attr.from then
        return
    end

    if is_in_recipient_roster(stanza, stanza.attr.from) then
        return
    end

    local alias = find_alias(load_aliases(), stanza.attr.from)
    if not alias then
        return
    end

    local bare_from = jid.bare(stanza.attr.from)
    stanza.attr.from = bare_from .. "/" .. alias
    local nick = stanza:get_child("nick", "http://jabber.org/protocol/nick")
    if nick then
        nick[1] = alias
    else
        stanza:tag("nick", { xmlns = "http://jabber.org/protocol/nick" })
            :text(alias)
            :up()
    end
    module:log("info", "Direct alias applied: %s -> %s", bare_from, alias)
end

module:hook("message/bare", apply_direct_alias, 100)
module:hook("message/full", apply_direct_alias, 100)