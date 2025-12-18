(function () {
  // Hooks som körs i sidans egen kontext (inte i extensionens isolerade värld)

  const TARGET_HOST = "poit.bolagsverket.se";

  // Aktivera på alla PoIT-sidor (inte bara /sok och /kungorelse)
  const href = window.location.href;
  const PAGE_OK = href.startsWith("https://poit.bolagsverket.se/");

  if (!PAGE_OK) {
    return;
  }

  // Hjälpfunktion för att kontrollera om URL ska ignoreras (chrome://, file://, etc)
  function shouldIgnoreUrl(url) {
    if (!url || typeof url !== 'string') return false;
    const lowerUrl = url.toLowerCase();
    return lowerUrl.startsWith('chrome://') || 
           lowerUrl.startsWith('chrome-extension://') ||
           lowerUrl.startsWith('file://') ||
           lowerUrl.startsWith('moz-extension://') ||
           lowerUrl.startsWith('edge://') ||
           lowerUrl.startsWith('about:') ||
           lowerUrl.startsWith('data:');
  }

  function isTargetUrl(url) {
    // Ignorera chrome:// och andra interna URLs direkt
    if (shouldIgnoreUrl(url)) return false;
    
    try {
      const u = new URL(url, window.location.href);
      if (u.hostname !== TARGET_HOST) return false;
      const p = u.pathname;
      // T.ex: /poit/rest/sokKungorelse, /poit/rest/SokKunngorelse etc
      const re = /\/poit\/rest\/sok[a-z]*?kung[a-z]*/i;
      return re.test(p);
    } catch (e) {
      return false;
    }
  }

  function bridgeSave(payload) {
    try {
      window.postMessage(
        {
          __kv: true,
          type: "KV_SAVE_JSON",
          payload: payload
        },
        "*"
      );
    } catch (e) {
      console.debug("[PoIT] bridgeSave error:", e);
    }
  }

  // Hooka fetch
  try {
    const origFetch = window.fetch;
    if (typeof origFetch === "function") {
      window.fetch = function (...args) {
        let url = args[0];
        let options = args[1] || {};

        const requestUrl = typeof url === "string" ? url : (url && url.url) || "";
        
        // Ignorera chrome:// och andra interna URLs direkt
        if (shouldIgnoreUrl(requestUrl)) {
          return origFetch.apply(this, args);
        }
        
        const shouldCapture = isTargetUrl(requestUrl);

        return origFetch.apply(this, args).then((response) => {
          try {
            if (shouldCapture) {
              const cloned = response.clone();
              const ct = (cloned.headers && cloned.headers.get("content-type")) || "";

              if (ct && ct.toLowerCase().includes("application/json")) {
                cloned
                  .json()
                  .then((data) => {
                    bridgeSave({ url: requestUrl, data: data });
                  })
                  .catch(() => {
                    cloned
                      .text()
                      .then((txt) => {
                        bridgeSave({
                          url: requestUrl,
                          data: { raw_text: String(txt || "") }
                        });
                      })
                      .catch(() => {});
                  });
              } else {
                cloned
                  .text()
                  .then((txt) => {
                    bridgeSave({
                      url: requestUrl,
                      data: { raw_text: String(txt || "") }
                    });
                  })
                  .catch(() => {});
              }
            }
          } catch (e) {
            console.debug("[PoIT] fetch capture error:", e);
          }
          return response;
        });
      };
    }
  } catch (e) {
    console.debug("[PoIT] Failed to patch fetch:", e);
  }

  // Hooka XHR
  try {
    const XHR = window.XMLHttpRequest;
    if (XHR && XHR.prototype) {
      const origOpen = XHR.prototype.open;
      const origSend = XHR.prototype.send;

      XHR.prototype.open = function (method, url) {
        // Ignorera chrome:// och andra interna URLs direkt
        if (shouldIgnoreUrl(url)) {
          return origOpen.apply(this, arguments);
        }
        
        try {
          this.__kv_url = url;
        } catch (e) {}
        return origOpen.apply(this, arguments);
      };

      XHR.prototype.send = function (body) {
        try {
          this.addEventListener("loadend", function () {
            try {
              const url = this.__kv_url;
              if (!url || !isTargetUrl(url)) return;

              let data = null;
              const ctHeader = this.getResponseHeader && this.getResponseHeader("content-type");
              const ct = (ctHeader || "").toLowerCase();

              if (this.responseType === "" || this.responseType === "text") {
                const text = String(this.responseText || "");
                if (ct.includes("application/json")) {
                  try {
                    data = JSON.parse(text);
                  } catch (e) {
                    data = { raw_text: text };
                  }
                } else {
                  data = { raw_text: text };
                }
              } else if (this.responseType === "json") {
                data = this.response;
              }

              if (data != null) {
                bridgeSave({ url: url, data: data });
              }
            } catch (e) {
              console.debug("[PoIT] XHR capture error:", e);
            }
          });
        } catch (e) {}
        return origSend.apply(this, arguments);
      };
    }
  } catch (e) {
    console.debug("[PoIT] Failed to patch XHR:", e);
  }

})();
