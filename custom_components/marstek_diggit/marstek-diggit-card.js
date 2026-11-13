const DOMAIN = "marstek_diggit";
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
            <h2>Marstek</h2>
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
            <h3>Tijdslot programmeren</h3>
            <p class="muted">De invoervelden tonen je nieuwe programma. Bestaande tijdsloten zijn zichtbaar in de Marstek-app.</p>
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
