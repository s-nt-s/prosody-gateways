local jid = require "prosody.util.jid"
local st = require "prosody.util.stanza"
local hashes = require "prosody.util.hashes"
local encodings = require "prosody.util.encodings"
local base64 = encodings.base64
local hex = encodings.hex

local avatar_dir = module:get_option_path(
    "contact_avatar_dir",
    "/var/lib/prosody/avatar/custom"
)

local PubSubNS = "http://jabber.org/protocol/pubsub"
local AvatarMetadataNS = "urn:xmpp:avatar:metadata"
local AvatarDataNS = "urn:xmpp:avatar:data"
local occupant_jids = module:shared("contact_avatar_jids")

module:log("info", "contact_avatars loaded; directory=%s", avatar_dir)

-- Solo se aceptan JID bare seguros para formar nombres de fichero.
local function safe_bare_jid(target)
    local bare = jid.bare(target)
    if not bare or bare:find("[/\\]", 1) or bare:find("%.%.") then
        return nil
    end
    return bare
end

-- Busca primero PNG y después JPG, según la convención del directorio.
local function avatar_jid_for_target(target)
    local occupant_jid = occupant_jids[target]
    if occupant_jid then
        return occupant_jid
    end
    local bare_target = jid.bare(target)
    occupant_jid = occupant_jids[bare_target]
    if occupant_jid then
        return occupant_jid
    end
    return safe_bare_jid(target)
end

local function load_avatar(target)
    local bare = avatar_jid_for_target(target)
    if not bare then
        return nil
    end

    local extensions = {
        { suffix = ".png", mime = "image/png" },
        { suffix = ".jpg", mime = "image/jpeg" },
    }
    for _, image in ipairs(extensions) do
        local path = avatar_dir .. "/" .. bare .. image.suffix
        local file = io.open(path, "rb")
        if file then
            local data = file:read("*a")
            file:close()
            if data and #data > 0 then
                return {
                    data = data,
                    hash = hashes.sha1(data),
                    mime = image.mime,
                    bytes = #data,
                }
            end
        end
    end
end

-- Recuerda el JID real asociado a un ocupante visible de una sala MUC.
local function remember_occupant(event)
    local stanza = event.stanza
    if event.origin and event.origin.type ~= "component" then
        return
    end
    local muc_user = stanza:get_child(
        "x", "http://jabber.org/protocol/muc#user"
    )
    local item = muc_user and muc_user:get_child("item")
    if item and item.attr.jid and stanza.attr.from then
        local occupant_jid = jid.bare(item.attr.jid)
        local from = stanza.attr.from
        occupant_jids[from] = occupant_jid
        occupant_jids[jid.bare(from)] = occupant_jid
        if item.attr.nick then
            local room = from:match("^([^/]+)/")
            if room then
                occupant_jids[room .. "/" .. item.attr.nick] = occupant_jid
            end
        end
        local avatar = load_avatar(occupant_jid)
        if avatar then
            local update = stanza:get_child(
                "x", "vcard-temp:x:update"
            )
            if not update then
                stanza:tag("x", { xmlns = "vcard-temp:x:update" }):up()
                update = stanza:get_child("x", "vcard-temp:x:update")
            end
            local photo = update and update:get_child("photo")
            if not photo then
                update:text_tag("photo", hex.encode(avatar.hash))
            else
                photo[1] = hex.encode(avatar.hash)
            end
        end
    end
end

-- Construye la metadata que permite al cliente localizar el avatar.
local function metadata_payload(avatar)
    return st.stanza("metadata", { xmlns = AvatarMetadataNS })
        :tag("info", {
            id = hex.encode(avatar.hash),
            type = avatar.mime,
            bytes = tostring(avatar.bytes),
        })
end

local function send_avatar_data(event, avatar, item_id)
    local reply = st.reply(event.stanza)
        :tag("pubsub", { xmlns = PubSubNS })
            :tag("items", { node = AvatarDataNS })
                :tag("item", { id = item_id })
                    :add_child(
                        st.stanza("data", { xmlns = AvatarDataNS })
                            :text(base64.encode(avatar.data))
                    )
    event.origin.send(reply)
    return true
end

local function send_avatar_metadata(event, avatar)
    local item_id = hex.encode(avatar.hash)
    local reply = st.reply(event.stanza)
        :tag("pubsub", { xmlns = PubSubNS })
            :tag("items", { node = AvatarMetadataNS })
                :tag("item", { id = item_id })
                    :add_child(metadata_payload(avatar))
    event.origin.send(reply)
    return true
end

-- Intercepta solo consultas de lectura de avatar destinadas a cualquier JID.
local function handle_avatar_query(event)
    local stanza = event.stanza
    if stanza.attr.type ~= "get" or not stanza.attr.to then
        return
    end

    module:log("debug", "Avatar query for %s: %s", stanza.attr.to, stanza)
    local avatar = load_avatar(stanza.attr.to)
    if not avatar then
        return
    end

    local pubsub = stanza:get_child("pubsub", PubSubNS)
    local items = pubsub and pubsub:get_child("items")
    local node = items and items.attr.node
    if node == AvatarMetadataNS then
        return send_avatar_metadata(event, avatar)
    elseif node == AvatarDataNS then
        return send_avatar_data(event, avatar, items:get_child("item")
            and items:get_child("item").attr.id or hex.encode(avatar.hash))
    end
end

-- Intercepta la petición antes de que se enrute al componente del gateway.
module:hook("pre-iq/bare", handle_avatar_query, 1000)
module:hook("pre-iq/full", handle_avatar_query, 1000)
module:hook("presence/bare", remember_occupant, 90)
module:hook("presence/full", remember_occupant, 90)
