const DOMAIN = "marstek_diggit";
const CARD_VERSION = "0.1.15";
const STATUS_REFRESH_MS = 30000;

function formatBatteryActivity(value) {
  if (typeof value !== "number" && (typeof value !== "string" || !value.trim())) {
    return "Onbekend";
  }
  const watts = Number(value);
  if (!Number.isFinite(watts)) return "Onbekend";
  if (watts === 0) return "In rust · 0 W";
  const direction = watts < 0 ? "Laden" : "Ontladen";
  return `${direction} · ${Math.abs(watts).toLocaleString("nl-BE")} W`;
}
const DAYS = [
  ["mon", "Ma"], ["tue", "Di"], ["wed", "Wo"], ["thu", "Do"],
  ["fri", "Vr"], ["sat", "Za"], ["sun", "Zo"],
];

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const ACTIVE_STYLE = `
  :is(#saved-slots li, #tariff-summary article)[data-current="true"] {
    border-color: var(--primary-color, #087e72);
    background: color-mix(in srgb, var(--primary-color, #087e72) 15%, var(--card-background-color, white));
  }
`;

function minutesOfDay(time) {
  const [hours, minutes] = time.split(":").map(Number);
  return hours * 60 + minutes;
}

function includesMoment(start, end, minute, today, yesterday) {
  const from = minutesOfDay(start);
  const to = minutesOfDay(end);
  return from <= to
    ? today && minute >= from && minute < to
    : (today && minute >= from) || (yesterday && minute < to);
}

class ScheduleCard extends HTMLElement {
  connectedCallback() {
    this.updateHighlight();
    this.highlightTimer = setInterval(() => this.updateHighlight(), 1000);
  }

  disconnectedCallback() {
    clearInterval(this.highlightTimer);
  }

  updateHighlight() {
    const zone = this._hass?.config?.time_zone;
    if (!zone || !this.highlightTiles?.length) return;
    if (this.highlightZone !== zone) {
      this.highlightClock = new Intl.DateTimeFormat("en-GB", {
        timeZone: zone, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
      });
      this.highlightZone = zone;
    }
    const parts = Object.fromEntries(
      this.highlightClock.formatToParts(new Date()).map(({ type, value }) => [type, value]),
    );
    const day = WEEKDAYS.indexOf(parts.weekday.toLowerCase());
    const previousDay = (day + 6) % 7;
    const minute = Number(parts.hour) * 60 + Number(parts.minute);
    for (const { tile, badge, matches } of this.highlightTiles) {
      const active = matches(day, previousDay, minute);
      tile.dataset.current = String(active);
      badge.hidden = !active;
    }
  }

  highlightTile(tile, label, matches) {
    const badge = document.createElement("strong");
    badge.textContent = ` · ${label}`;
    badge.hidden = true;
    tile.append(badge);
    this.highlightTiles.push({ tile, badge, matches });
  }
}

