// content.js - lyssnar på meddelanden från injected.js och hanterar kungörelsesidor/enskild

// 1) Injicera injected.js i sidans kontext så vi kan hooka riktiga fetch/XHR
(function () {
  try {
    const s = document.createElement("script");
    s.src = chrome.runtime.getURL("injected.js");
    s.type = "text/javascript";
    s.async = false;
    (document.head || document.documentElement).appendChild(s);
    s.remove();
  } catch (e) {
    console.debug("[PoIT] Failed to inject page script:", e);
  }

  // 2) Brygga meddelanden från sidan → extension (API-respons-data)
  window.addEventListener("message", function (ev) {
    try {
      if (ev.source !== window) return;
      const msg = ev.data;
      if (!msg || msg.__kv !== true) return;

      if (msg.type === "KV_SAVE_JSON" && msg.payload) {
        chrome.runtime.sendMessage(
          {
            type: "KV_SAVE_JSON",
            payload: msg.payload,
          },
          function () {}
        );
      }
    } catch (e) {
      console.debug("[PoIT] content message bridge error:", e);
    }
  });

  // Hjälpfunktioner för att kontrollera sidtyp (uppdateras dynamiskt)
  function isKungorelsePage() {
    const url = window.location.href;
    // MUST be /kungorelse/ and MUST NOT contain /enskild/
    if (url.toLowerCase().includes("/enskild/")) return false;
    return /^https:\/\/poit\.bolagsverket\.se\/poit-app\/kungorelse\/K[^/]+/i.test(
      url
    );
  }

  function isEnskildPage() {
    return /\/enskild\//i.test(window.location.href);
  }

  function urlContainsEnskild(url) {
    // Helper to check ANY url for "enskild" - used as safety check
    return url && url.toLowerCase().includes("/enskild/");
  }

  const href = window.location.href;
  const IS_KUNGORELSE = isKungorelsePage();
  const IS_ENSKILD = isEnskildPage();

  // 3) Fånga innehåll på kungörelsesida och skicka till servern
  // VIKTIGT: Bättre logik från old_ext med duplicering-skydd och validering
  let capturedKungorelseIds = new Set();
  let pendingCaptures = new Set(); // Track captures that are waiting in timeout

  function extractKungorelseId() {
    const match = window.location.href.match(
      /(?:kungorelse|enskild)\/(K[\d\-]+)/
    );
    return match ? match[1] : null;
  }

  function captureKungorelseData() {
    // VIKTIGT: ALDRIG fånga enskild-sidor
    const currentUrl = window.location.href;
    if (urlContainsEnskild(currentUrl)) {
      console.log(
        "[PoIT] BLOCKED: URL contains 'enskild', not capturing:",
        currentUrl
      );
      return;
    }

    // Bara fånga faktiska kungörelse-sidor
    if (!isKungorelsePage() || isEnskildPage()) return;

    const kungorelseId = extractKungorelseId();
    if (!kungorelseId) return;

    // Undvik att fånga samma kungörelse flera gånger
    const normalizedId = kungorelseId.replace("/", "-");

    // Check BOTH already captured AND pending captures
    if (
      capturedKungorelseIds.has(normalizedId) ||
      pendingCaptures.has(normalizedId)
    ) {
      console.log("[PoIT] Skipping duplicate capture for:", normalizedId);
      return;
    }

    // Mark as pending IMMEDIATELY to prevent duplicate calls during timeout
    pendingCaptures.add(normalizedId);
    console.log("[PoIT] Queued capture for:", normalizedId);

    // Kontrollera att sidan faktiskt är en kungörelse-sida (inte bara en länk-sida)
    // Vänta längre för att säkerställa att navigationen är klar
    setTimeout(() => {
      // Dubbelkolla att vi fortfarande är på rätt sida
      const currentHref = window.location.href;
      const stillKungorelse =
        /^https:\/\/poit\.bolagsverket\.se\/poit-app\/kungorelse\/K[^/]+/i.test(
          currentHref
        );
      const stillEnskild =
        /^https:\/\/poit\.bolagsverket\.se\/poit-app\/enskild\//i.test(
          currentHref
        );

      if (!stillKungorelse || stillEnskild) {
        console.log("[PoIT] Page changed during wait, skipping capture");
        pendingCaptures.delete(normalizedId);
        return;
      }

      // Double-check not already captured (in case of race condition)
      if (capturedKungorelseIds.has(normalizedId)) {
        console.log(
          "[PoIT] Already captured (race condition prevented):",
          normalizedId
        );
        pendingCaptures.delete(normalizedId);
        return;
      }

      // Kontrollera att sidan har faktiskt innehåll (inte bara länkar)
      const textContent = document.body ? document.body.innerText : "";
      const mainContent = document.querySelector("main");

      // Om textContent är för kort eller saknar kungörelse-innehåll, hoppa över
      if (textContent.length < 500) {
        console.log(
          "[PoIT] Page content too short, likely not a real kungörelse page"
        );
        pendingCaptures.delete(normalizedId);
        return;
      }

      // Kontrollera att vi inte är på en mellansida med bara länkar
      const linkCount = document.querySelectorAll(
        'a[href*="/kungorelse/K"]'
      ).length;
      if (linkCount > 2 && textContent.length < 1000) {
        console.log(
          "[PoIT] Page appears to be a link page, not actual kungörelse content"
        );
        pendingCaptures.delete(normalizedId);
        return;
      }

      // FINAL SAFETY CHECK: Never send enskild URLs
      const urlToSend = window.location.href;
      if (urlContainsEnskild(urlToSend)) {
        console.log(
          "[PoIT] BLOCKED at final check: URL contains 'enskild':",
          urlToSend
        );
        pendingCaptures.delete(normalizedId);
        return;
      }

      console.log("[PoIT] Capturing kungörelse:", normalizedId);

      // Markera som fångad för att undvika duplicering
      capturedKungorelseIds.add(normalizedId);
      pendingCaptures.delete(normalizedId);

      const htmlContent = mainContent ? mainContent.innerHTML : "";

      // Skicka till background script - ONLY ONCE
      chrome.runtime.sendMessage(
        {
          type: "KV_SAVE_KUNGORELSE",
          payload: {
            url: urlToSend,
            kungorelseId: normalizedId,
            textContent: textContent,
            htmlContent: htmlContent,
            timestamp: new Date().toISOString(),
            title: document.title || "Kungörelse " + normalizedId,
          },
        },
        function () {}
      );
    }, 3000); // Ökad väntetid till 3 sekunder för att säkerställa att navigationen är klar
  }

  if (IS_KUNGORELSE || IS_ENSKILD) {
    // Initial check - vänta lite för att säkerställa att sidan är laddad
    setTimeout(() => {
      // Om vi är på en enskild-sida, hantera den först
      if (isEnskildPage()) {
        handleEnskildPage().then(() => {
          // Vänta efter klick innan vi försöker fånga data
          setTimeout(() => {
            const currentHref = window.location.href;
            const nowKungorelse =
              /^https:\/\/poit\.bolagsverket\.se\/poit-app\/kungorelse\/K[^/]+/i.test(
                currentHref
              );
            const nowEnskild =
              /^https:\/\/poit\.bolagsverket\.se\/poit-app\/enskild\//i.test(
                currentHref
              );
            if (nowKungorelse && !nowEnskild) {
              captureKungorelseData();
            }
          }, 2500);
        });
      } else if (isKungorelsePage()) {
        // Om vi redan är på en kungörelse-sida, fånga direkt
        captureKungorelseData();
      }
    }, 1000); // Vänta 1 sekund för att säkerställa att sidan är laddad

    // Monitor för URL-förändringar (SPA navigation)
    let lastUrl = window.location.href;
    setInterval(() => {
      const currentUrl = window.location.href;
      if (currentUrl !== lastUrl) {
        lastUrl = currentUrl;
        // Reset handled flag on navigation
        if (document.body) delete document.body.dataset.enskildHandled;

        // Uppdatera IS_KUNGORELSE och IS_ENSKILD baserat på ny URL
        const nowKungorelse =
          /^https:\/\/poit\.bolagsverket\.se\/poit-app\/kungorelse\/K[^/]+/i.test(
            currentUrl
          );
        const nowEnskild =
          /^https:\/\/poit\.bolagsverket\.se\/poit-app\/enskild\//i.test(
            currentUrl
          );

        // VIKTIGT: Hantera enskild-sidor först, vänta sedan innan vi fångar kungörelse-data
        if (nowEnskild) {
          handleEnskildPage().then(() => {
            // Vänta lite extra efter att ha klickat på länken innan vi försöker fånga data
            setTimeout(() => {
              captureKungorelseData();
            }, 2000);
          });
        } else if (nowKungorelse) {
          // Om vi redan är på en kungörelse-sida, fånga direkt
          captureKungorelseData();
        }
      }
    }, 500); // Kontrollera oftare för bättre responsivitet

    // Monitor DOM-förändringar för dynamiskt innehåll
    const observer = new MutationObserver(() => {
      const currentHref = window.location.href;
      const nowEnskild =
        /^https:\/\/poit\.bolagsverket\.se\/poit-app\/enskild\//i.test(
          currentHref
        );
      if (nowEnskild) {
        handleEnskildPage();
      }
    });

    // Start observer när document.body är tillgänglig
    function startObserver() {
      if (document.body) {
        observer.observe(document.body, {
          childList: true,
          subtree: true,
        });
      } else {
        setTimeout(startObserver, 100);
      }
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", startObserver);
    } else {
      startObserver();
    }
  }

  // 4) På enskild-sida: försök automatiskt navigera vidare till kungörelsesidan
  // VIKTIGT: Bättre logik från old_ext för att hantera mellansidor
  async function handleEnskildPage() {
    if (!isEnskildPage()) return;
    if (document.body && document.body.dataset.enskildHandled === "true")
      return;

    console.log(
      "[PoIT] Detected enskild page, will auto-click to kungörelse..."
    );

    // Markera som hanterad för att undvika duplicering
    if (document.body) document.body.dataset.enskildHandled = "true";

    // Vänta lite för att simulera läsning (1-2 sekunder)
    await new Promise((resolve) =>
      setTimeout(resolve, 1000 + Math.random() * 1000)
    );

    // Hitta "Visa kungörelse" länken med bättre selectors
    const selectors = [
      'a[href*="/poit-app/kungorelse/K"][title="Visa kungörelse"]',
      'a.btn-link[href*="/kungorelse/K"]',
      'a[href*="/kungorelse/K"]',
    ];

    for (const selector of selectors) {
      const link = document.querySelector(selector);
      if (link) {
        console.log("[PoIT] Found kungörelse link, clicking...");

        // Simulera mänskligt klick med liten delay
        await new Promise((resolve) =>
          setTimeout(resolve, 200 + Math.random() * 300)
        );
        link.click();
        return true;
      }
    }
    return false;
  }

  if (IS_ENSKILD) {
    handleEnskildPage();
  }

  console.log("[PoIT Listener] content.js laddad på:", href);
})();
