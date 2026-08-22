local st = require "util.stanza"
local http = require "util.http"
local json = require "util.json"

-- Intercepta las lecturas del roster y completa los contactos con datos de un
-- servicio HTTP. Si el servicio no está disponible, devuelve el roster normal.
local roster_xmlns = "jabber:iq:roster"
local endpoint = module:get_option_string("external_roster_url")
local token = module:get_option_string("external_roster_token")

module:add_feature(roster_xmlns)

local function url_encode(value)
    -- Escapa el usuario y el host antes de añadirlos a la cadena de consulta.
    return tostring(value):gsub("([^%w%-_%.~])", function(character)
        return string.format("%%%02X", string.byte(character))
    end)
end

local function local_roster_reply(session, stanza)
    -- Reproduce la respuesta GET de mod_roster para que la consulta externa sea
    -- asíncrona, sin retrasar ni reinyectar el IQ original.
    local reply = st.reply(stanza)
    local query = stanza.tags[1]
    local client_version = tonumber(query and query.attr.ver)
    local roster_meta = session.roster[false] or {}
    local server_version = tonumber(roster_meta.version or 1)

    -- Con versionado del roster, un cliente actualizado solo recibe un resultado
    -- vacío con la versión actual, igual que en mod_roster.
    if not (client_version and client_version == server_version) then
        reply:query(roster_xmlns)
        for contact_jid, item in pairs(session.roster) do
            if contact_jid then
                reply:tag("item", {
                    jid = contact_jid,
                    subscription = item.subscription,
                    approved = item.approved,
                    ask = item.ask,
                    name = item.name,
                })
                for group in pairs(item.groups or {}) do
                    reply:text_tag("group", group)
                end
                reply:up()
            end
        end
        reply.tags[1].attr.ver = tostring(server_version)
    end

    return reply
end

local function apply_external_data(session, data)
    -- Acepta tanto un mapa directo de JID como el formato { contacts = ... }.
    local contacts = data
    if type(data) == "table" and type(data.contacts) == "table" then
        contacts = data.contacts
    end
    if type(contacts) == "table" and #contacts > 0 then
        -- Convierte el formato de lista usado por tools/roster.py en un mapa de JID.
        local by_jid = {}
        for _, contact in ipairs(contacts) do
            if type(contact) == "table" and type(contact.jid) == "string" then
                by_jid[contact.jid] = contact
            end
        end
        contacts = by_jid
    end
    if type(contacts) ~= "table" then
        return false, "response must be an object or contain a contacts object"
    end

    local applied = 0
    for contact_jid, values in pairs(contacts) do
        if type(contact_jid) == "string" and type(values) == "table" then
            local item = session.roster[contact_jid]
            if item then
                -- Solo completa entradas existentes; el servicio externo no puede
                -- añadir, eliminar ni modificar el estado de suscripción.
                if type(values.name) == "string" then
                    item.name = values.name
                end
                if type(values.groups) == "table" then
                    local groups = {}
                    for _, group in ipairs(values.groups) do
                        if type(group) == "string" and group ~= "" then
                            groups[group] = true
                        end
                    end
                    item.groups = groups
                end
                applied = applied + 1
            end
        end
    end
    return true, applied
end

local function request_roster(session, stanza)
    local username = session.username or ""
    local host = session.host or module.host
    local url = endpoint .. "?user=" .. url_encode(username) .. "&host=" .. url_encode(host)
    local headers = { ["Accept"] = "application/json" }
    if token then
        -- El token es opcional y se envía como credencial Bearer estándar.
        headers["Authorization"] = "Bearer " .. token
    end

    local function finish(reply)
        session.send(reply)
        session.interested = true
    end

    http.request(url, { headers = headers }, function(body, code)
        if code == 200 then
            local data, decode_error = json.decode(body)
            if data then
                local ok, result = apply_external_data(session, data)
                if ok then
                    module:log("debug", "Applied external roster data for %s (%s contacts)", username, result)
                    finish(local_roster_reply(session, stanza))
                    return
                end
                module:log("warn", "Invalid external roster data for %s: %s", username, result)
            else
                module:log("warn", "Could not decode external roster data for %s: %s", username, decode_error or "unknown error")
            end
        else
            module:log("warn", "External roster request for %s failed with HTTP status %s", username, code or "unknown")
        end
        -- Cualquier error termina usando el roster interno como alternativa.
        finish(local_roster_reply(session, stanza))
    end)
end

module:hook("iq/self/" .. roster_xmlns .. ":query", function(event)
    -- La prioridad 1000 se ejecuta antes que mod_roster. Solo se interceptan
    -- GET; los cambios del roster (SET) siguen gestionados por Prosody.
    if not endpoint or event.stanza.attr.type ~= "get" then
        return
    end
    request_roster(event.origin, event.stanza)
    return true
end, 1000)