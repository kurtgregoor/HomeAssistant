# Marstek by Diggit voor Home Assistant

Versie 0.1.12. Deze integratie stuurt commando’s via de lokale Marstek Open API over UDP. De Diggit-server hoeft hiervoor niet te draaien.

## Installatie via HACS

1. Open **HACS → ⋮ → Aangepaste repositories**.
2. Voeg `https://github.com/kurtgregoor/HomeAssistant` toe met categorie **Integratie**.
3. Open **Marstek by Diggit** in HACS, kies **Downloaden** en herstart Home Assistant. Als je de integratie eerder handmatig hebt geïnstalleerd, laat je bestaande batterijconfiguratie staan.
4. Gebruik HACS voor toekomstige downloads en updates. Als je de kaart al gebruikte, wijzig dan de dashboardbron zoals hieronder beschreven.

## Handmatige installatie

1. Zet de lokale Open API aan in de Marstek-app. Noteer het IP-adres en de UDP-poort van de batterij. De standaardpoort is 30000.
2. Kopieer de volledige map `custom_components/marstek_diggit` naar `/config/custom_components/` op je Home Assistant-installatie.
3. Herstart Home Assistant. Kies **Instellingen → Apparaten & diensten → Integratie toevoegen → Marstek by Diggit** en vul het adres en de poort in. De installatie probeert eerst de batterijmodus te lezen.
4. Open **Ontwikkelaarstools → Acties** en voer **Lees batterijstatus** uit. De actie geeft het antwoord op `ES.GetMode` terug. Gebruik de andere acties vanuit hetzelfde scherm of in scripts en automatiseringen.

## Modi en tijdsloten

| Actie | Gebruik |
| --- | --- |
| `marstek_diggit.set_mode` | Activeer Auto, AI of UPS. |
| `marstek_diggit.set_passive` | Activeer Passive met vermogen in watt en een duur van 60 tot 86400 seconden. Negatief laadt en positief ontlaadt. Home Assistant herstelt daarna de oorspronkelijke modus (Auto, AI of UPS). |
| `marstek_diggit.set_slot` | Programmeer slot 1 t/m 9. Gebruik `activate_manual: true` om Manual actief te laten. |
| `marstek_diggit.disable_slot` | Schrijf een uitgeschakeld slot. Dit vervangt de bestaande gegevens van dat slot. |
| `marstek_diggit.get_status` | Lees de huidige modus en de velden die je firmware daarbij retourneert. |

Voorbeeld om slot 1 op werkdagen van 01:00 tot 03:00 met 1000 W te laten laden en Manual te activeren:

```yaml
action: marstek_diggit.set_slot
data:
  slot: 1
  start_time: "01:00"
  end_time: "03:00"
  days: [mon, tue, wed, thu, fri]
  power: -1000
  enabled: true
  activate_manual: true
```

Standaard gebruikt het slot alle weekdagen en staat het aan. Je kunt ook expliciet `action: charge`, `discharge` of `auto` meegeven binnen `data`. Het vermogen voor Auto binnen een slot is `-1` in het protocol. Een vermogen van 0 zonder expliciete laadactie wordt, net als in Diggit, naar die waarde omgezet. Het bereik uit Diggit is −2500 tot +2500 W. Gebruik een vermogen dat je batterij ondersteunt.

De integratie behandelt `SelfConsumption` als `Auto` voor het uitlezen en herstellen van de modus. Een nieuwe Passive-opdracht tijdens een lopende opdracht vervangt de eindtijd en behoudt de oorspronkelijke modus. Home Assistant bewaart die eindtijd per batterij en haalt zo nodig een verlopen herstelactie in na een herstart. Een geslaagde moduswissel via de integratie annuleert het geplande herstel.

Elke slotwijziging stuurt `ES.SetMode` met `manual_cfg`, inclusief slotnummer, tijden, weekmasker, vermogen en aan/uit. Daardoor kan de batterij kort in Manual gaan. Met `activate_manual: false` probeert de integratie de eerdere modus Auto, AI of UPS na 1,2 seconde terug te zetten. Manual blijft actief als de batterij al in Manual stond. Vanuit Passive of een onbekende modus vereist een slotwijziging `activate_manual: true`, omdat de eerdere toestand dan niet betrouwbaar hersteld kan worden.

Diggit activeert Manual los van een programma door een uitgeschakeld slot 9 mee te sturen. Deze integratie laat je bij het activeren zelf het slot kiezen, zodat slot 9 beschikbaar blijft. De integratie leest geen bestaande slotprogramma’s terug. Controleer bij een time-out de modus en het slot in de Marstek-app voordat je de actie opnieuw uitvoert.

Bij meerdere geconfigureerde batterijen selecteer je de batterij in het veld **Batterij**. In YAML heet dat veld `config_entry_id`.

