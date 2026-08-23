local lfs = require "lfs"
local st = require "prosody.util.stanza"
local base64 = require "prosody.util.encodings".base64
local sha1 = require "prosody.util.hashes".sha1
local jid = require "prosody.util.jid"

local data_path = module:get_option_string("data_path", "/var/lib/prosody")
local custom_path = data_path .. "/avatar/custom"
local default_path = data_path .. "/avatar/default"

local nodes = {
    data = "urn:xmpp:avatar:data",
    metadata = "urn:xmpp:avatar:metadata",
}

local image_types = {
    jpg = "image/jpeg",
    jpeg = "image/jpeg",
    png = "image/png",
    gif = "image/gif",
    webp = "image/webp",
    bmp = "image/bmp",
    tif = "image/tiff",
    tiff = "image/tiff",
}

local function image_file(directory, jid)
    if lfs.attributes(directory, "mode") ~= "directory" then
        return nil
    end
    local newest
    for filename in lfs.dir(directory) do
        if filename ~= "." and filename ~= ".." then
            local candidate_jid, extension = filename:match("^(.*)%.([^.]*)$")
            if candidate_jid == jid and image_types[extension:lower()] then
                local path = directory .. "/" .. filename
                local attributes = lfs.attributes(path)
                if attributes and attributes.mode == "file"
                    and (not newest or attributes.modification > newest.modification
                        or attributes.modification == newest.modification
                        and filename > newest.filename) then
                    newest = {
                        filename = filename,
                        path = path,
                        modification = attributes.modification,
                        type = image_types[extension:lower()],
                    }
                end
            end
        end
    end
    return newest
end

local function read_image(image)
    if not image then
        return nil
    end
    local file = io.open(image.path, "rb")
    if not file then
        return nil
    end
    local raw = file:read("*a")
    file:close()
    if not raw or #raw == 0 then
        return nil
    end
    if image.type == "image/png" and raw:sub(1, 8) ~= "\137PNG\r\n\026\n"
        or image.type == "image/jpeg" and raw:sub(1, 2) ~= "\255\216"
        or image.type == "image/gif" and raw:sub(1, 3) ~= "GIF"
        or image.type == "image/webp" and raw:sub(1, 4) ~= "RIFF"
        or image.type == "image/bmp" and raw:sub(1, 2) ~= "BM"
        or image.type == "image/tiff"
            and raw:sub(1, 4) ~= "II*\0"
            and raw:sub(1, 4) ~= "MM\0*" then
        return nil
    end
    return raw
end

local function avatar_item(image)
    local raw = read_image(image)
    if not raw then
        return nil
    end
    local encoded = base64.encode(raw)
    local hash = sha1(raw, true)
    local data = st.stanza("item", { xmlns = "http://jabber.org/protocol/pubsub", id = hash })
        :tag("data", { xmlns = nodes.data }):text(encoded)
    local metadata = st.stanza("item", { xmlns = "http://jabber.org/protocol/pubsub", id = hash })
        :tag("metadata", { xmlns = nodes.metadata })
            :tag("info", { id = hash, bytes = tostring(#raw), type = image.type })
    return {
        hash = hash,
        raw = raw,
        type = image.type,
        data = data,
        metadata = metadata,
    }
end

local function avatar_from(directory, jid)
    return avatar_item(image_file(directory, jid))
end

local function rewrite_avatar_update(event)
    local stanza = event.stanza
    local source = stanza.attr.from
    if not source then
        return
    end

    source = jid.bare(source)
    if module:get_host_type() ~= "component" then
        return
    end
    local _, source_host = jid.split(source)
    if source_host ~= module.host then
        return
    end

    local avatar = avatar_from(custom_path, source)
    if not avatar then
        return
    end

    local update = stanza:get_child("x", "vcard-temp:x:update")
    if not update then
        update = st.stanza("x", { xmlns = "vcard-temp:x:update" })
        stanza:add_child(update)
    end
    local photo = update:get_child("photo")
    if photo then
        photo[1] = avatar.hash
    else
        update:text_tag("photo", avatar.hash)
    end
end

local function send_avatar(event, avatar)
    local query = event.stanza.tags[1]
    local item = query:get_child("items")
    local node = item.attr.node
    local payload = node == nodes.data and avatar.data or avatar.metadata
    event.origin.send(st.reply(event.stanza)
        :tag("pubsub", { xmlns = "http://jabber.org/protocol/pubsub" })
            :tag("items", { node = node })
                :add_child(payload))
    return true
end

module:hook("iq/bare/http://jabber.org/protocol/pubsub:pubsub", function (event)
    if event.stanza.attr.type ~= "get" then
        return
    end

    local query = event.stanza.tags[1]
    local items = query and query:get_child("items")
    local node = items and items.attr.node
    if not node or (node ~= nodes.data and node ~= nodes.metadata) then
        return
    end

    local target = event.stanza.attr.to
    if not target then
        return
    end

    target = jid.bare(target)
    local _, target_host = jid.split(target)
    if module:get_host_type() ~= "component" or target_host ~= module.host then
        return
    end
    local custom = avatar_from(custom_path, target)
    if custom then
        return send_avatar(event, custom)
    end

end, 1)

module:hook("iq/bare/http://jabber.org/protocol/pubsub:pubsub", function (event)
    if event.stanza.attr.type ~= "get" then
        return
    end

    local query = event.stanza.tags[1]
    local items = query and query:get_child("items")
    local node = items and items.attr.node
    if not node or (node ~= nodes.data and node ~= nodes.metadata) then
        return
    end

    local target = event.stanza.attr.to
    if not target then
        return
    end
    target = jid.bare(target)
    local _, target_host = jid.split(target)
    if module:get_host_type() ~= "component" or target_host ~= module.host then
        return
    end

    local default = avatar_from(default_path, target)
    if default then
        return send_avatar(event, default)
    end
end, -1)

module:hook("pre-presence/full", rewrite_avatar_update, 1000)
module:hook("pre-presence/bare", rewrite_avatar_update, 1000)
module:hook("pre-presence/host", rewrite_avatar_update, 1000)

module:hook("iq-get/bare/vcard-temp:vCard", function (event)
    local target = event.stanza.attr.to
    if not target then
        return
    end
    target = jid.bare(target)
    local _, target_host = jid.split(target)
    if module:get_host_type() ~= "component" or target_host ~= module.host then
        return
    end
    local avatar = avatar_from(custom_path, target)
    if avatar then
        event.origin.send(st.reply(event.stanza)
            :tag("vCard", { xmlns = "vcard-temp" })
                :tag("PHOTO")
                    :text_tag("TYPE", avatar.type)
                    :text_tag("BINVAL", base64.encode(avatar.raw))
                :up()
            :up()
        )
        return true
    end
end, 1)

module:hook("iq-get/bare/vcard-temp:vCard", function (event)
    local target = event.stanza.attr.to
    if not target then
        return
    end
    target = jid.bare(target)
    local _, target_host = jid.split(target)
    if module:get_host_type() ~= "component" or target_host ~= module.host then
        return
    end
    local avatar = avatar_from(default_path, target)
    if not avatar then
        return
    end
    event.origin.send(st.reply(event.stanza)
        :tag("vCard", { xmlns = "vcard-temp" })
            :tag("PHOTO")
                :text_tag("TYPE", avatar.type)
                :text_tag("BINVAL", base64.encode(avatar.raw))
            :up()
        :up()
    )
    return true
end, -1)