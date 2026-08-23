local json = require "util.json"
local jid = require "prosody.util.jid"
local roster_manager = require "prosody.core.rostermanager"

local aliases_file = module:get_option_string(
    "roster_aliases_file",
    "/var/lib/prosody/roster-names.json"
)

local roster_defaults = setmetatable({}, { __mode = "k" })
local aliases_signatures = setmetatable({}, { __mode = "k" })

local function load_aliases()
    local file = io.open(aliases_file, "r")
    if not file then
        return {}, nil
    end

    local content = file:read("*a")
    file:close()
    local decoded, err = json.decode(content)
    if type(decoded) == "table" then
        return decoded, content
    end
    module:log("error", "Could not read %s: %s", aliases_file, err or "invalid JSON")
    return {}, content
end

local function apply_alias(aliases, jid, item)
    local alias = aliases[jid or item.jid]
    if type(alias) ~= "table" then
        return
    end

    local name = alias.name
    if name ~= json.null and type(name) == "string" then
        item.name = alias.name
    end

    local configured_groups = alias.groups
    if configured_groups ~= json.null and type(configured_groups) == "table" then
        local groups = {}
        for _, group in ipairs(configured_groups) do
            if type(group) == "string" then
                groups[group] = true
            end
        end
        item.groups = groups
    end
end

local function save_roster_defaults(roster)
    local defaults = {}
    for jid, item in pairs(roster) do
        if type(item) == "table" and type(jid) == "string" then
            defaults[jid] = {
                name = item.name,
                groups = item.groups,
            }
        end
    end
    roster_defaults[roster] = defaults
end

local function apply_roster(roster, aliases)
    if type(roster) ~= "table" then
        return
    end
    local defaults = roster_defaults[roster]
    if not defaults then
        save_roster_defaults(roster)
        defaults = roster_defaults[roster]
    end
    for jid, item in pairs(roster) do
        if type(item) == "table" and type(jid) == "string" then
            local default = defaults[jid]
            if default then
                item.name = default.name
                item.groups = default.groups
            end
            apply_alias(aliases, jid, item)
        end
    end
end

local function apply_stanza_alias(item, aliases)
    local alias = aliases[item.attr.jid]
    if type(alias) ~= "table" then
        return
    end

    if alias.name ~= json.null and type(alias.name) == "string" then
        item.attr.name = alias.name
    end

    local configured_groups = alias.groups
    if configured_groups ~= json.null and type(configured_groups) == "table" then
        for index = #item, 1, -1 do
            if item[index].name == "group" then
                table.remove(item, index)
            end
        end
        for _, group in ipairs(configured_groups) do
            if type(group) == "string" then
                item:tag("group"):text(group):up()
            end
        end
    end
end

module:hook("roster-load", function(event)
    save_roster_defaults(event.roster)
    local aliases = load_aliases()
    apply_roster(event.roster, aliases)
end)

module:hook("iq/self/jabber:iq:roster:query", function(event)
    if event.stanza.attr.type ~= "get" then
        return
    end
    local aliases, signature = load_aliases()
    local roster = event.origin.roster
    if roster and roster[false]
        and signature ~= aliases_signatures[roster] then
        roster[false].version = (roster[false].version or 0) + 1
        aliases_signatures[roster] = signature
    end
    apply_roster(roster, aliases)
end, 1)

module:hook("iq-get/bare/jabber:iq:roster:query", function(event)
    local target = event.stanza.attr.to
    if not target then
        return
    end

    local username, host = jid.split(target)
    if not username or not host then
        return
    end

    local roster = roster_manager.load_roster(username, host)
    local aliases, signature = load_aliases()
    if roster and roster[false]
        and signature ~= aliases_signatures[roster] then
        roster[false].version = (roster[false].version or 0) + 1
        aliases_signatures[roster] = signature
    end
    apply_roster(roster, aliases)
end, 1)

module:hook("iq-set/bare/jabber:iq:roster:query", function(event)
    local target = event.stanza.attr.to
    if not target then
        return
    end

    local aliases = load_aliases()
    local query = event.stanza.tags[1]
    if not query then
        return
    end
    for _, item in ipairs(query.tags) do
        if item.name == "item" and item.attr.jid then
            apply_stanza_alias(item, aliases)
        end
    end
end, 1)

module:hook("roster-item-added", function(event)
    local aliases = load_aliases()
    apply_alias(aliases, event.jid, event.item)
end)

module:hook("roster-item-updated", function(event)
    local aliases = load_aliases()
    apply_alias(aliases, event.jid, event.item)
end)