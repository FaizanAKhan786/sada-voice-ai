/* 16 kHz little-endian signed PCM frames, 20 ms each (640 bytes).
 * AudioWorklet runs outside the main UI thread. The browser applies microphone
 * echo cancellation/noise suppression when available. No cloud STT here.
 */
class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples = new Int16Array(320);
    this.offset = 0;
    this.phase = 0;
    this.lowpass = 0;
  }
  process(inputs) {
    const channels = inputs[0];
    if (!channels || !channels.length) return true;
    const input = channels[0];
    const ratio = 16000 / sampleRate;
    for (let i = 0; i < input.length; i++) {
      // Lightweight smoothing to reduce downsampling aliases. 16 kHz PCM.
      this.lowpass += 0.32 * (input[i] - this.lowpass);
      this.phase += ratio;
      while (this.phase >= 1) {
        this.phase -= 1;
        const value = Math.max(-1, Math.min(1, this.lowpass));
        this.samples[this.offset++] = value < 0 ? Math.round(value * 32768) : Math.round(value * 32767);
        if (this.offset === 320) {
          const frame = this.samples;
          this.port.postMessage(frame.buffer, [frame.buffer]);
          this.samples = new Int16Array(320);
          this.offset = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('pcm-streamer', PcmWorklet);