De UDP-berichten zijn lokaal getest met een nagebootste batterij. Of jouw firmware alle modi accepteert en de tijdsloten uitvoert, moet op je Home Assistant-installatie en batterij worden bevestigd.

## Firmware en Peak Shaving

Vanaf 0.1.2 geeft de actie `marstek_diggit.get_device_info` de modelcode en firmwareversie terug via `Marstek.GetDevice`. Open **Instellingen → Tools → Acties → Lees model en firmware**. De actie leest alleen gegevens uit.

Voor Venus D en Venus E 3.0 is de ingebouwde Peak Shaving toegevoegd in controlfirmware V150. Deze instelling heeft een eigen aan/uitstatus en een netlimiet in watt. Configureer ze in de Marstek-app. De [lokale UDP Open API](https://static-eu.marstekcloud.com/ems/resource/agreement/MarstekDeviceOpenApi.pdf) waarmee deze integratie werkt, documenteert geen commando voor die instelling. De [protocolanalyse voor Venus D en Venus E 3.0](https://github.com/iacavd/marstek-hm2mqtt/blob/main/docs/venus.md#28-configure-peak-shaving) beschrijft ze op het app-protocol. Een eventuele Home Assistant-regeling op basis van een netmeter en Passive is een eigen regeling.

## Marstek op je dashboard

Vanaf versie 0.1.3 levert de integratie zelf de JavaScript-kaart. De integratie moet geladen zijn voordat de bron beschikbaar is.

1. Ga naar **Instellingen → Dashboards → ⋮ → Bronnen**. Zet zo nodig **Geavanceerde modus** aan in je gebruikersprofiel.
2. Voeg `/marstek_diggit/dashboard-0.1.12.js` toe als **JavaScript-module**. Gebruik je de kaart al met een `/local/`-URL, wijzig dan die bron naar de nieuwe URL.
3. Open een bewerkbaar dashboard, kies **Bewerken → Kaart toevoegen → Handmatig** en plak:

   ```yaml
   type: custom:marstek-diggit-card
   ```

4. Sla op. De kaart haalt de actuele modus en het laadniveau op als de firmware dat veld levert. De hoofding toont ook het actuele laad- of ontlaadvermogen aan de netzijde, in watt. De batterijstatus wordt om de 30 seconden vernieuwd zolang de pagina zichtbaar is. Met **Vernieuwen** kun je meteen opnieuw uitlezen.

Voor een eigen plek in de zijbalk kun je onder **Instellingen → Dashboards** een dashboard met de naam **Marstek** maken en daar de kaart toevoegen. Bij meerdere batterijen geef je per kaart ook `config_entry_id` mee.

De tijdslotvelden zijn een formulier om een programma te schrijven. Controleer bestaande programma’s in de Marstek-app voordat je een bezet slot overschrijft. De kaart gebruikt dezelfde acties als hierboven.

## Kaart voor elektriciteitstarieven

Werk **Marstek by Diggit** via HACS bij naar 0.1.12 en herstart Home Assistant. Bewerk bij **Instellingen → Dashboards → ⋮ → Bronnen** de bestaande Marstek-bron naar `/marstek_diggit/dashboard-0.1.12.js` en herlaad het dashboard. Voeg **Marstek elektriciteitstarieven** toe in de kaartkiezer of voeg handmatig toe:

```yaml
type: custom:marstek-diggit-tariffs-card
```

Vul de drie prijzen in €/kWh in en geef per tarief de tijdvakken voor werkdagen en het weekend op. Een voorbeeld met twee piekperiodes is `07:00-11:00, 17:00-22:00`. Een blok zoals `22:00-06:00` loopt door op de volgende kalenderdag, ook van vrijdag op zaterdag. Gebruik `24:00` als eindtijd als een blok precies om middernacht eindigt. Overlappende blokken worden geweigerd. Lege uren blijven zonder tarief.

**Tarieven opslaan** bewaart één schema per Home Assistant-installatie. De kaart bewaart prijzen en tijden. Automatische batterijaansturing en kostenberekening zijn geen onderdeel van deze kaart.

Vanaf 0.1.7 tonen beide kaarten een compact overzicht. Open **Tarieven en tijdvakken wijzigen** of **Tijdslot wijzigen** om het formulier te tonen. De programmatie toont vanaf deze versie slotwijzigingen die via de integratie zijn bevestigd. Eerder ingestelde tijdsloten en wijzigingen via de Marstek-app raadpleeg je in de Marstek-app.

De kleurmarkering **Nu** volgt het geldende tarief in de tijdzone van Home Assistant. **Nu gepland** geeft aan dat een opgeslagen en ingeschakeld slot in zijn tijdvak zit. De actuele batterijmodus staat bovenaan de kaart.
