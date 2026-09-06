import { html } from "../lib/html.js";
import { SunIcon, SystemIcon, MoonIcon } from "./Icons.js";

const CHOICES = [
  { key: "light", label: "Light theme", title: "Light", Icon: SunIcon },
  { key: "system", label: "Match the system theme", title: "Match the system", Icon: SystemIcon },
  { key: "dark", label: "Dark theme", title: "Dark", Icon: MoonIcon },
];

export function ThemeToggle({ theme, onChoose }) {
  return html`
    <div class="theme" role="group" aria-label="Colour theme">
      ${CHOICES.map(({ key, label, title, Icon }) => html`
        <button type="button" key=${key} title=${title} aria-label=${label}
                aria-pressed=${String(theme === key)} onClick=${() => onChoose(key)}>
          <${Icon} />
        </button>`)}
    </div>`;
}
