local json = require "util.json"
local st = require "prosody.util.stanza"
local jid = require "prosody.util.jid"

local bookmarks_file = module:get_option_string(
    "default_bookmarks_file",
    "/var/lib/prosody/default-bookmarks.json"
)
local bookmarks_ns = "urn:xmpp:bookmarks:1"
local pubsub_ns = "http://jabber.org/protocol/pubsub"
local mod_pep = module:depends("pep")
local applied = {}
local hooked_services = {}
local repairing = {}

module:log("info", "bookmark_defaults loaded; file=%s", bookmarks_file)

local function load_defaults()
    local file = io.open(bookmarks_file, "r")
    if not file then
        module:log("warn", "Could not open default bookmarks file %s", bookmarks_file)
        return {}
    end
    local content = file:read("*a")
    file:close()
    local decoded, err = json.decode(content)
    if type(decoded) ~= "table" then
        module:log("error", "Could not read %s: %s", bookmarks_file, err or "invalid JSON")
        return {}
    end
    return decoded
end

local function configured_bookmark(id, config)
    local conference = st.stanza("conference", {
        xmlns = bookmarks_ns,
        name = config.name,
        autojoin = config.autojoin and "true" or "false",
    })
    if type(config.nick) == "string" then
        conference:text_tag("nick", config.nick):up()
    end
    return st.stanza("item", { xmlns = pubsub_ns, id = id })
        :add_child(conference)
end

local function same_bookmark(item, config)
    local conference = item and item:get_child("conference", bookmarks_ns)
    if not conference then
        return false
    end
    local nick = conference:get_child_text("nick")
    return conference.attr.name == config.name
        and conference.attr.autojoin == (config.autojoin and "true" or "false")
        and nick == config.nick
end

local function protect_published_bookmark(event)
    local user_jid = jid.bare(event.actor)
    local defaults = load_defaults()[user_jid]
    local config = defaults and defaults[event.id]
    if not config or repairing[user_jid] or same_bookmark(event.item, config) then
        return
    end
    repairing[user_jid] = true
    local published, publish_error = event.service:publish(
        bookmarks_ns,
        user_jid,
        event.id,
        configured_bookmark(event.id, config),
        {
            persist_items = true,
            max_items = "max",
            send_last_published_item = "never",
            access_model = "whitelist",
        }
    )
    repairing[user_jid] = nil
    if not published then
        module:log("error", "Could not restore bookmark %s for %s: %s", event.id, user_jid, publish_error)
    end
end

local function apply_user(user_jid, defaults)
    local bare_jid = jid.bare(user_jid)
    local username = jid.node(bare_jid)
    if not username or type(defaults) ~= "table" or applied[bare_jid] then
        return
    end

    local service = mod_pep.get_pep_service(username)
    if not hooked_services[username] then
        module:hook_object_event(
            service.events,
            "item-published/" .. bookmarks_ns,
            protect_published_bookmark
        )
        hooked_services[username] = true
    end
    local ok, items = service:get_items(bookmarks_ns, bare_jid)
    if not ok and items == "item-not-found" then
        local created, create_error = service:create(bookmarks_ns, bare_jid, {
            persist_items = true,
            max_items = "max",
            send_last_published_item = "never",
            access_model = "whitelist",
        })
        if not created then
            module:log("error", "Could not create bookmarks for %s: %s", bare_jid, create_error)
            return
        end
        items = {}
        ok = true
    end
    if not ok then
        module:log("error", "Could not read bookmarks for %s: %s", bare_jid, items)
        return
    end

    local changed = 0
    for room_jid, config in pairs(defaults) do
        if type(room_jid) == "string" and type(config) == "table"
            and type(config.name) == "string"
            and type(config.autojoin) == "boolean" then
            if not same_bookmark(items[room_jid], config) then
                local published, publish_error = service:publish(
                    bookmarks_ns,
                    bare_jid,
                    room_jid,
                    configured_bookmark(room_jid, config),
                    {
                        persist_items = true,
                        max_items = "max",
                        send_last_published_item = "never",
                        access_model = "whitelist",
                    }
                )
                if not published then
                    module:log("error", "Could not protect bookmark %s for %s: %s", room_jid, bare_jid, publish_error)
                    return
                end
                changed = changed + 1
            end
        end
    end
    applied[bare_jid] = true
    module:log("info", "Protected bookmarks for %s; updated=%d", bare_jid, changed)
end

local function apply_defaults()
    for user_jid, defaults in pairs(load_defaults()) do
        apply_user(user_jid, defaults)
    end
end

module:hook_global("component-authenticated", apply_defaults)
module:hook("authentication-success", function(event)
    local session = event.session
    local user_jid = jid.bare(jid.join(session.username, session.host))
    local defaults = load_defaults()[user_jid]
    if defaults then
        apply_user(user_jid, defaults)
    end
end)
module:hook("ready", apply_defaults)
