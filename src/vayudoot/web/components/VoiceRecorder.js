/* A voice note, recorded in the browser or attached as a file.
 *
 * Someone standing near a burning dump can say more in twenty seconds than
 * they will type, and can say it in their own language. So the report form
 * takes a spoken account as well as, or instead of, a photograph; the server
 * hears it with Gemini and stores a transcript and an English translation.
 *
 * The states are drawn one at a time, because each asks for one thing:
 *
 * - idle: one big record button, and a plain file picker under it for anyone
 *   whose browser cannot record or who already has a clip on their phone.
 * - asking: the browser's own permission prompt is up. Nothing to press.
 * - recording: a running clock against the limit, a live level so the person
 *   can see the phone is hearing them, and a stop button. It stops by itself
 *   at the limit the instance publishes in `/health`, so a clip can never be
 *   refused for length after the fact.
 * - recorded: playback, record again, remove. Nothing is sent until the form
 *   is submitted.
 * - denied: the microphone was refused. Said plainly, with how to undo it,
 *   and the file picker still works.
 *
 * The recorder prefers Opus in WebM, then Opus in Ogg, then AAC in MP4 (what
 * Safari records). All three are formats the server accepts; the server reads
 * the format from the bytes, so the file name given here is only a courtesy.
 */

import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { megabytes } from "../lib/format.js";

/* Local icons, in the same 24px stroked style as `Icons.js`. Kept here so the
   recorder is one file to read and one file to change. */
const icon = (body) => () => html`<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
const MicIcon = icon(html`
  <rect x="9" y="3" width="6" height="11" rx="3" />
  <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" />`);
const StopIcon = icon(html`<rect x="6.5" y="6.5" width="11" height="11" rx="2" />`);
const RedoIcon = icon(html`
  <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" /><path d="M4.5 4v4.5H9" />`);
const TrashIcon = icon(html`
  <path d="M4.5 7h15M10 4h4M6.5 7l1 12.5h9l1-12.5M10 10.5v6M14 10.5v6" />`);
const MicOffIcon = icon(html`
  <path d="M9 9v2a3 3 0 0 0 5.1 2.1M15 10V6a3 3 0 0 0-5.7-1.3" />
  <path d="M5.5 11a6.5 6.5 0 0 0 10.6 5M18.5 11a6.4 6.4 0 0 1-.6 2.7M12 17.5V21M8.5 21h7" />
  <path d="M4 4l16 16" />`);
const LockIcon = icon(html`
  <rect x="4.5" y="10.5" width="15" height="9.5" rx="2" />
  <path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3" />`);
const FileAudioIcon = icon(html`
  <path d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5H6.5A.5.5 0 0 1 6 20z" />
  <path d="M14 3.5V8h4M10.5 17.5v-5l4-1v5" /><circle cx="9.5" cy="17.5" r="1" />
  <circle cx="13.5" cy="16.5" r="1" />`);

/* What the instance takes when `/health` has not answered yet. Matches the
   server's defaults; the server checks again either way. */
const DEFAULT_SECONDS = 90;

/* Under a second is a slipped thumb, not a report. */
const MIN_SECONDS = 1;

/* The level meter: how many bars, and how often it moves. */
const BARS = 28;
const TICK_MS = 100;

const CANDIDATES = [
  ["audio/webm;codecs=opus", "webm"],
  ["audio/ogg;codecs=opus", "ogg"],
  ["audio/mp4", "m4a"],
  ["audio/webm", "webm"],
];

function recorderType() {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return ["", "webm"];
  return CANDIDATES.find(([type]) => MediaRecorder.isTypeSupported(type)) || ["", "webm"];
}

export const canRecord = () =>
  typeof window !== "undefined" && typeof window.MediaRecorder !== "undefined"
  && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

/* A clip's size. Voice notes are small, so kilobytes are the useful unit
   below a megabyte; the limit itself is still said in `megabytes`. */
const sizeOf = (bytes) => (bytes < 1024 * 1024
  ? `${Math.max(1, Math.round(bytes / 1024))} KB` : megabytes(bytes));

export const clock = (seconds) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/* A refusal from getUserMedia, turned into what to do about it. */
function refusal(error) {
  const name = error && error.name;
  if (name === "NotAllowedError" || name === "SecurityError") {
    return {
      state: "denied",
      text: "Microphone access was refused, so nothing can be recorded here.",
      hint: "Turn the microphone on in this site's settings (the icon by the address bar), "
        + "or attach a file below.",
    };
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return {
      state: "denied",
      text: "No microphone was found on this device.",
      hint: "Attach a recording made on another device instead.",
    };
  }
  return {
    state: "denied",
    text: "The microphone could not be started.",
    hint: "Another app may be using it. Close it and try again, or attach a recording below.",
  };
}