class MarstekDiggitCard extends ScheduleCard {
  static getStubConfig() {
    return { type: "custom:marstek-diggit-card" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          --accent: var(--primary-color, #087e72);
          --line: var(--divider-color, #dce5e3);
          --muted: var(--secondary-text-color, #52676a);
          color: var(--primary-text-color, #152c30);
          font: inherit;
          display: block;
        }
        * { box-sizing: border-box; }
        [hidden] { display: none !important; }
        ha-card { overflow: hidden; }
        header, section { padding: 20px; }
        header {
          background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 15%, transparent), transparent);
          display: grid; gap: 16px; border-bottom: 1px solid var(--line);
        }
        .between { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
        h2, h3, p { margin: 0; }
        h2 { font-size: 24px; font-weight: 700; letter-spacing: -.03em; }
        h3 { font-size: 16px; }
        .muted, label, legend { color: var(--muted); font-size: 13px; }
        output.soc { font-size: 38px; line-height: 1; font-weight: 700; letter-spacing: -.045em; }
        .meter { height: 7px; border-radius: 12px; background: var(--line); overflow: hidden; }
        .meter > div { height: 100%; width: 0; background: var(--accent); transition: width .25s; }
        .body { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); }
        section + section { border-inline-start: 1px solid var(--line); }
        #saved-slots { display: grid; gap: 6px; list-style: none; margin: 0; padding: 0; }
        #saved-slots li { border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; }
        ${ACTIVE_STYLE}
        form, fieldset { margin: 0; padding: 0; min-width: 0; border: 0; }
        form, .stack { display: grid; gap: 12px; }
        fieldset { display: grid; gap: 12px; }
        .row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
        .modes, .days, .buttons { display: flex; flex-wrap: wrap; gap: 8px; }
        label { display: grid; gap: 5px; min-width: 0; }
        button, select, input {
          font: inherit; color: inherit;
        }
        button, select, input:not([type="checkbox"]) {
          min-height: 42px; border-radius: 9px; padding: 8px 10px;
          border: 1px solid var(--line); background: var(--card-background-color, #fff);
          min-width: 0;
        }
        button { cursor: pointer; font-weight: 600; }
        button:disabled { opacity: .55; cursor: wait; }
        button[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }
        button.primary { background: var(--accent); color: var(--text-primary-color, #fff); border-color: transparent; }
        button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
        input[type="checkbox"] { accent-color: var(--accent); }
        .days label, label.check { display: flex; align-items: center; gap: 4px; min-height: 28px; }
        details { border-top: 1px solid var(--line); padding-top: 12px; }
        summary { cursor: pointer; margin-bottom: 10px; }
        .message { padding: 0 20px 16px; color: var(--muted); overflow-wrap: anywhere; }
        .message:empty { display: none; }
        .message[data-error="true"] { color: var(--error-color, #b3261e); }
        @media (max-width: 620px) {
          section + section { border-inline-start: 0; border-top: 1px solid var(--line); }
        }
      </style>
      <ha-card>
        <header>
          <div class="between">
            <div>
              <h2>Marstek</h2>
              <p class="muted">Kaartversie ${CARD_VERSION}</p>
            </div>
            <button type="button" id="refresh">Vernieuwen</button>
          </div>
          <div class="between">
            <div><p class="muted">Laadniveau</p><output class="soc" id="soc">—</output></div>
            <div><p class="muted">Huidige modus</p><output id="mode">—</output></div>
            <div><p class="muted">Actueel vermogen</p><output id="activity">—</output></div>
          </div>
          <div class="meter" aria-hidden="true"><div id="fill"></div></div>
        </header>
        <div class="body">
          <section class="stack">
            <h3>Batterijmodus</h3>
            <div class="modes">
              ${["Auto", "AI", "UPS"].map((mode) => `
                <button type="button" data-mode="${mode}" aria-pressed="false">${mode}</button>
              `).join("")}
            </div>
            <p class="muted">Activeer Manual bij het opslaan van een tijdslot.</p>
            <details>
              <summary>Passive instellen</summary>
              <form id="passive">
                <fieldset>
                  <div class="row">
                    <label>Vermogen (W)<input name="power" type="number" min="-2500" max="2500" required></label>
                    <label>Duur (min)<input name="minutes" type="number" min="1" max="1440" value="15" required></label>
                  </div>
                  <p class="muted">Negatief laadt, positief ontlaadt.</p>
                  <button type="submit">Passive starten</button>
                </fieldset>
              </form>
            </details>
          </section>
          <section class="stack">
            <h3>Programmatie</h3>
            <ul id="saved-slots" class="muted"></ul>
            <details id="schedule-editor">
              <summary>Tijdslot wijzigen</summary>
            <p class="muted">Tijdsloten die je in de Marstek-app instelt, zie je in die app.</p>
            <form id="schedule">
              <fieldset>
                <div class="row">
                  <label>Slot<select name="slot">${Array.from({ length: 9 }, (_, i) =>
                    `<option>${i + 1}</option>`).join("")}</select></label>
                  <label>Laadactie<select name="direction">
                    <option value="charge">Laden</option>
                    <option value="discharge">Ontladen</option>
                    <option value="auto">Auto binnen slot</option>
                  </select></label>
                </div>
                <div class="row">
                  <label>Van<input name="start" type="time" required></label>
                  <label>Tot<input name="end" type="time" required></label>
                </div>
                <label id="slot-power">Vermogen (W)<input name="power" type="number" min="1" max="2500" required></label>
                <div>
                  <p class="muted" id="day-label">Weekdagen</p>
                  <div class="days" role="group" aria-labelledby="day-label">
                    ${DAYS.map(([day, label]) =>
                      `<label><input type="checkbox" name="days" value="${day}" checked>${label}</label>`).join("")}
                  </div>
                </div>
                <label class="check"><input name="manual" type="checkbox"> Manual actief laten</label>
                <div class="buttons">
                  <button type="submit" class="primary">Slot opslaan</button>
                  <button type="button" id="disable">Slot uitschakelen</button>
                </div>
              </fieldset>
            </form>
            </details>
          </section>
        </div>
        <p class="message" id="message" role="status" aria-live="polite"></p>
      </ha-card>`;

    const schedule = this.find("#schedule");
    schedule.elements.direction.addEventListener("change", () => {
      const automatic = schedule.elements.direction.value === "auto";
      schedule.elements.power.disabled = automatic;
      this.find("#slot-power").hidden = automatic;
    });
    schedule.elements.slot.addEventListener("change", () => this.fillSlot());
    this.find("#schedule-editor").addEventListener("toggle", (event) => {
      if (event.target.open) this.fillSlot();
    });
    schedule.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(schedule);
      const days = data.getAll("days");
      if (!days.length) {
        this.message("Kies minstens één weekdag.", true);
        return;
      }
      const slot = Number(data.get("slot"));
      this.run("set_slot", {
        slot,
        start_time: data.get("start"),
        end_time: data.get("end"),
        days,
        action: data.get("direction"),
        power: Number(data.get("power")),
        activate_manual: data.has("manual"),
      }, `Slot ${slot} opgeslagen.`);
    });
    this.find("#disable").addEventListener("click", () => {
      const slot = Number(schedule.elements.slot.value);
      if (window.confirm(`Slot ${slot} uitschakelen en de bestaande slotgegevens vervangen?`)) {
        this.run("disable_slot", {
          slot,
          activate_manual: schedule.elements.manual.checked,
        }, `Slot ${slot} uitgeschakeld.`);
      }
    });
    const passive = this.find("#passive");
    passive.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(passive);
      this.run("set_passive", {
        power: Number(data.get("power")),
        duration_seconds: Number(data.get("minutes")) * 60,
      }, "Passive geactiveerd.");
    });
    for (const button of this.shadowRoot.querySelectorAll("[data-mode]")) {
      button.addEventListener("click", () => {
        const { mode } = button.dataset;
        this.run("set_mode", { mode }, `${mode} geactiveerd.`);
      });
    }
    this.find("#refresh").addEventListener("click", () => this.run());
  }

  setConfig(config) {
    this.config = config;
    this.loadOnce();
  }

  set hass(hass) {
    this._hass = hass;
    this.loadOnce();
  }

  connectedCallback() {
    super.connectedCallback();
    this.loadOnce();
    this.statusTimer = setInterval(() => {
      if (!document.hidden) this.run(undefined, undefined, undefined, true);
    }, STATUS_REFRESH_MS);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this.statusTimer);
  }

  getCardSize() {
    return 8;
  }

  find(selector) {
    return this.shadowRoot.querySelector(selector);
  }

  loadOnce() {
    if (this.isConnected && this.config && this._hass && !this.loaded) {
      this.loaded = true;
      this.run();
    }
  }

  message(text, error = false) {
    const message = this.find("#message");
    message.textContent = text;
    message.dataset.error = String(error);
  }

  call(service, data, returnResponse = false) {
    const entry = this.config.config_entry_id;
    return this._hass.callWS({
      type: "call_service",
      domain: DOMAIN,
      service,
      service_data: entry ? { ...data, config_entry_id: entry } : data,
      return_response: returnResponse,
    });
  }

  showStatus(status) {
    const value = status?.bat_soc;
    const soc = value === null || value === undefined || value === "" ? NaN : Number(value);
    const valid = Number.isFinite(soc) && soc >= 0 && soc <= 100;
    this.find("#soc").textContent = valid ? `${Math.round(soc)}%` : "—";
    this.find("#fill").style.width = valid ? `${soc}%` : "0";
    this.find("#mode").textContent = status?.mode || "—";
    this.find("#activity").textContent = formatBatteryActivity(status?.ongrid_power);
    for (const button of this.shadowRoot.querySelectorAll("[data-mode]")) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === status?.mode));
    }
  }

  showSlots(slots) {
    this.slots = slots;
    this.highlightTiles = [];
    const list = this.find("#saved-slots");
    list.replaceChildren();
    const items = Object.entries(slots);
    if (!items.length) {
      const item = document.createElement("li");
      item.textContent = "Via deze integratie opgeslagen slots verschijnen hier.";
      list.append(item);
    }
    for (const [number, slot] of items) {
      const item = document.createElement("li");
      const action = slot.action || (slot.power < 0 ? "charge" : slot.power > 0 ? "discharge" : "auto");
      const label = { charge: "Laden", discharge: "Ontladen", auto: "Auto" }[action];
      const power = action === "auto" ? "" : ` · ${Math.abs(slot.power)} W`;
      const days = DAYS.filter(([key]) => slot.days?.includes(key)).map(([, day]) => day).join(", ");
      item.textContent = slot.enabled
        ? `Slot ${number} · ${slot.start_time}–${slot.end_time} · ${label}${power} · ${days}`
        : `Slot ${number} · Uitgeschakeld`;
      list.append(item);
      if (slot.enabled && slot.start_time && slot.end_time && slot.days) {
        this.highlightTile(item, "Nu gepland", (day, previousDay, minute) =>
          includesMoment(slot.start_time, slot.end_time, minute,
            slot.days.includes(WEEKDAYS[day]), slot.days.includes(WEEKDAYS[previousDay])),
        );
      }
    }
    this.updateHighlight();
  }

  fillSlot() {
    const fields = this.find("#schedule").elements;
    const slot = this.slots?.[fields.slot.value];
    fields.start.value = slot?.start_time || "";
    fields.end.value = slot?.end_time || "";
    fields.direction.value = slot?.action || (slot?.power > 0 ? "discharge" : "charge");
    if (slot?.action === undefined && slot?.power === 0) fields.direction.value = "auto";
    fields.power.value = slot?.power == null ? "" : Math.abs(slot.power);
    for (const day of fields.days) day.checked = slot?.days?.includes(day.value) ?? true;
    fields.direction.dispatchEvent(new Event("change"));
  }

  async run(service, data, success, automatic = false) {
    if (this.busy || !this._hass || !this.config) return;
    this.busy = true;
    const controls = this.shadowRoot.querySelectorAll("button, fieldset");
    for (const control of controls) control.disabled = true;
    if (!automatic) this.message(service ? "Bezig met schrijven…" : "Batterijstatus ophalen…");
    let written = false;
    try {
      if (service) {
        await this.call(service, data);
        written = true;
      }
      const slotChanged = service === "set_slot" || service === "disable_slot";
      if (slotChanged) this.find("#schedule-editor").open = false;
      if ((!service && !automatic) || slotChanged) {
        try {
          const { response } = await this.call("get_slots", {}, true);
          this.showSlots(response.slots);
        } catch (error) {
          this.highlightTiles = [];
          this.find("#saved-slots").textContent = `Slots ophalen mislukt. ${error?.message || error}`;
        }
      }
      const result = await this.call("get_status", {}, true);
      this.showStatus(result.response);
      if (!automatic) this.message(success || "");
    } catch (error) {
      if (automatic) {
        this.find("#activity").textContent = "Onbekend";
        return;
      }
      this.showStatus();
      this.message(
        written
          ? `${success} Status uitlezen mislukt: ${error?.message || error}`
          : `Marstek: ${error?.message || error}`,
        true,
      );
    } finally {
      for (const control of controls) control.disabled = false;
      this.busy = false;
    }
  }
}

if (!customElements.get("marstek-diggit-card")) {
  customElements.define("marstek-diggit-card", MarstekDiggitCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "marstek-diggit-card",
    name: "Marstek",
    description: "Batterijstatus, modi en tijdsloten",
  });
}

const TARIFF_TYPES = [["peak", "Piek"], ["offpeak", "Dal"], ["super_offpeak", "Superdal"]];
const TARIFF_PROFILES = [["weekday", "Maandag t/m vrijdag"], ["weekend", "Zaterdag en zondag"]];

class MarstekTariffsCard extends ScheduleCard {
  static getStubConfig() {
    return { type: "custom:marstek-diggit-tariffs-card" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; color: var(--primary-text-color); }
        ha-card { padding: 20px; }
        h2, p { margin: 0; }
        h2 { font-size: 24px; }
        .muted { color: var(--secondary-text-color); font-size: 13px; }
        .overview { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 10px; margin: 14px 0; }
        .overview article { border: 1px solid var(--divider-color); border-radius: 9px; padding: 8px 10px; }
        ${ACTIVE_STYLE}
        .overview p { margin-top: 4px; overflow-wrap: anywhere; }
        summary { cursor: pointer; font-weight: 600; }
        output:not(:empty) { display: block; margin-top: 8px; }
        form { display: grid; gap: 18px; margin-top: 16px; }
        fieldset { border: 1px solid var(--divider-color); border-radius: 12px; min-width: 0; margin: 0; padding: 12px; }
        fieldset:disabled { opacity: .65; }
        legend { font-weight: 600; padding: 0 5px; }
        .fields { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 115px), 1fr)); }
        label { display: grid; gap: 6px; min-width: 0; }
        input, textarea, button {
          box-sizing: border-box; font: inherit; color: inherit; padding: 8px;
          background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 8px;
        }
        input, textarea { width: 100%; }
        textarea { resize: vertical; }
        button { min-height: 42px; cursor: pointer; font-weight: 600; }
        button:disabled { opacity: .55; }
        button[type="submit"] { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .actions { display: flex; flex-wrap: wrap; gap: 8px; }
        output[data-error="true"] { color: var(--error-color, #b3261e); }
      </style>
      <ha-card>
        <h2>Elektriciteitstarieven</h2>
        <p class="muted">Kaartversie ${CARD_VERSION}</p>
        <div id="tariff-summary" class="overview" aria-live="polite"></div>
        <details>
          <summary>Tarieven en tijdvakken wijzigen</summary>
          <form>
          <fieldset disabled>
            <legend>Prijzen in €/kWh</legend>
            <div class="fields">
              ${TARIFF_TYPES.map(([kind, label]) => `
                <label>${label}<input name="${kind}" inputmode="decimal" maxlength="20"
                  pattern="[0-9]+([.,][0-9]{1,4})?" placeholder="0,2500" required></label>
              `).join("")}
            </div>
          </fieldset>
          <p class="muted">Gebruik UU:MM-UU:MM. Scheid tijdvakken met komma’s of nieuwe regels.
            Een tijdvak over middernacht loopt door op de volgende dag. Lege uren krijgen geen tarief.</p>
          ${TARIFF_PROFILES.map(([profile, label]) => `
            <fieldset disabled>
              <legend>${label}</legend>
              <div class="fields">
                ${TARIFF_TYPES.map(([kind, title]) => `
                  <label>${title}<textarea name="${profile}_${kind}" rows="2"
                    placeholder="07:00-11:00"></textarea></label>
                `).join("")}
              </div>
            </fieldset>
          `).join("")}
          <div class="actions">
            <button type="submit" disabled>Tarieven opslaan</button>
            <button type="button" disabled>Opnieuw laden</button>
          </div>
          </form>
        </details>
        <output role="status" aria-live="polite"></output>
      </ha-card>`;
    this.form = this.shadowRoot.querySelector("form");
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.save();
    });
    this.form.querySelector('button[type="button"]').addEventListener("click", () => {
      if (!this.dirty || window.confirm("Je wijzigingen verwerpen en de opgeslagen tarieven laden?")) {
        this.load();
      }
    });
    this.form.addEventListener("input", () => { this.dirty = true; });
  }

  setConfig() {}

  set hass(value) {
    this._hass = value;
    if (!this.started) {
      this.started = true;
      this.load();
    }
  }

  getCardSize() {
    return 6;
  }

  async request(service, data, returnResponse) {
    const result = await this._hass.callWS({
      type: "call_service", domain: DOMAIN, service,
      service_data: data, return_response: returnResponse,
    });
    return result.response;
  }

  async load() {
    await this.run(async () => {
      const settings = await this.request("get_tariffs", {}, true);
      for (const [kind] of TARIFF_TYPES) {
        this.form.elements[kind].value = settings.prices[kind];
        for (const [profile] of TARIFF_PROFILES) {
          this.form.elements[`${profile}_${kind}`].value = settings.schedule[profile][kind].join("\n");
        }
      }
      this.showTariffs(settings);
      this.loaded = true;
      this.dirty = false;
      return "";
    }, "Tarieven laden…");
  }

  async save() {
    const prices = Object.fromEntries(TARIFF_TYPES.map(([kind]) => [kind, this.form.elements[kind].value]));
    const schedule = Object.fromEntries(TARIFF_PROFILES.map(([profile]) => [
      profile,
      Object.fromEntries(TARIFF_TYPES.map(([kind]) => [
        kind, this.form.elements[`${profile}_${kind}`].value.split(/[,\n]/).map((block) => block.trim()).filter(Boolean),
      ])),
    ]));
    await this.run(async () => {
      await this.request("set_tariffs", { prices, schedule }, false);
      this.showTariffs({ prices, schedule });
      this.form.closest("details").open = false;
      this.dirty = false;
      return "Tarieven opgeslagen.";
    }, "Tarieven opslaan…");
  }

  showTariffs({ prices, schedule }) {
    const summary = this.shadowRoot.querySelector("#tariff-summary");
    summary.replaceChildren();
    this.highlightTiles = [];
    for (const [kind, label] of TARIFF_TYPES) {
      const tile = document.createElement("article");
      const heading = document.createElement("strong");
      const amount = prices[kind].replace(".", ",");
      heading.textContent = amount ? `${label} · € ${amount}/kWh` : label;
      tile.append(heading);
      for (const [profile, shortLabel] of [["weekday", "Ma–vr"], ["weekend", "Za–zo"]]) {
        const line = document.createElement("p");
        line.className = "muted";
        line.textContent = `${shortLabel} · ${schedule[profile][kind].join(", ") || "—"}`;
        tile.append(line);
      }
      summary.append(tile);
      this.highlightTile(tile, "Nu", (day, previousDay, minute) =>
        TARIFF_PROFILES.some(([profile]) => schedule[profile][kind].some((block) => {
          const [start, end] = block.split("-").map((time) => time.trim());
          return includesMoment(start, end, minute,
            (day < 5) === (profile === "weekday"),
            (previousDay < 5) === (profile === "weekday"));
        })),
      );
    }
    this.updateHighlight();
  }

  async run(action, pending) {
    if (this.busy) return;
    this.busy = true;
    const controls = this.form.querySelectorAll("fieldset, button");
    const status = this.shadowRoot.querySelector("output");
    for (const control of controls) control.disabled = true;
    status.dataset.error = "false";
    status.textContent = pending;
    try {
      status.textContent = await action();
    } catch (error) {
      status.dataset.error = "true";
      status.textContent = error?.message || String(error);
    } finally {
      for (const control of controls) control.disabled = !this.loaded && control.type !== "button";
      this.busy = false;
    }
  }
}

if (!customElements.get("marstek-diggit-tariffs-card")) {
  customElements.define("marstek-diggit-tariffs-card", MarstekTariffsCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "marstek-diggit-tariffs-card",
    name: "Marstek elektriciteitstarieven",
    description: "Prijzen en tijdvakken voor piek, dal en superdal",
  });
}

const ENERGY_MODES = {
  CHARGING: "Laden", HOLDING: "Vasthouden",
  SELF_CONSUMPTION: "Ontladen via Auto", SAFE_FALLBACK: "Geblokkeerd",
};
const ENERGY_TARIFFS = { peak: "Piek", offpeak: "Dal", super_offpeak: "Superdal" };
const PHASES = { learning: "Leerfase", shadow: "Schaduwmodus", active: "Actieve doel-SoC in simulatie" };
const ENERGY_FIELDS = [
  ["p1_sensor", "P1-netvermogen"], ["ev_sensor", "Smappee-laadvermogen"],
  ["solar_sensor", "Zonneproductie"], ["forecast_sensor", "Zonnevoorspelling"],
  ["quarter_energy_sensor", "Importenergie lopend meetkwartier"],
  ["minimum_soc", "Minimum-SoC (%)", 0, 99], ["grid_limit", "Kwartiergrens (W)", 500, 25000],
  ["interval_minutes", "Strategie-interval (minuten)", 10, 60],
  ["max_charge", "Maximaal laadvermogen (W)", 100, 2500],
  ["safety_margin", "Voorspellingsmarge (%)", 0, 100],
  ["learning_days", "Geldige leerdagen", 30, 90], ["shadow_days", "Geldige schaduwdagen", 14, 90],
  ["max_sensor_age", "Maximale sensorleeftijd (seconden)", 30, 600],
];

function energyValue(value, unit) {
  return value == null ? "Onbekend" : `${Number(value).toLocaleString("nl-BE", { maximumFractionDigits: 1 })} ${unit}`;
}

class MarstekEnergyPlannerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; --rule:var(--divider-color,#d6dce2); }
        * { box-sizing:border-box; }
        ha-card { padding:16px; display:grid; gap:14px; overflow:hidden; }
        h2,h3,p,dl,dd,ol { margin:0; }
        h2 { font-size:1.36rem; }
        h3 { font-size:1rem; margin-bottom:8px; }
        .sub,dt { color:var(--secondary-text-color,#526267); font-size:.85em; }
        dl,fieldset { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,155px),1fr)); gap:8px 12px; }
        dl>div,li { padding:8px 10px; border:1px solid var(--rule); border-radius:8px; }
        dd { margin-top:3px; overflow-wrap:anywhere; }
        ol { list-style:none; padding:0; display:grid; gap:6px; max-height:340px; overflow:auto; }
        li { border-inline-start:5px solid #607080; display:grid; gap:4px; }
        li[data-mode=CHARGING] { border-inline-start-color:#23853c; }
        li[data-mode=HOLDING] { border-inline-start-color:#b18000; }
        li[data-mode=SELF_CONSUMPTION] { border-inline-start-color:#2b6abc; }
        li[data-blocked=true] { border-inline-start-color:#b54040; }
        .warn { color:var(--error-color,#af3434); }
        summary { cursor:pointer; margin-bottom:8px; }
        fieldset { border:0; margin:0 0 8px; padding:0; min-width:0; }
        label { display:grid; gap:4px; min-width:0; }
        button,input,select { color:inherit; font:inherit; }
        input:not([type=checkbox]),select,button { border:1px solid var(--rule); border-radius:6px; padding:7px;
          min-height:40px; background:var(--card-background-color,#fff); width:100%; }
        button { cursor:pointer; }
        .checks { display:flex; flex-wrap:wrap; gap:10px; margin:10px 0; }
        .checks label { display:flex; align-items:center; }
        [hidden] { display:none!important; }
      </style>
      <ha-card>
        <header><h2>Energy Planner</h2><p id="summary" class="sub">Gegevens ophalen…</p></header>
        <p id="error" class="warn" role="status" hidden></p>
        <section id="diagnostics" hidden></section>
        <section id="metrics" hidden></section>
        <section id="timeline" hidden></section>
        <details id="settings">
          <summary>Instellingen</summary>
          <form>
            <fieldset></fieldset>
            <div class="checks">
              <label><input type="checkbox" name="enabled"> Planner inschakelen</label>
              <label><input type="checkbox" name="simulation" checked disabled> Simulatiemodus</label>
              <label><input type="checkbox" name="learning_active"> Lerende doel-SoC toestaan</label>
            </div>
            <button type="submit">Instellingen opslaan</button>
          </form>
        </details>
      </ha-card>`;
    this.shadowRoot.querySelector("form").addEventListener("submit", event => this.save(event));
  }

  static getStubConfig() { return { type: "custom:marstek-diggit-energy-planner-card" }; }

  setConfig() {}
  set hass(value) {
    this._hass = value;
    if (this.isConnected && !this.data && !this.loading) this.refresh();
  }
  connectedCallback() {
    this.refresh();
    this.timer = setInterval(() => { if (!document.hidden) this.refresh(); }, STATUS_REFRESH_MS);
  }
  disconnectedCallback() { clearInterval(this.timer); }

  async call(service, data = {}, response = false) {
    return this._hass.callWS({
      type: "call_service", domain: DOMAIN, service, service_data: data, return_response: response,
    });
  }

  showError(message) {
    const error = this.shadowRoot.querySelector("#error");
    error.textContent = message || "";
    error.hidden = !message;
  }

  async refresh() {
    if (!this._hass || this.loading) return;
    this.loading = true;
    try {
      const { response } = await this.call("get_energy_plan", {}, true);
      this.data = response;
      this.render();
    } catch (error) {
      this.showError(error.message || String(error));
    } finally {
      this.loading = false;
    }
  }

  section(id, title, fields) {
    const section = this.shadowRoot.querySelector(id);
    section.hidden = false;
    const heading = document.createElement("h3");
    heading.textContent = title;
    const list = document.createElement("dl");
    for (const [label, value] of fields) {
      const cell = document.createElement("div");
      const key = document.createElement("dt");
      const reading = document.createElement("dd");
      key.textContent = label;
      reading.textContent = value;
      cell.append(key, reading);
      list.append(cell);
    }
    section.replaceChildren(heading, list);
  }

  renderTimeline(rows) {
    const section = this.shadowRoot.querySelector("#timeline");
    const heading = document.createElement("h3");
    heading.textContent = "Planning komende 24 uur";
    const list = document.createElement("ol");
    const time = new Intl.DateTimeFormat("nl-BE", {
      timeZone: this._hass.config.time_zone, weekday: "short", hour: "2-digit", minute: "2-digit",
    });
    for (const row of rows) {
      const item = document.createElement("li");
      item.dataset.mode = row.mode;
      item.dataset.blocked = String(row.status === "blocked");
      const title = document.createElement("strong");
      const details = document.createElement("span");
      const reason = document.createElement("span");
      details.className = reason.className = "sub";
      title.textContent = `${time.format(new Date(row.start))} – ${time.format(new Date(row.end))} · ${ENERGY_TARIFFS[row.tariff] || "Zonder tarief"} · ${ENERGY_MODES[row.mode]}`;
      details.textContent = `Doel ${row.target}% · Verwacht ${row.soc.map(soc => energyValue(soc, "%")).join(" / ")} · Zon ${energyValue(row.solar_w, "W")} · Verbruik ${energyValue(row.household_w, "W")}`;
      reason.textContent = `${row.status === "blocked" ? "Geblokkeerd" : "Gepland"} · ${row.reason}`;
      item.append(title, details, reason);
      list.append(item);
    }
    section.replaceChildren(heading, list);
  }

  renderSettings() {
    const form = this.shadowRoot.querySelector("form");
    const { config, battery_entries: entries } = this.data;
    const fields = form.querySelector("fieldset");
    fields.replaceChildren();
    for (let i = 0; i < 2; i++) {
      const label = document.createElement("label");
      label.textContent = `Batterij ${i + 1}`;
      const select = document.createElement("select");
      select.name = `battery_${i}`;
      select.append(new Option("Kies een batterij", ""));
      for (const entry of entries) select.append(new Option(entry.title, entry.id));
      select.value = config.battery_ids?.[i] || "";
      label.append(select);
      fields.append(label);
    }
    for (const [name, title, min, max] of ENERGY_FIELDS) {
      const label = document.createElement("label");
      label.textContent = title;
      const input = document.createElement("input");
      input.name = name;
      input.value = config[name] ?? "";
      if (min !== undefined) {
        input.type = "number";
        input.min = min;
        input.max = max;
        input.required = true;
      } else {
        input.placeholder = "sensor.naam";
      }
      label.append(input);
      fields.append(label);
    }
    form.elements.enabled.checked = config.enabled;
    form.elements.learning_active.checked = config.learning_active;
  }

  render() {
    const { config, decision, quarter, learning, batteries, plan, error } = this.data;
    this.showError(error || (this.data.quarter_warning ? "Netafname al minstens 10 minuten boven de grens." : ""));
    this.shadowRoot.querySelector("#summary").textContent = config.enabled
      ? "Simulatie · leest metingen en berekent voorstellen"
      : "Planner uitgeschakeld";
    for (const id of ["#diagnostics", "#metrics", "#timeline"]) this.shadowRoot.querySelector(id).hidden = !decision;
    if (!this.settingsLoaded) {
      this.renderSettings();
      this.settingsLoaded = true;
    }
    if (!decision || !quarter || !learning) return;
    this.section("#diagnostics", "Huidige beslissing", [
      ["Voorstel", ENERGY_MODES[decision.mode]], ["Reden", decision.reason],
      ["Blokkeringen", decision.blocks.join(", ") || "Geen in de simulatie"],
      ["Uitvoering", this.data.blocked_execution],
      ["Laatste opdracht", this.data.last_successful_command || "Geen · simulatie"],
      ["Volgende actie", this.data.next_action ? `${ENERGY_MODES[this.data.next_action.mode]} · ${this.data.next_action.reason}` : "Geen wijziging gepland"],
      ["Superdal", this.data.superdal_shortfall ? `100% mogelijk niet haalbaar · ${this.data.superdal_shortfall.join("% / ")}%` : "Geen voorspeld tekort"],
    ]);
    const last = learning.errors.at(-1);
    this.section("#metrics", "Batterijen, kwartierpiek en leerproces", [
      ...batteries.map((battery, i) => [`Batterij ${i + 1}`, battery
        ? `${energyValue(battery.soc, "%")} · ${battery.mode} · ${formatBatteryActivity(battery.watts)}` : "Geen bevestigde status"]),
      ["Gezamenlijk boven minimum", energyValue(this.data.available_wh, "Wh")],
      ["Netafname", energyValue(quarter.grid_w, "W")], ["Kwartier tot nu toe", energyValue(quarter.average_w, "W")],
      ["Voorspelde kwartierpiek", energyValue(quarter.forecast_w, "W")],
      ["Kwartiergrens", energyValue(quarter.limit_w, "W")],
      ["Boven de grens", energyValue(quarter.above_seconds, "s")],
      ["Toelaatbaar resterend gemiddelde", energyValue(quarter.allowed_w, "W")],
      ["Kwartierenergie", `${energyValue(quarter.energy_wh, "Wh")} · ${quarter.source === "meter" ? "Meter" : "Schatting"}`],
      ["Laadvoorstel", energyValue(-decision.watts.reduce((total, watts) => total + (watts || 0), 0), "W")],
      ["Laadbeperking", this.data.quarter_charge_limited ? "Kwartierbudget beperkt netladen" : "Geen kwartierbeperking"],
      ["Piekwaarschuwing", this.data.unavoidable_peak ? "Verbruik zonder batterijactie ligt al boven de resterende marge" : "Binnen resterende marge"],
      ["Fase", PHASES[learning.phase]], ["Geldige dagen", `${learning.valid_days} · ${learning.shadow_days} schaduw`],
      ["Verwacht avondverbruik", energyValue(learning.forecast_wh, "Wh")],
      ["Doel-SoC · rekenwaarde / toegepast", `${decision.target}% toegepast · ${learning.target}% berekend voor dal`],
      ["Voorspellingsbasis", learning.confidence === "historical" ? "Geldige leer- en schaduwdagen" : "Nog onvoldoende meetdagen"],
      ["Laatste voorspelling / gemeten", last ? `${energyValue(last.predicted_wh, "Wh")} / ${energyValue(last.actual_wh, "Wh")}` : "Nog geen geldige schaduwdag"],
      ["Historische fouten", learning.errors.length
        ? learning.errors.map(day => `${day.date} ${energyValue(day.error_wh, "Wh")}`).join(" · ") : "Geen voorspellingen om te vergelijken"],
    ]);
    this.renderTimeline(plan);
  }

  async save(event) {
    event.preventDefault();
    const submit = event.target.querySelector("button");
    const params = new FormData(event.target);
    const data = { enabled: params.has("enabled"), learning_active: params.has("learning_active"), simulation: true };
    const batteries = [params.get("battery_0"), params.get("battery_1")];
    if (batteries.every(Boolean)) data.battery_ids = batteries;
    if (data.enabled && (!batteries.every(Boolean) || batteries[0] === batteries[1])) {
      this.showError("Kies twee verschillende batterijen.");
      return;
    }
    for (const [key, , min] of ENERGY_FIELDS) {
      data[key] = min === undefined ? params.get(key).trim() : Number(params.get(key));
    }
    submit.disabled = true;
    try {
      await this.call("configure_energy_controller", data);
      this.settingsLoaded = false;
      await this.refresh();
    } catch (error) {
      this.showError(error.message || String(error));
    } finally {
      submit.disabled = false;
    }
  }
}

if (!customElements.get("marstek-diggit-energy-planner-card")) {
  customElements.define("marstek-diggit-energy-planner-card", MarstekEnergyPlannerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "marstek-diggit-energy-planner-card", name: "Marstek Energy Planner",
    description: "Simuleer de tariefregeling voor twee Marstek-batterijen.",
  });
}
