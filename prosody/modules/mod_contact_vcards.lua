local jid = require "prosody.util.jid"
local st = require "prosody.util.stanza"
local hashes = require "prosody.util.hashes"
local encodings = require "prosody.util.encodings"
local base64 = encodings.base64

local avatar_dir = module:get_option_path(
    "contact_avatar_dir",
    "/var/lib/prosody/avatar/custom"
)
local avatar_jids = module:shared("contact_avatar_jids")
local VCardNS = "vcard-temp"

local function load_avatar(target)
    local bare = avatar_jids[target] or avatar_jids[jid.bare(target)] or jid.bare(target)
    if not bare or bare:find("[/\\]", 1) or bare:find("%.%.") then
        return nil
    end
    for _, image in ipairs({
        { suffix = ".png", mime = "image/png" },
        { suffix = ".jpg", mime = "image/jpeg" },
    }) do
        local file = io.open(avatar_dir .. "/" .. bare .. image.suffix, "rb")
        if file then
            local data = file:read("*a")
            file:close()
            if data and #data > 0 then
                return { data = data, hash = hashes.sha1(data), mime = image.mime }
            end
        end
    end
end

local function handle_vcard_query(event)
    local stanza = event.stanza
    if stanza.attr.type ~= "get" or not stanza.attr.to
        or not stanza:get_child("vCard", VCardNS) then
        return
    end
    local avatar = load_avatar(stanza.attr.to)
    if not avatar then
        return
    end
    local reply = st.reply(stanza)
        :tag("vCard", { xmlns = VCardNS })
            :tag("PHOTO")
                :tag("TYPE"):text(avatar.mime):up()
                :tag("BINVAL"):text(base64.encode(avatar.data))
    event.origin.send(reply)
    return true
end

module:hook("pre-iq/bare", handle_vcard_query, 1000)
module:hook("pre-iq/full", handle_vcard_query, 1000)