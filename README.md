# Marstek by Diggit voor Home Assistant

Versie 0.1.18. Deze integratie stuurt commando’s via de lokale Marstek Open API over UDP. De Diggit-server hoeft hiervoor niet te draaien.

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
2. Voeg `/marstek_diggit/dashboard-0.1.18.js` toe als **JavaScript-module**. Gebruik je de kaart al met een `/local/`-URL, wijzig dan die bron naar de nieuwe URL.
3. Open een bewerkbaar dashboard, kies **Bewerken → Kaart toevoegen → Handmatig** en plak:

   ```yaml
   type: custom:marstek-diggit-card
   ```

4. Sla op. De kaart haalt de actuele modus en het laadniveau op als de firmware dat veld levert. De hoofding toont ook het actuele laad- of ontlaadvermogen aan de netzijde, in watt. De batterijstatus wordt om de 30 seconden vernieuwd zolang de pagina zichtbaar is. Met **Vernieuwen** kun je meteen opnieuw uitlezen.

Voor een eigen plek in de zijbalk kun je onder **Instellingen → Dashboards** een dashboard met de naam **Marstek** maken en daar de kaart toevoegen. Bij meerdere batterijen geef je per kaart ook `config_entry_id` mee.

De tijdslotvelden zijn een formulier om een programma te schrijven. Controleer bestaande programma’s in de Marstek-app voordat je een bezet slot overschrijft. De kaart gebruikt dezelfde acties als hierboven.

## Kaart voor elektriciteitstarieven

Werk **Marstek by Diggit** via HACS bij naar 0.1.18 en herstart Home Assistant. Bewerk bij **Instellingen → Dashboards → ⋮ → Bronnen** de bestaande Marstek-bron naar `/marstek_diggit/dashboard-0.1.18.js` en herlaad het dashboard. Voeg **Marstek elektriciteitstarieven** toe in de kaartkiezer of voeg handmatig toe:

```yaml
type: custom:marstek-diggit-tariffs-card
```

Vul de drie prijzen in €/kWh in en geef per tarief de tijdvakken voor werkdagen en het weekend op. Een voorbeeld met twee piekperiodes is `07:00-11:00, 17:00-22:00`. Een blok zoals `22:00-06:00` loopt door op de volgende kalenderdag, ook van vrijdag op zaterdag. Gebruik `24:00` als eindtijd als een blok precies om middernacht eindigt. Overlappende blokken worden geweigerd. Lege uren blijven zonder tarief.

**Tarieven opslaan** bewaart één schema per Home Assistant-installatie. De kaart bewaart prijzen en tijden. Automatische batterijaansturing en kostenberekening zijn geen onderdeel van deze kaart.

Vanaf 0.1.7 tonen beide kaarten een compact overzicht. Open **Tarieven en tijdvakken wijzigen** of **Tijdslot wijzigen** om het formulier te tonen. De programmatie toont vanaf deze versie slotwijzigingen die via de integratie zijn bevestigd. Eerder ingestelde tijdsloten en wijzigingen via de Marstek-app raadpleeg je in de Marstek-app.

De kleurmarkering **Nu** volgt het geldende tarief in de tijdzone van Home Assistant. **Nu gepland** geeft aan dat een opgeslagen en ingeschakeld slot in zijn tijdvak zit. De actuele batterijmodus staat bovenaan de kaart.

## Energy Planner voor twee batterijen

De Energy Planner gebruikt jouw metingen en tarieven. Hij staat standaard uit en start na inschakelen in simulatie zolang die instelling aangevinkt blijft. Tijdens de simulatie kan de bestaande tijdslotprogrammatie blijven draaien.

1. Voeg in de dashboardeditor **Marstek Energy Planner** toe met dezelfde JavaScript-bron als de batterij- en tariefkaart.

   ```yaml
   type: custom:marstek-diggit-energy-planner-card
   ```

2. Kies onder **Instellingen** beide Marstek-integratie-items, het totale P1-netvermogen en het actuele Smappee-laadvermogen. Stel waar beschikbaar ook SMA-zonneproductie, zonnevoorspelling en de importenergie van het lopende meetkwartier in. Schakel de planner in en sla op.
3. Controleer de gemeten batterijmodus, het gesimuleerde laadvoorstel, het kwartierbudget en de 24-uursplanning. De kaart leest de laatst berekende toestand via `marstek_diggit.get_energy_plan`. Beheerders kunnen instellingen ook via `marstek_diggit.configure_energy_controller` opslaan.

De P1-sensor moet positief zijn bij afname, negatief bij injectie en W of kW rapporteren. Gebruik voor Smappee bij voorkeur effectief laadvermogen in W of kW. Vanaf 1.000 W geldt de auto als actief. Stop wordt bevestigd na 10 seconden op ten hoogste 700 W. Een binaire laadsensor kan de auto blokkeren, maar is onvoldoende om EV-energie van het huishoudelijke verbruik af te trekken. Voor geldige leerdagen zijn Smappee-laadvermogen en zonneproductie in W of kW nodig.

Voor een open meetkwartier accepteert de planner een importenergiesensor in Wh of kWh met het attribuut `quarter_start` als ISO 8601-tijdstip met tijdzone. De sensor moet bij iedere officiële kwartiergrens opnieuw beginnen. Zonder deze sensor integreert de planner positieve P1-afname per kwartier en labelt de uitkomst als schatting. Bij onvoldoende dekking rekent de schatting voor die ontbrekende periode met de ingestelde grens. Het is geen garantie dat een gemiste piek onder die grens lag.

