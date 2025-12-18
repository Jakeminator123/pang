# SNI-baserade branscher (B2B-segment) – divisionsnivå (SNI 2007)

Den här filen listar **branscher/segment** och tillhörande **SNI-divisioner (tvåsiffriga koder, 01–99)** enligt SNI 2007.
Syfte: ge en enkel, stabil mappning att använda i segmentering/kategorisering.  
_Note_: SNI 2025 lanseras i slutet av 2025; divisionerna (01–99) är i stort sett beständiga, men kontrollera förändringar innan migrering.

**Senast uppdaterad:** 2025-10-21

---

```yaml
version: "SNI 2007"
segments:
  Jordbruk, skogsbruk & fiske:
    sni_divisioner: [ "01", "02", "03" ]

  Gruvor & utvinning:
    sni_divisioner: [ "05", "06", "07", "08", "09" ]

  Tillverkning – livsmedel & tobak:
    sni_divisioner: [ "10", "11", "12" ]

  Tillverkning – textil, kläder & läder:
    sni_divisioner: [ "13", "14", "15" ]

  Tillverkning – trä, papper & massa:
    sni_divisioner: [ "16", "17" ]

  Tillverkning – tryck:
    sni_divisioner: [ "18" ]

  Tillverkning – petroleum:
    sni_divisioner: [ "19" ]

  Tillverkning – kemi & läkemedel:
    sni_divisioner: [ "20", "21" ]

  Tillverkning – plast & gummi:
    sni_divisioner: [ "22" ]

  Tillverkning – mineraliska produkter:
    sni_divisioner: [ "23" ]

  Tillverkning – metall & metallvaror:
    sni_divisioner: [ "24", "25" ]

  Tillverkning – el & elektronik:
    sni_divisioner: [ "26", "27" ]

  Tillverkning – maskiner:
    sni_divisioner: [ "28" ]

  Tillverkning – fordon & transportmedel:
    sni_divisioner: [ "29", "30" ]

  Tillverkning – möbler, reparation & övrigt:
    sni_divisioner: [ "31", "32", "33" ]

  Energi & el (el-, gas-, värme- och kylförsörjning):
    sni_divisioner: [ "35" ]

  Vatten, avlopp, avfall & sanering:
    sni_divisioner: [ "36", "37", "38", "39" ]

  Bygg & anläggning:
    sni_divisioner: [ "41", "42", "43" ]

  Motorhandel & verkstad:
    sni_divisioner: [ "45" ]

  Partihandel (B2B):
    sni_divisioner: [ "46" ]

  Detaljhandel:
    sni_divisioner: [ "47" ]

  Transport & magasinering:
    sni_divisioner: [ "49", "50", "51", "52" ]

  Post & kurir:
    sni_divisioner: [ "53" ]

  Hotell, restaurang & catering:
    sni_divisioner: [ "55", "56" ]

  Media, förlag & underhållning:
    sni_divisioner: [ "58", "59", "60" ]

  Telekom:
    sni_divisioner: [ "61" ]

  IT – programvara & konsult:
    sni_divisioner: [ "62" ]

  IT – data/hosting/portaler:
    sni_divisioner: [ "63" ]

  Bank & finans:
    sni_divisioner: [ "64" ]

  Försäkring & finansiella stödtjänster:
    sni_divisioner: [ "65", "66" ]

  Fastigheter:
    sni_divisioner: [ "68" ]

  Juridik & redovisning:
    sni_divisioner: [ "69" ]

  Företagsledning/managementkonsult:
    sni_divisioner: [ "70" ]

  Tekniska konsulter & arkitekter:
    sni_divisioner: [ "71" ]

  Forskning & utveckling:
    sni_divisioner: [ "72" ]

  Reklam/PR/marknadsföring:
    sni_divisioner: [ "73" ]

  Professionella tjänster – övrigt:
    sni_divisioner: [ "74", "75" ]

  Uthyrning & leasing:
    sni_divisioner: [ "77" ]

  Bemanning & personaluthyrning:
    sni_divisioner: [ "78" ]

  Resebyrå & researrangör:
    sni_divisioner: [ "79" ]

  Bevakning & säkerhet:
    sni_divisioner: [ "80" ]

  Städ, trädgård & facility management:
    sni_divisioner: [ "81" ]

  Övriga företagstjänster:
    sni_divisioner: [ "82" ]

  Offentlig förvaltning (offentlig sektor):
    sni_divisioner: [ "84" ]

  Utbildning:
    sni_divisioner: [ "85" ]

  Hälso- och sjukvård; vård & omsorg:
    sni_divisioner: [ "86", "87", "88" ]

  Kultur, nöje & fritid:
    sni_divisioner: [ "90", "91", "92", "93" ]

  Organisationer, reparation & personliga tjänster:
    sni_divisioner: [ "94", "95", "96" ]

  Hushåll & internationella organisationer:
    sni_divisioner: [ "97", "98", "99" ]
```

---

### Noteringar
- **SNI-divisioner** är de två första siffrorna i SNI-koden (t.ex. *62.020* → division **62**).
- Denna mappning täcker i princip alla vanliga B2B-branscher och kan användas för att
  - mappa från SNI-koder → segment,
  - eller som mål-kategorier när SNI saknas (via nyckelordsfallback i din kod).
