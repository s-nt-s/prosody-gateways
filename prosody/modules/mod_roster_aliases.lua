local json = require "util.json"
local jid = require "prosody.util.jid"
local roster_manager = require "prosody.core.rostermanager"

local aliases_file = module:get_option_string(
    "roster_aliases_file",
    "/var/lib/prosody/roster-names.json"
)

module:log("info", "roster_aliases loaded on host %s", module.host)

-- Lee los aliases en cada operación para aceptar cambios sin reiniciar Prosody.
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

-- Compara mapas de grupos sin depender del orden en que fueron definidos.
local function groups_equal(left, right)
    if type(left) ~= "table" or type(right) ~= "table" then
        return left == right
    end
    for group, enabled in pairs(left) do
        if right[group] ~= enabled then
            return false
        end
    end
    for group, enabled in pairs(right) do
        if left[group] ~= enabled then
            return false
        end
    end
    return true
end

-- Aplica al contacto el nombre y los grupos definidos en el archivo JSON.
local function apply_alias(aliases, contact_jid, item)
    local normalized_jid = jid.prep(contact_jid or item.jid)
    local alias = normalized_jid and aliases[normalized_jid]
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
        if not groups_equal(item.groups, groups) then
            item.groups = groups
        end
    end
end

-- Aplica los aliases al roster y devuelve los contactos que realmente cambiaron.
local function apply_roster(roster, aliases)
    if type(roster) ~= "table" then
        return false, {}
    end
    local changed = false
    local changed_jids = {}
    for jid, item in pairs(roster) do
        if type(item) == "table" and type(jid) == "string" then
            local old_name = item.name
            local old_groups = item.groups
            apply_alias(aliases, jid, item)
            if old_name ~= item.name or old_groups ~= item.groups then
                changed = true
                changed_jids[#changed_jids + 1] = jid
            end
        end
    end
    return changed, changed_jids
end

-- Guarda los cambios usando la API oficial y notifica a las sesiones conectadas.
local function persist_roster_aliases(username, host, roster, aliases)
    local changed, changed_jids = apply_roster(roster, aliases)
    if not changed then
        return true
    end
    if not roster_manager.save_roster(username, host, roster) then
        module:log(
            "error",
            "Could not persist aliases for roster %s@%s",
            username,
            host
        )
        return false
    end
    for _, contact_jid in ipairs(changed_jids) do
        roster_manager.roster_push(username, host, contact_jid)
    end
    return true
end

-- Modifica un item de una petición IQ antes de que Prosody lo persista.
local function apply_stanza_alias(item, aliases)
    local item_jid = jid.prep(item.attr.jid)
    local alias = item_jid and aliases[item_jid]
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

-- Cambia el nick visible de un participante MUC sin cambiar su JID real.
local function apply_participant_alias(event)
    local stanza = event.stanza
    local origin_type = event.origin and event.origin.type or "nil"
    local muc_user = stanza:get_child(
        "x", "http://jabber.org/protocol/muc#user"
    )
    local item = muc_user and muc_user:get_child("item")
    local bare_jid = item and item.attr.jid
    local user_nick = stanza:get_child(
        "nick", "http://jabber.org/protocol/nick"
    )
    module:log(
        "debug",
        "presence hook host=%s origin=%s type=%s from=%s to=%s item.jid=%s item.nick=%s nick=%s stanza=%s",
        module.host,
        origin_type,
        stanza.attr.type or "available",
        stanza.attr.from or "nil",
        stanza.attr.to or "nil",
        bare_jid or "nil",
        item and item.attr.nick or "nil",
        user_nick and user_nick[1] or "nil",
        stanza
    )

    if origin_type ~= "component" then
        return
    end

    local aliases = load_aliases()
    local alias

    if bare_jid then
        alias = aliases[bare_jid] or aliases[jid.bare(bare_jid)]
    end

    if not alias and not bare_jid and stanza.attr.from then
        local _, room_host, participant_resource = jid.split(stanza.attr.from)
        if room_host and participant_resource then
            bare_jid = participant_resource .. "@" .. room_host
            alias = aliases[bare_jid]
        end
    end

    if not alias and item then
        local item_node, item_host = item.attr.jid and jid.split(item.attr.jid)
        if item_node and item_host then
            for alias_jid, candidate in pairs(aliases) do
                local alias_node, alias_host = jid.split(alias_jid)
                if alias_node == item_node and alias_host == item_host then
                    alias = candidate
                    break
                end
            end
        end
    end

    if not alias then
        module:log("debug", "No participant alias for item JID %s", bare_jid or "nil")
        return
    end

    if type(alias) == "table"
        and alias.name ~= json.null
        and type(alias.name) == "string" then
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
        module:log(
            "info",
            "Participant alias applied: %s -> %s; from=%s; item.nick=%s",
            bare_jid,
            alias.name,
            stanza.attr.from or "nil",
            item and item.attr.nick or "nil"
        )
    end
end

module:hook("roster-load", function(event)
    local aliases = load_aliases()
    persist_roster_aliases(event.username, event.host, event.roster, aliases)
end)

-- Reaplica la política cuando el cliente solicita su propio roster.
module:hook("iq/self/jabber:iq:roster:query", function(event)
    if event.stanza.attr.type ~= "get" then
        return
    end
    local aliases = load_aliases()
    persist_roster_aliases(
        event.origin.username,
        event.origin.host,
        event.origin.roster,
        aliases
    )
end, 1)

-- Reaplica la política cuando un componente solicita el roster de un usuario.
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
    local aliases = load_aliases()
    persist_roster_aliases(username, host, roster, aliases)
end, 1)

-- Protege los nombres y grupos frente a cambios enviados por gateways.
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

module:hook("presence/full", apply_participant_alias, 100)
module:hook("presence/bare", apply_participant_alias, 100)
module:hook("presence/host", apply_participant_alias, 100)
