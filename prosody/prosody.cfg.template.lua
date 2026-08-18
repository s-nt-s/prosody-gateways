pidfile = "/var/run/prosody/prosody.pid"
data_path = "/var/lib/prosody"
plugin_paths = { "/usr/lib/prosody/modules", "/usr/local/share/lua/5.1" }

s2s_secure_auth = false

allow_registration = false
c2s_require_encryption = true
s2s_secure_auth = false

c2s_ports = { 5222 }
--s2s_ports = { 5269 }
http_ports = { 80, 5280 }
https_ports = { 443, 5281 }
component_ports = { 5347 }
component_interfaces = { "*" }


modules_enabled = {
  "roster"; "saslauth"; "tls"; "smacks"; "dialback";
  "disco"; "version"; "uptime";
  "ping"; "register"; "admin_adhoc";
  "carbons"; "offline";
  "privilege";
  "http_file_share";
  "admin_shell";
  "pep";
  --"bosh"; "websocket";
  "reload_components";
}

local _privileges = {
  roster = "both";       -- for adding/removing contacts from the users' rosters
  message = "outgoing";  -- for reflecting messages sent by the user themselve from official Telegram apps
  presence = "managed_entity";
  iq = {
    ["http://jabber.org/protocol/pubsub"] = "both";      -- for PEP Bookmarks
    ["http://jabber.org/protocol/pubsub#owner"] = "set"; -- for Message Display Synchronization
    ["urn:xmpp:http:upload:0"] = "both";                  -- for HTTP Upload on behalf of users
  }
};

local _http_file_share_access = {
  "{{XMPP_DOMAIN}}";
  "upload.{{XMPP_DOMAIN}}";
  "{{TELEGRAM_COMPONENT_JID}}";
  "{{WHATSAPP_COMPONENT_JID}}";
  "{{STEAM_COMPONENT_JID}}";
  "{{GOOGLE_COMPONENT_JID}}";
}

Component "pubsub.{{XMPP_DOMAIN}}" "pubsub"

Component "upload.{{XMPP_DOMAIN}}" "http_file_share"
  -- allow slidgram to use the upload component
  -- point generated upload URLs to the public host that actually serves the file share endpoint
  http_external_url = "https://{{XMPP_DOMAIN}}"
  http_file_share_access = _http_file_share_access

VirtualHost "{{XMPP_DOMAIN}}"
  ssl = {
    key = "/etc/prosody/certs/{{XMPP_DOMAIN}}.key";
    certificate = "/etc/prosody/certs/{{XMPP_DOMAIN}}.crt";
  };
  modules_enabled = { "privilege", "pep", "carbons", "offline" }
  pubsub_component = "pubsub.{{XMPP_DOMAIN}}"
  privileged_entities = {
    ["{{TELEGRAM_COMPONENT_JID}}"] = _privileges;
    ["{{WHATSAPP_COMPONENT_JID}}"] = _privileges;
    ["{{STEAM_COMPONENT_JID}}"] = _privileges;
    ["{{GOOGLE_COMPONENT_JID}}"] = _privileges;
  }

Component "{{TELEGRAM_COMPONENT_JID}}"
  component_secret = "{{SLIDGE_COMPONENT_SECRET}}"
  modules_enabled = {"privilege"}
  http_file_share_expires_after = 86400   -- 1 día
  http_file_share_access = _http_file_share_access

Component "{{WHATSAPP_COMPONENT_JID}}"
  component_secret = "{{SLIDGE_COMPONENT_SECRET}}"
  modules_enabled = {"privilege"}
  http_file_share_expires_after = 86400   -- 1 día
  http_file_share_access = _http_file_share_access

Component "{{STEAM_COMPONENT_JID}}"
  component_secret = "{{SLIDGE_COMPONENT_SECRET}}"
  modules_enabled = {"privilege"}
  http_file_share_expires_after = 86400   -- 1 día
  http_file_share_access = _http_file_share_access

Component "{{GOOGLE_COMPONENT_JID}}"
  component_secret = "{{SLIDGE_COMPONENT_SECRET}}"
  modules_enabled = {"register", "privilege"}
  http_file_share_expires_after = 86400   -- 1 día
  http_file_share_access = _http_file_share_access

admins = { "{{XMPP_ADMIN}}" }