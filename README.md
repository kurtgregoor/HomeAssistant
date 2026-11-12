# Marstek by Diggit voor Home Assistant

Versie 0.1.1. Deze integratie stuurt commando’s via de lokale Marstek Open API over UDP. De Diggit-server hoeft hiervoor niet te draaien.

## Installatie

1. Zet de lokale Open API aan in de Marstek-app. Noteer het IP-adres en de UDP-poort van de batterij. De standaardpoort is 30000.
2. Kopieer de volledige map `custom_components/marstek_diggit` naar `/config/custom_components/` op je Home Assistant-installatie.
3. Herstart Home Assistant. Kies **Instellingen → Apparaten & diensten → Integratie toevoegen → Marstek by Diggit** en vul het adres en de poort in. De installatie probeert eerst de batterijmodus te lezen.
4. Open **Ontwikkelaarstools → Acties** en voer **Lees batterijstatus** uit. De actie geeft het antwoord op `ES.GetMode` terug. Gebruik de andere acties vanuit hetzelfde scherm of in scripts en automatiseringen.

## Modi en tijdsloten

| Actie | Gebruik |
| --- | --- |
| `marstek_diggit.set_mode` | Activeer Auto, AI of UPS. |
| `marstek_diggit.set_passive` | Activeer Passive met vermogen in watt en een duur van 60 tot 86400 seconden. Negatief laadt en positief ontlaadt. |
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

Elke slotwijziging stuurt `ES.SetMode` met `manual_cfg`, inclusief slotnummer, tijden, weekmasker, vermogen en aan/uit. Daardoor kan de batterij kort in Manual gaan. Met `activate_manual: false` probeert de integratie de eerdere modus Auto, AI of UPS na 1,2 seconde terug te zetten. Manual blijft actief als de batterij al in Manual stond. Vanuit Passive of een onbekende modus vereist een slotwijziging `activate_manual: true`, omdat de eerdere toestand dan niet betrouwbaar hersteld kan worden.

Diggit activeert Manual los van een programma door een uitgeschakeld slot 9 mee te sturen. Deze integratie laat je bij het activeren zelf het slot kiezen, zodat slot 9 beschikbaar blijft. De integratie leest geen bestaande slotprogramma’s terug. Controleer bij een time-out de modus en het slot in de Marstek-app voordat je de actie opnieuw uitvoert.

Bij meerdere geconfigureerde batterijen selecteer je de batterij in het veld **Batterij**. In YAML heet dat veld `config_entry_id`.

De UDP-berichten zijn lokaal getest met een nagebootste batterij. Of jouw firmware alle modi accepteert en de tijdsloten uitvoert, moet op je Home Assistant-installatie en batterij worden bevestigd.
