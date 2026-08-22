local st = require "util.stanza"
local http = require "util.http"
local json = require "util.json"
local base64 = require "util.encodings".base64
local jid = require "util.jid"

-- Sustituye la vCard de un contacto por una imagen obtenida del servicio
-- externo. Si no hay una imagen descargada, deja que Prosody responda normalmente.
local endpoint = module:get_option_string("external_roster_url")
local token = module:get_option_string("external_roster_token")
local refresh_period = module:get_option_number("external_avatar_refresh", 900)
local max_avatar_size = module:get_option_integer("external_avatar_max_size", 1024 * 1024, 1)
local contacts = {}
local avatars = {}

local function url_encode(value)
    return tostring(value):gsub("([^%w%-_%.~])", function(character)
        return string.format("%%%02X", string.byte(character))
    end)
end

local function request_headers()
    local headers = { ["Accept"] = "application/json" }
    if token then
        headers["Authorization"] = "Bearer " .. token
    end
    return headers
end

local function load_contacts(body)
    local data, decode_error = json.decode(body)
    if not data then
        return nil, decode_error or "JSON no válido"
    end

    local values = data
    if type(data) == "table" and type(data.contacts) == "table" then
        values = data.contacts
    end
    if type(values) ~= "table" then
        return nil, "la respuesta no contiene un mapa de contactos"
    end

    if #values > 0 then
        local by_jid = {}
        for _, contact in ipairs(values) do
            if type(contact) == "table" and type(contact.jid) == "string" then
                by_jid[contact.jid] = contact
            end
        end
        values = by_jid
    end

                local endpoint = module:get_option_string("external_avatar_url")
                local token = module:get_option_string("external_roster_token")
                local max_avatar_size = module:get_option_integer("external_avatar_max_size", 1024 * 1024, 1)
                local avatars = {}
                local pending = {}
            end
        end
    end
    return loaded
end

local function refresh_contacts()
    if not endpoint then
                    return endpoint:gsub("/$", "") .. "/" .. url_encode(contact_jid)
    end

    http.request(endpoint, { headers = request_headers() }, function(body, code)
        if code ~= 200 then
            module:log("warn", "No se pudieron actualizar los avatares: HTTP %s", code or "desconocido")
            return
        end

        local loaded, err = load_contacts(body)
        if not loaded then
            module:log("warn", "No se pudieron actualizar los avatares: %s", err)
            return
        end

        for contact_jid, avatar in pairs(avatars) do
            if not loaded[contact_jid] or loaded[contact_jid].url ~= avatar.url then
                avatars[contact_jid] = nil
            end
        end
        contacts = loaded
        module:log("debug", "Se han cargado URLs de avatar para contactos")
    end)
end

local function download_avatar(contact_jid, avatar_url)
    if avatars[contact_jid] or not avatar_url then
        return
    end

    http.request(avatar_url, {
        headers = { ["Accept"] = "image/*" },
    }, function(body, code, response)
        if code ~= 200 or type(body) ~= "string" then
            module:log("warn", "No se pudo descargar el avatar de %s: HTTP %s", contact_jid, code or "desconocido")
            return
        end
        if #body > max_avatar_size then
            module:log("warn", "Avatar demasiado grande para %s: %s bytes", contact_jid, #body)
            return
        end

        local content_type = response and response.headers and response.headers["content-type"]
        content_type = content_type and content_type:match("^[^;]+") or "image/jpeg"
        if not content_type:match("^image/") then
            module:log("warn", "El avatar de %s no es una imagen: %s", contact_jid, content_type)
            return
        end

        avatars[contact_jid] = {
            body = body,
            type = content_type,
            url = avatar_url,
        }
    end)
end

local function avatar_vcard(contact_jid, avatar)
    local vcard = st.stanza("vCard", { xmlns = "vcard-temp" })
        :tag("PHOTO")
            :text_tag("TYPE", avatar.type)
            :text_tag("BINVAL", base64.encode(avatar.body))
        :up()
    local contact = contacts[contact_jid]
        vcard:tag("FN"):text(contact.name):up()
    end
    return vcard
end

local function handle_vcard(event)
    local stanza = event.stanza
    if stanza.attr.type ~= "get" or not stanza.attr.to then
        return
    end

    local contact_jid = jid.bare(stanza.attr.to)
    local contact = contacts[contact_jid]
    local avatar_url = contact and contact.url
    local avatar = avatars[contact_jid]
    if not avatar then
        download_avatar(contact_jid, avatar_url)
        return
    end

    event.origin.send(st.reply(stanza):add_child(avatar_vcard(contact_jid, avatar)))
    return true
end

if endpoint then
    refresh_contacts()
    module:add_timer(refresh_period, function()
        refresh_contacts()
        return refresh_period
    end)
end

-- Se carga en los componentes para interceptar las vCards de sus contactos.
module:hook("iq/bare/vcard-temp:vCard", handle_vcard, 1000)