De optionele zonnevoorspellingssensor kan een attribuut `watts_by_hour` leveren. Gebruik ISO 8601-sleutels met tijdzone en verwachte gemiddelde W per uur. Voorbeeld:

```yaml
watts_by_hour:
  "2026-11-18T12:00:00+01:00": 620
  "2026-11-18T13:00:00+01:00": 390
```

Bij ontbrekende voorspellingen projecteert de planner zonder toekomstige PV-bijdrage en toont hij de zonnevoorspelling als onbekend. Buiten het verwachte avondverbruik gebruikt hij de bij de strategie-evaluatie geschatte huislast. Het huidige autolaadsignaal telt mee in het eerste strategie-interval, zonder voorspelling van toekomstige laadsessies.

### Beslissingen en meetgegevens

- **Superdal** streeft naar 100%. De planning toont een voorspeld tekort aan het einde van het blok. **Dal** streeft eerst ook naar 100%. **Piek** kan als voorstel Auto gebruiken wanneer beide batterijen boven minimum-SoC zitten en de administratieve laadherkomst dit toestaat.
- De planner gebruikt tariefprijzen en tijdvakken uit de bestaande tariefkaart. De kwartierbewaking verwerkt P1-updates, met een klokcontrole voor de start van een nieuw tijdvak en verouderde sensorwaarden. De strategie en de 24-uursprojectie worden standaard om de tien minuten en bij een tariefwijziging herberekend.
- Bij autoladen of in piek is gepland laden beperkt tot gemeten zonneoverschot. De planner stelt laadvermogen pas voor wanneer beide batterijen bevestigd zijn en geen batterij meetbaar ontlaadt. Als Auto toegestaan is, blijft de realtime regeling bij Marstek en CT003. De individuele SoC-trajecten in de projectie zijn schattingen.
- De energiebalans registreert per batterij superdal-, dal- en piekenergie, zonne-energie en onbekende energie. De berekening combineert SoC, de batterijzijdige Wh-tellers uit `ES.GetStatus`, P1 en PV. Ze rekent met 90% laad- en 90% ontlaadefficiëntie. Een positief P1-signaal zonder PV of een negatief P1-signaal met PV kan bij overeenstemmende batterijtellers laadherkomst onderbouwen. Gemengde of gemiste intervallen blijven onzeker. Onzekere energie, gewijzigde prijzen of een onderbreking kunnen ontlading blokkeren. De planner trekt bij dalende SoC proportioneel uit de administratieve bakken, omdat firmware geen laadherkomst selecteert.
- Het leerproces gebruikt minimaal 30 geldige meetdagen en vervolgens minimaal 14 geldige schaduwdagen. De schaduwmodus toont voorspelling en gemeten avondverbruik, terwijl het laadvoorstel op 100% blijft. De instelling **Lerende doel-SoC toestaan** kan pas na beide fases een lager simulatievoorstel geven voor dal. Superdal behoudt een doel van 100%. De recentste vergelijkbare dagen wegen zwaarder. Standaard is de extra marge 15%.

### Actieve regeling op V151

De standaardinstelling is simulatie. De actieve stand is geschikt voor twee bevestigde Venus E 3.0-batterijen op firmware V151. De planner houdt de tweede batterij aantoonbaar stil voordat hij de andere laat laden. Hij leest P1 en de laadpaal opnieuw vóór de laadopdracht. Iedere laadopdracht duurt maximaal 60 seconden. De planner vernieuwt zo nodig de actieve opdracht vóór de afloop en plant geen herstel naar Auto in.

De opstellingstest bevestigde op beide batterijen dat een rechtstreekse opdracht van 0 W na afloop in Passive op 0 W bleef. Op de woonkamerbatterij stopte ook een laadopdracht van 300 W na 60 seconden zelfstandig op Passive 0 W. De test liet Home Assistant online en sloeg zijn automatische herstelopdracht over. Een werkelijke netwerkonderbreking en herstart van de batterijen vragen nog validatie.

Vanaf 0.1.18 schakelt de actieve planner tijdens piek over op SelfConsumption zodra de Smappee-sensor bevestigt dat de auto niet laadt. Energieherkomst blijft zichtbaar als diagnostiek. Bij een actieve of onbetrouwbare laadpaalmeting schakelt hij over naar Passive 0 W, of gebruikt hij gemeten zonneoverschot zonder te ontladen. Als Home Assistant de verbinding verliest terwijl een batterij al in Auto staat, kan hij de batterij geen ontlaadstop bezorgen. De [Marstek Local Open API](https://static-eu.marstekcloud.com/ems/resource/agreement/MarstekDeviceOpenApi.pdf) beschrijft geen begrensde Auto-opdracht.

Schakel andere automatiseringen en tijdsloten voor beide batterijen eerst uit wanneer je bewust overstapt op de actieve regeling. Laat eerdere Passive-opdrachten aflopen. Zet daarna op de kaart **Planner inschakelen** aan en vink **Simulatiemodus** uit. De actieve planner reserveert beide batterij-items voor eigen opdrachten via de integratie. Bij uitschakelen zet de planner de batterijen eerst op Passive 0 W. Zet ze daarna desgewenst zelf terug op Auto en schakel je eerdere automatisering weer in.

De automatische tests gebruiken nagebootste batterijantwoorden en geen netwerk- of batterijcommando's.

```sh
python3 -m unittest discover -s tests -v
```
