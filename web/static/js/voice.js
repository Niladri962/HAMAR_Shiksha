/* Voice assistant helpers.
   - Speech to text: the browser records 16 kHz mono WAV and sends it to this
     server's local Whisper model (/api/voice/transcribe). Audio is not stored.
   - Text to speech: the device's own voices (speechSynthesis); on-device voices
     are preferred over online ones. */
(function () {
  "use strict";
  const HS = window.HS;
  const el = HS.el;
  const RATE = 16000;
  const MAX_SECONDS = 30;

  const canRecord = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && (window.AudioContext || window.webkitAudioContext));
  const canSpeak = () => "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;

  // ------------------------------------------------------------ recording --
  function toWav(chunks, inRate) {
    const length = chunks.reduce((n, c) => n + c.length, 0);
    const pcm = new Float32Array(length);
    let off = 0;
    chunks.forEach((c) => { pcm.set(c, off); off += c.length; });
    const ratio = inRate / RATE;
    const outLen = Math.floor(length / ratio);
    const buf = new ArrayBuffer(44 + outLen * 2);
    const v = new DataView(buf);
    const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + outLen * 2, true); str(8, "WAVE"); str(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, RATE, true);
    v.setUint32(28, RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data");
    v.setUint32(40, outLen * 2, true);
    for (let i = 0; i < outLen; i++) {
      // average the input samples that fall into this output sample (simple low-pass)
      const a = Math.floor(i * ratio), b = Math.min(length, Math.floor((i + 1) * ratio)) || a + 1;
      let sum = 0;
      for (let j = a; j < b; j++) sum += pcm[j];
      const s = Math.max(-1, Math.min(1, sum / Math.max(1, b - a)));
      v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  async function startRecording(onTick) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const src = ctx.createMediaStreamSource(stream);
    const node = ctx.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    const started = Date.now();
    let done = null;
    node.onaudioprocess = (e) => {
      chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      const secs = (Date.now() - started) / 1000;
      if (onTick) onTick(secs);
      if (secs >= MAX_SECONDS && done) done();
    };
    src.connect(node);
    node.connect(ctx.destination);
    return new Promise((resolveStart) => {
      const stopped = new Promise((resolve) => {
        done = () => {
          done = null;
          node.disconnect(); src.disconnect();
          stream.getTracks().forEach((t) => t.stop());
          const rate = ctx.sampleRate;
          ctx.close().catch(() => {});
          resolve(toWav(chunks, rate));
        };
      });
      resolveStart({ stop: () => { if (done) done(); return stopped; }, stopped });
    });
  }

  async function transcribe(blob, lang) {
    const form = new FormData();
    form.append("audio", blob, "question.wav");
    form.append("language", lang === "hi" ? "hi" : "en");
    return HS.api("/api/voice/transcribe", { method: "POST", form });
  }

  /** A "Speak" button that records, transcribes on the server and puts the
      text into `target` for the user to check before sending. */
  function micButton(target, opts = {}) {
    const status = el("span", { class: "voice-status small", role: "status", "aria-live": "polite" });
    const btn = el("button", { type: "button", class: "voice-btn" });
    const wrap = el("span", { class: "voice-wrap" }, btn, status);
    let rec = null;
    const label = (recording) => {
      HS.mount(btn, el("span", { "aria-hidden": "true" }, recording ? "■" : "🎤"), " ", HS.t(recording ? "voice_stop" : "voice_speak"));
      btn.classList.toggle("recording", recording);
      btn.setAttribute("aria-pressed", String(recording));
    };
    label(false);
    if (!canRecord() || (HS.platform && HS.platform.voice && !HS.platform.voice.speech_to_text)) {
      btn.disabled = true;
      btn.title = HS.t("voice_no_mic");
      return wrap;
    }
    btn.addEventListener("click", async () => {
      if (rec) {
        const r = rec; rec = null;
        label(false);
        btn.disabled = true;
        status.textContent = HS.t("voice_transcribing");
        try {
          const out = await transcribe(await r.stop(), opts.lang ? opts.lang() : HS.lang);
          if (!out.text) { status.textContent = HS.t("voice_no_speech"); return; }
          target.value = (target.value.trim() ? target.value.trim() + " " : "") + out.text;
          target.dispatchEvent(new Event("input"));
          target.focus();
          status.textContent = HS.t("voice_check");
          if (opts.onText) opts.onText(out.text);
        } catch (e) { status.textContent = e.message; }
        finally { btn.disabled = false; }
        return;
      }
      try {
        HS.voice.stopSpeaking();
        rec = await startRecording((s) => { status.textContent = `${HS.t("voice_listening")} ${Math.floor(s)}s`; });
        label(true);
        status.textContent = HS.t("voice_listening");
        rec.stopped.then(() => { if (rec) btn.click(); }); // auto-stop at the time limit
      } catch (_) {
        rec = null;
        label(false);
        status.textContent = HS.t("voice_no_mic");
      }
    });
    return wrap;
  }

  // ------------------------------------------------------------- speaking --
  let voices = [];
  const loadVoices = () => { voices = canSpeak() ? window.speechSynthesis.getVoices() : []; };
  if (canSpeak()) { loadVoices(); window.speechSynthesis.addEventListener?.("voiceschanged", loadVoices); }

  function pickVoice(lang) {
    const want = lang === "hi" ? ["hi-IN", "hi"] : ["en-IN", "en-GB", "en-US", "en"];
    for (const tag of want) {
      const matches = voices.filter((v) => v.lang && v.lang.replace("_", "-").toLowerCase().startsWith(tag.toLowerCase()));
      if (matches.length) return matches.find((v) => v.localService) || matches[0];
    }
    return null;
  }
  const detectLang = (text) => ((text.match(/[ऀ-ॿ]/g) || []).length > text.length * 0.2 ? "hi" : "en");
  const clean = (text) => String(text).replace(/\[(?:S|स)\s*\d+\]/gi, "").replace(/[*_#`>]/g, " ").replace(/\s+/g, " ").trim();

  function speak(text, lang, onEnd) {
    if (!canSpeak()) return false;
    const l = lang || detectLang(text);
    const voice = pickVoice(l);
    if (!voice) return false;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(clean(text));
    u.voice = voice;
    u.lang = voice.lang;
    u.rate = 0.95;
    u.onend = u.onerror = () => onEnd && onEnd();
    window.speechSynthesis.speak(u);
    return true;
  }
  function stopSpeaking() { if (canSpeak()) window.speechSynthesis.cancel(); }

  /** A "Listen" button that reads `text` aloud with a device voice. */
  function speakButton(text) {
    const lang = detectLang(text);
    const btn = el("button", { type: "button", class: "voice-btn small-btn" });
    let speaking = false;
    const label = () => HS.mount(btn, el("span", { "aria-hidden": "true" }, speaking ? "■" : "🔊"), " ",
      HS.t(speaking ? "voice_stop_reading" : "voice_listen"));
    label();
    if (!canSpeak()) { btn.disabled = true; btn.title = HS.t("voice_no_tts"); return btn; }
    btn.addEventListener("click", () => {
      if (speaking) { stopSpeaking(); speaking = false; label(); return; }
      loadVoices();
      if (!speak(text, lang, () => { speaking = false; label(); })) { HS.toast(HS.t("voice_no_tts"), true); return; }
      speaking = true; label();
    });
    return btn;
  }

  const autoRead = {
    get: () => { try { return localStorage.getItem("hs_voice_autoread") === "1"; } catch (_) { return false; } },
    set: (on) => { try { localStorage.setItem("hs_voice_autoread", on ? "1" : "0"); } catch (_) { /* ignore */ } },
  };

  HS.voice = { canRecord, canSpeak, micButton, speakButton, speak, stopSpeaking, autoRead };
})();
