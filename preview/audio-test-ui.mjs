/* P6.3 optional Audio Test adapter.
 *
 * The page does not own a speech system. It samples a user-selected local
 * audio file with Web Audio, emits normalized RMS frames, and leaves the
 * controller as the only owner of mouth motion.
 */

"use strict";

export const AUDIO_TEST_VERSION = "P6.3";

export function rmsFromTimeDomain(samples) {
  if (!samples?.length) return 0;
  let sum = 0;
  for (const sample of samples) {
    const centered = (Number(sample) - 128) / 128;
    sum += centered * centered;
  }
  return Math.max(0, Math.min(1, Math.sqrt(sum / samples.length)));
}

function emit(window, type, detail = {}) {
  if (typeof window?.dispatchEvent !== "function" || typeof CustomEvent === "undefined") return;
  window.dispatchEvent(new CustomEvent(type, { detail }));
}

export function bindAudioTest({ document, window } = {}) {
  const fileInput = document?.getElementById?.("audioTestFile");
  const playButton = document?.getElementById?.("audioTestPlay");
  const stopButton = document?.getElementById?.("audioTestStop");
  const status = document?.getElementById?.("audioTestStatus");
  if (!fileInput || !playButton || !stopButton) return;

  let audio = null;
  let objectUrl = null;
  let context = null;
  let analyser = null;
  let source = null;
  let raf = 0;
  let samples = null;

  function setStatus(message) {
    if (status) status.textContent = message;
  }

  function stop({ reset = true } = {}) {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    audio?.pause();
    if (reset && audio) audio.currentTime = 0;
    emit(window, "rigstudio:lipsync:stop");
    playButton.disabled = !audio;
    stopButton.disabled = true;
    setStatus(audio ? "Ready" : "Choose an audio file");
  }

  function sample() {
    if (!analyser || !audio || audio.paused) return;
    analyser.getByteTimeDomainData(samples);
    emit(window, "rigstudio:lipsync:rms", { rms: rmsFromTimeDomain(samples), source: "audio-test" });
    raf = requestAnimationFrame(sample);
  }

  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    stop();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    audio = new Audio(objectUrl);
    audio.preload = "auto";
    audio.addEventListener("ended", () => stop());
    playButton.disabled = false;
    stopButton.disabled = true;
    setStatus(`${file.name} · Ready`);
  });

  playButton.addEventListener("click", async () => {
    if (!audio) return;
    try {
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextCtor) throw new Error("Web Audio API unavailable");
      context ||= new AudioContextCtor();
      if (context.state === "suspended") await context.resume();
      if (!source) {
        source = context.createMediaElementSource(audio);
        analyser = context.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.12;
        samples = new Uint8Array(analyser.fftSize);
        source.connect(analyser);
        analyser.connect(context.destination);
      }
      await audio.play();
      emit(window, "rigstudio:lipsync:enabled", { enabled: true, source: "audio-test" });
      stopButton.disabled = false;
      setStatus(`${audio.src ? "Playing" : "Audio"} · RMS lip-sync ON`);
      if (!raf) sample();
    } catch (error) {
      stop();
      setStatus(`Audio test unavailable: ${error.message}`);
    }
  });

  stopButton.addEventListener("click", () => stop());
}

if (typeof document !== "undefined" && typeof window !== "undefined")
  bindAudioTest({ document, window });

