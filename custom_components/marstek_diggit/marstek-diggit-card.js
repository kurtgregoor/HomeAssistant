const DOMAIN = "marstek_diggit";
const CARD_VERSION = "0.1.7";
const DAYS = [
  ["mon", "Ma"], ["tue", "Di"], ["wed", "Wo"], ["thu", "Do"],
  ["fri", "Vr"], ["sat", "Za"], ["sun", "Zo"],
];

class MarstekDiggitCard extends HTMLElement {
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
        #saved-slots { margin: 0; padding-inline-start: 18px; }
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
    this.loadOnce();
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
    for (const button of this.shadowRoot.querySelectorAll("[data-mode]")) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === status?.mode));
    }
  }

  showSlots(slots) {
    this.slots = slots;
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
    }
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

  async run(service, data, success) {
    if (this.busy || !this._hass || !this.config) return;
    this.busy = true;
    const controls = this.shadowRoot.querySelectorAll("button, fieldset");
    for (const control of controls) control.disabled = true;
    this.message(service ? "Bezig met schrijven…" : "Batterijstatus ophalen…");
    let written = false;
    try {
      if (service) {
        await this.call(service, data);
        written = true;
      }
      const slotChanged = service === "set_slot" || service === "disable_slot";
      if (slotChanged) this.find("#schedule-editor").open = false;
      if (!service || slotChanged) {
        try {
          const { response } = await this.call("get_slots", {}, true);
          this.showSlots(response.slots);
        } catch (error) {
          this.find("#saved-slots").textContent = `Slots ophalen mislukt. ${error?.message || error}`;
        }
      }
      const result = await this.call("get_status", {}, true);
      this.showStatus(result.response);
      this.message(success || "");
    } catch (error) {
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

class MarstekTariffsCard extends HTMLElement {
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
    }
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