export function VoiceRecorder({ health, clip, onClip, onRecording }) {
  const maxSeconds = (health && health.max_audio_seconds) || DEFAULT_SECONDS;
  const maxBytes = health && health.max_audio_bytes;

  const [state, setState] = useState(clip ? "recorded" : "idle");
  const [elapsed, setElapsed] = useState(0);
  const [levels, setLevels] = useState(() => new Array(BARS).fill(0));
  const [problem, setProblem] = useState(null);

  const live = useRef(null);   // { stream, recorder, context, timer, started }
  const picker = useRef(null);

  useEffect(() => () => teardown(), []);
  useEffect(() => { if (onRecording) onRecording(state === "recording" || state === "asking"); },
    [state]);
  useEffect(() => { if (!clip && state === "recorded") setState("idle"); }, [clip]);

  function teardown() {
    const run = live.current;
    live.current = null;
    if (!run) return;
    clearInterval(run.timer);
    if (run.recorder && run.recorder.state !== "inactive") {
      run.recorder.onstop = null;
      run.recorder.stop();
    }
    run.stream.getTracks().forEach((track) => track.stop());
    if (run.context) run.context.close().catch(() => {});
  }

  function keep(next) {
    if (clip && clip.url) URL.revokeObjectURL(clip.url);
    onClip(next);
  }

  async function start() {
    setProblem(null);
    setState("asking");
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch (error) {
      const said = refusal(error);
      setProblem(said);
      setState(said.state);
      return;
    }

    const [mimeType, extension] = recorderType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };

    /* The level meter. Optional: a browser without Web Audio still records. */
    let context = null;
    let analyser = null;
    try {
      context = new (window.AudioContext || window.webkitAudioContext)();
      analyser = context.createAnalyser();
      analyser.fftSize = 512;
      context.createMediaStreamSource(stream).connect(analyser);
    } catch { context = null; analyser = null; }
    const samples = analyser ? new Uint8Array(analyser.fftSize) : null;

    const run = { stream, recorder, context, started: Date.now(), timer: 0 };
    live.current = run;

    recorder.onstop = () => {
      const seconds = (Date.now() - run.started) / 1000;
      teardown();
      const type = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(chunks, { type });
      if (seconds < MIN_SECONDS || !blob.size) {
        setProblem({ text: "That was too short to hear anything. Hold on and try again." });
        setState("idle");
        return;
      }
      keep({
        blob,
        name: `voice-note.${extension}`,
        url: URL.createObjectURL(blob),
        seconds,
        size: blob.size,
        source: "recorded",
      });
      setState("recorded");
    };

    run.timer = setInterval(() => {
      const seconds = (Date.now() - run.started) / 1000;
      setElapsed(seconds);
      if (analyser) {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const v of samples) sum += ((v - 128) / 128) ** 2;
        const level = Math.min(1, Math.sqrt(sum / samples.length) * 4);
        setLevels((prev) => [...prev.slice(1), level]);
      }
      if (seconds >= maxSeconds) stop();
    }, TICK_MS);

    setElapsed(0);
    setLevels(new Array(BARS).fill(0));
    recorder.start(250);
    setState("recording");
  }

  function stop() {
    const run = live.current;
    if (run && run.recorder.state !== "inactive") run.recorder.stop();
  }

  function discard() {
    keep(null);
    setProblem(null);
    setState("idle");
  }

  function again() {
    discard();
    start();
  }

  function onFile(event) {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    if (maxBytes && file.size > maxBytes) {
      setProblem({
        text: `That recording is too large. The limit is ${megabytes(maxBytes)}, and that one `
          + `is ${sizeOf(file.size)}.`,
        hint: `Keep it under ${maxSeconds} seconds, or share a compressed copy.`,
      });
      return;
    }
    setProblem(null);
    keep({
      blob: file,
      name: file.name || "voice-note",
      url: URL.createObjectURL(file),
      seconds: null,
      size: file.size,
      source: "attached",
    });
    setState("recorded");
  }

  const recordable = canRecord();
  const left = Math.max(0, maxSeconds - elapsed);
  const nearEnd = state === "recording" && left <= 10;

  return html`
    <div class="voice" data-state=${state}>
      <div class="field-head">
        <span class="field-label">Or say it <span class="muted">(optional)</span></span>
        <span class="voice-lang">Any language</span>
      </div>

      <div class="voice-well">
        ${state === "idle" && html`
          ${recordable
            ? html`
              <button type="button" class="voice-record" onClick=${start}>
                <span class="voice-disc"><${MicIcon} /></span>
                <span class="voice-cta">
                  <strong>Record a voice note</strong>
                  <span>Up to ${clock(maxSeconds)} · say what, where, and how often</span>
                </span>
              </button>`
            : html`
              <p class="voice-message">
                <span class="voice-disc is-off"><${MicOffIcon} /></span>
                <span>Recording isn't available in this browser — attach a file below.</span>
              </p>`}`}

        ${state === "asking" && html`
          <div class="voice-row" role="status">
            <span class="voice-disc is-waiting"><${MicIcon} /></span>
            <span class="voice-cta">
              <strong>Waiting for the microphone</strong>
              <span>Allow access in the prompt your browser is showing.</span>
            </span>
          </div>`}

        ${state === "recording" && html`
          <div class="voice-live">
            <span class="voice-rec" aria-hidden="true"></span>
            <span class=${`voice-clock tnum${nearEnd ? " is-near" : ""}`} role="timer"
                  aria-live="off">${clock(elapsed)}</span>
            <span class="voice-meter" aria-hidden="true">
              ${levels.map((level, i) => html`
                <i key=${i} style=${`--level:${Math.max(0.08, level).toFixed(3)}`}></i>`)}
            </span>
            <button type="button" class="voice-stop" onClick=${stop}>
              <${StopIcon} />Stop
            </button>
          </div>
          <div class="voice-progress" aria-hidden="true">
            <span style=${`width:${Math.min(100, (elapsed / maxSeconds) * 100).toFixed(1)}%`}></span>
          </div>
          <p class="help tnum" aria-live="polite">
            ${nearEnd
              ? `${Math.ceil(left)} seconds left. It stops by itself at ${clock(maxSeconds)}.`
              : `Recording. It stops by itself at ${clock(maxSeconds)}.`}
          </p>`}

        ${state === "recorded" && clip && html`
          <div class="voice-take">
            <div class="voice-take-head">
              <span class="voice-disc is-done"><${clip.source === "attached"
                ? FileAudioIcon : MicIcon} /></span>
              <span class="voice-cta">
                <strong>${clip.source === "attached" ? "Recording attached" : "Voice note ready"}</strong>
                <span class="tnum">${[
                  clip.seconds ? clock(clip.seconds) : clip.name,
                  sizeOf(clip.size),
                  "sent with the report",
                ].join(" · ")}</span>
              </span>
            </div>
            <audio controls preload="metadata" src=${clip.url}></audio>
            <div class="voice-actions">
              ${recordable && html`
                <button type="button" class="voice-ghost" onClick=${again}>
                  <${RedoIcon} />Record again
                </button>`}
              <button type="button" class="voice-ghost is-quiet" onClick=${discard}>
                <${TrashIcon} />Remove
              </button>
            </div>
          </div>`}

        ${state === "denied" && problem && html`
          <div class="voice-denied" role="alert">
            <span class="voice-disc is-off"><${MicOffIcon} /></span>
            <div>
              <strong>${problem.text}</strong>
              <p>${problem.hint}</p>
              <button type="button" class="link" onClick=${start}>Try the microphone again</button>
            </div>
          </div>`}
      </div>

      ${problem && state !== "denied" && html`
        <div class="form-error" data-tone="attention" role="alert">
          <p>${problem.text}</p>
          ${problem.hint && html`<p class="hint">${problem.hint}</p>`}
        </div>`}

      ${state !== "recording" && state !== "asking" && html`
        <p class="help voice-attach">
          <input type="file" accept="audio/*,.m4a,.aac,.opus,.ogg,.webm,.mp3,.wav" hidden
                 ref=${picker} onChange=${onFile} />
          <button type="button" class="link" onClick=${() => picker.current.click()}>
            ${state === "recorded" ? "Attach a different file" : "Attach a file"}
          </button>
          <span class="report-chip">WebM · Ogg · MP3 · M4A · WAV</span>
          ${maxBytes ? html`<span class="report-chip tnum">≤ ${megabytes(maxBytes)}</span>` : ""}
          <span class="report-chip is-private"
                title="The recording stays private; only what was said is shown on the case.">
            <${LockIcon} />Private</span>
        </p>`}
    </div>`;
}
