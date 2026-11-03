'use strict';

const $ = (id) => document.getElementById(id);
const els = {
  messages: $('messages'), chatInput: $('chatInput'), sendBtn: $('sendBtn'), micBtn: $('micBtn'),
  languageSelect: $('languageSelect'), resetBtn: $('resetBtn'), soundBtn: $('soundBtn'), exportBtn: $('exportBtn'),
  connectionStatus: $('connectionStatus'), connectionTop: $('connectionTop'),
  metricTurns: $('metricTurns'), metricOrders: $('metricOrders'), metricHandoffs: $('metricHandoffs'),
  voiceState: $('voiceState'), voiceOrb: $('voiceOrb'), voiceHeadline: $('voiceHeadline'),
  voiceDescription: $('voiceDescription'), waveform: $('waveform'), ordersList: $('ordersList'),
  toast: $('toast'), inputModeSelect: $('inputModeSelect'), voiceOutputMode: $('voiceOutputMode'),
};

let socket, connected = false, busy = false, speaking = false, listenMode = null, recorder = null;
let recordStream = null, activeRecognition = null, toastTimeout = null, reconnectTimeout = null;
let synthOn = true, config = {stt_enabled: false};
let audioContext = null, audioNode = null, audioSource = null, silentSink = null;
let streamingMessage = null, speechBuffer = '', streamSpeechStarted = false;
let playbackContext = null, currentSource = null, audioTail = Promise.resolve();
let playbackEpoch = 0, latestVoiceTurn = null;


const transcript = [];
const BrowserRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

function notification(message) {
  els.toast.textContent = message;
  els.toast.classList.add('show');
  if (toastTimeout) window.clearTimeout(toastTimeout);
  toastTimeout = window.setTimeout(() => els.toast.classList.remove('show'), 3600);
}

function status(kind) {
  els.voiceOrb.classList.toggle('listening', kind === 'listening');
  els.voiceOrb.classList.toggle('speaking', kind === 'speaking');
  els.waveform.classList.toggle('active', kind === 'listening' || kind === 'speaking');
  els.voiceState.classList.toggle('recording', kind === 'listening');
  if (kind === 'listening') {
    els.voiceHeadline.textContent = 'Listening to you…';
    els.voiceDescription.textContent = 'Speak naturally in Arabic or English. Tap the mic to stop.';
    els.voiceState.lastChild.textContent = ' Listening';
  } else if (kind === 'speaking') {
    els.voiceHeadline.textContent = 'Speaking response';
    els.voiceDescription.textContent = 'SADA is reading the response aloud.';
    els.voiceState.lastChild.textContent = ' Speaking';
  } else if (kind === 'processing') {
    els.voiceHeadline.textContent = 'Thinking…';
    els.voiceDescription.textContent = 'Finding the right support workflow.';
    els.voiceState.lastChild.textContent = ' Processing';
  } else {
    els.voiceHeadline.textContent = 'Ready to listen';
    els.voiceDescription.textContent = 'Select the microphone to start a voice conversation.';
    els.voiceState.lastChild.textContent = ' Voice ready';
  }
  els.micBtn.classList.toggle('recording', kind === 'listening');
  els.micBtn.setAttribute('aria-label', kind === 'listening' ? 'Stop speaking' : 'Start speaking');
}

function appendTextWithEmphasis(node, text) {
  // Avoid innerHTML when displaying data from the server.
  text.split(/(\*\*[^*]+\*\*)/g).forEach(part => {
    if (part.startsWith('**') && part.endsWith('**')) {
      const strong = document.createElement('strong');
      strong.textContent = part.slice(2, -2);
      node.appendChild(strong);
    } else node.appendChild(document.createTextNode(part));
  });
}

function addMessage(role, text, extra = {}) {
  const row = document.createElement('div'); row.className = `message-row ${role === 'user' ? 'user' : 'bot'}`;
  const avatar = document.createElement('div'); avatar.className = `message-avatar ${role === 'user' ? 'user-avatar' : ''}`;
  avatar.textContent = role === 'user' ? '●' : '✦';
  const group = document.createElement('div'); group.className = 'message-group';
  const sender = document.createElement('div'); sender.className = 'sender-name';
  sender.textContent = role === 'user' ? 'You · Just now' : 'SADA · Just now';
  const bubble = document.createElement('div'); bubble.className = `bubble ${role === 'user' ? '' : 'bot-bubble'}`;
  appendTextWithEmphasis(bubble, text);
  if (extra.language === 'ar') bubble.dir = 'rtl';
  const label = document.createElement('span'); label.className = 'message-label';
  label.textContent = role === 'user' ? 'YOUR MESSAGE' : `${(extra.intent || 'ASSISTANT').toUpperCase().replaceAll('_', ' ')}${extra.latency_ms !== undefined ? ' · ' + extra.latency_ms + ' MS' : ''}`;
  group.append(sender, bubble, label); row.append(avatar, group);
  els.messages.appendChild(row); els.messages.scrollTop = els.messages.scrollHeight;
  const item = {role, text, time: new Date().toISOString(), ...extra};
  transcript.push(item);
  return {bubble, label, item};
}

function updateConnection(online) {
  connected = online;
  els.connectionStatus.textContent = online ? 'Online · Ready to help' : 'Disconnected · Reconnecting';
  els.connectionTop.textContent = online ? 'Agent connected' : 'Agent offline';
  document.querySelectorAll('.green-pulse').forEach(el => el.classList.toggle('offline', !online));
  els.sendBtn.disabled = !online || busy;
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${protocol}//${location.host}/ws/live`);
  socket.addEventListener('open', () => {
    updateConnection(true);
    socket.send(JSON.stringify({type:'set_language', language:els.languageSelect.value}));
    socket.send(JSON.stringify({type:'set_voice_output', enabled:synthOn}));
  });
  socket.addEventListener('message', event => {
    let payload;
    try { payload = JSON.parse(event.data); } catch { return; }
    if (payload.type === 'answer_start') {
      // A local Ollama answer can be read aloud sentence-by-sentence.
      if (streamingMessage) streamingMessage = null;
      latestVoiceTurn = payload.turn_id;
      streamingMessage = {turn_id: payload.turn_id, ...addMessage('assistant', '', {language:payload.language}), text:''};
      speechBuffer = ''; streamSpeechStarted = false;
      status('processing');
    } else if (payload.type === 'answer_delta') {
      if (streamingMessage?.turn_id !== payload.turn_id) return;
      streamingMessage.text += payload.delta;
      streamingMessage.bubble.textContent = streamingMessage.text;
      streamingMessage.item.text = streamingMessage.text;
      els.messages.scrollTop = els.messages.scrollHeight;
      speechBuffer += payload.delta;
      if (listenMode !== 'cloud')
        streamSpeechChunks(false, els.languageSelect.value === 'ar' ? 'ar' : detectArabic(streamingMessage.text) ? 'ar' : 'en');
    } else if (payload.type === 'answer') {
      latestVoiceTurn = payload.turn_id;
      busy = false; els.sendBtn.disabled = false;
      const wasStreamed = streamingMessage && streamingMessage.turn_id === payload.turn_id;
      if (wasStreamed) {
        streamingMessage.bubble.textContent = payload.text;
        streamingMessage.bubble.dir = payload.language === 'ar' ? 'rtl' : 'ltr';
        streamingMessage.item.text = payload.text;
        streamingMessage.item.intent = payload.intent;
        streamingMessage.label.textContent = (payload.intent || 'ASSISTANT').toUpperCase().replaceAll('_', ' ');
        if (!['local_ollama_unverified', 'hosted_groq_unverified'].includes(payload.source)) {
          // A failed model stream must replace partially spoken content.
          if (listenMode !== 'cloud') { cancelSpeech(); speak(payload.text, payload.language); }
          speechBuffer = '';
        } else if (listenMode !== 'cloud') streamSpeechChunks(true, payload.language);
        streamingMessage = null;
      } else {
        addMessage('assistant', payload.text, {intent:payload.intent, language:payload.language, latency_ms:payload.latency_ms, case_id:payload.case_id});
        if (listenMode !== 'cloud') speak(payload.text, payload.language);
      }
      refreshStats();
      if (payload.handoff) notification('Simulated handoff created. No real support team is connected.');
      if (!synthOn || (listenMode !== 'cloud' && !('speechSynthesis' in window))) status('ready');
    } else if (payload.type === 'transcript') {
      busy = true; els.sendBtn.disabled = true;
      addMessage('user', payload.text, {language: payload.language, mode:listenMode === 'cloud' ? 'hosted_stt' : 'local_streaming_stt'});
      status('processing');
    } else if (payload.type === 'voice_audio') {
      if (listenMode === 'cloud' && synthOn && latestVoiceTurn === payload.turn_id)
        enqueueHostedSpeech(payload.audio_base64);
    } else if (payload.type === 'voice_fallback') {
      if (listenMode === 'cloud' && synthOn && latestVoiceTurn === payload.turn_id) {
        notification('Hosted voice temporarily unavailable. Using browser speech.');
        speak(payload.text, payload.language);
      }
    } else if (payload.type === 'speech_started') {
      cancelSpeech(); streamingMessage = null; speechBuffer = '';
      busy = false; els.sendBtn.disabled = false; status('listening');
    } else if (payload.type === 'speech_ended') {
      status('processing');
    } else if (payload.type === 'interrupted') {
      cancelSpeech(); streamingMessage = null; speechBuffer = '';
      busy = false; els.sendBtn.disabled = false;
    } else if (payload.type === 'no_speech') {
      busy = false; els.sendBtn.disabled = false;
      notification('No speech recognized. Try again.'); status('ready');
    } else if (payload.type === 'error') {
      busy = false; els.sendBtn.disabled = false; status('ready'); notification(payload.message || 'A request failed.');
    } else if (payload.type === 'reset_complete') {
      notification('New session started.');
    }
  });
  socket.addEventListener('close', () => {
    if (listenMode === 'stream' || listenMode === 'cloud') void stopStreaming({flush:false});
    updateConnection(false); busy = false; status('ready');
    reconnectTimeout = window.setTimeout(connect, 2500);
  });
  socket.addEventListener('error', () => updateConnection(false));
}

function sendMessage(text = els.chatInput.value) {
  const cleaned = text.trim();
  if (!cleaned || (busy && listenMode !== 'stream')) return;
  if (!connected) { notification('Agent is reconnecting. Please try again.'); return; }
  cancelSpeech();
  addMessage('user', cleaned, {language: els.languageSelect.value});
  els.chatInput.value = ''; els.chatInput.style.height = 'auto';
  busy = true; els.sendBtn.disabled = true; status('processing');
  socket.send(JSON.stringify({type:'message', text:cleaned}));
}

function detectArabic(text) { return /[\u0600-\u06FF]/.test(text); }

function cancelSpeech() {
  playbackEpoch++;
  try { currentSource?.stop(); } catch { /* Already stopped. */ }
  currentSource = null;
  audioTail = Promise.resolve();
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  speaking = false; streamSpeechStarted = false; speechBuffer = '';
}

function enqueueHostedSpeech(base64wav) {
  const epoch = playbackEpoch;
  audioTail = audioTail.then(async () => {
    if (epoch !== playbackEpoch || listenMode !== 'cloud') return;
    try {
      if (!playbackContext) playbackContext = new AudioContext();
      const binary = atob(base64wav);
      const bytes = new Uint8Array(binary.length);
      for (let i=0; i<binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const audio = await playbackContext.decodeAudioData(bytes.buffer);
      if (epoch !== playbackEpoch || listenMode !== 'cloud') return;
      await playbackContext.resume();
      if (epoch !== playbackEpoch || listenMode !== 'cloud') return;
      await new Promise(resolve => {
        const source = playbackContext.createBufferSource(); currentSource = source;
        source.buffer = audio;
        source.connect(playbackContext.destination);
        source.onended = () => {
          if (currentSource === source) {
            currentSource = null;
            if (epoch === playbackEpoch && listenMode === 'cloud') status('listening');
          }
          resolve();
        };
        status('speaking'); source.start();
      });
    } catch (error) {
      if (epoch === playbackEpoch) notification('Unable to play hosted voice audio.');
    }
  });
}

function streamSpeechChunks(force, language) {
  if (!synthOn || !('speechSynthesis' in window)) { if (force) speechBuffer = ''; return; }
  // Read completed sentences as they arrive; avoid tiny word-by-word speech.
  while (speechBuffer.length) {
    const match = speechBuffer.match(/^[\s\S]*?[.!?؟。](?:\s|$)/);
    const cutoff = match ? match[0].length : (force ? speechBuffer.length : 0);
    if (!cutoff) break;
    const part = speechBuffer.slice(0, cutoff).trim();
    speechBuffer = speechBuffer.slice(cutoff);
    if (part) queueSpeech(part, language);
  }
}

function queueSpeech(text, language) {
  const utterance = new SpeechSynthesisUtterance(text.replaceAll('**', ''));
  utterance.lang = language === 'ar' ? 'ar-SA' : 'en-US';
  utterance.rate = language === 'ar' ? 0.9 : 0.97;
  utterance.onstart = () => { speaking = true; status('speaking'); };
  utterance.onend = utterance.onerror = () => { speaking = false; if (!window.speechSynthesis.speaking) status('ready'); };
  window.speechSynthesis.speak(utterance);
  streamSpeechStarted = true;
}

function speak(text, language) {
  if (!synthOn || !('speechSynthesis' in window)) return;
  cancelSpeech(); queueSpeech(text, language);
}

async function stopStreaming({flush=true} = {}) {
  cancelSpeech();
  listenMode = null;
  try { audioNode?.port.close(); audioNode?.disconnect(); audioSource?.disconnect(); silentSink?.disconnect(); } catch { /* Audio context closed. */ }
  if (audioContext) await audioContext.close().catch(() => {});
  if (playbackContext) await playbackContext.close().catch(() => {});
  playbackContext = null;
  recordStream?.getTracks().forEach(track => track.stop());
  audioNode = audioSource = silentSink = audioContext = recordStream = null;
  if (flush && connected) socket.send(JSON.stringify({type:'flush'}));
  status('ready');
}

async function startStreaming(mode = 'stream') {
  const available = mode === 'cloud' ? config.cloud_voice_enabled : config.stt_enabled;
  if (!available || !connected) { notification('This speech mode is not available on the server.'); return; }
  try {
    recordStream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation:true, noiseSuppression:true, autoGainControl:true}, video:false});
    audioContext = new AudioContext();
    if (mode === 'cloud') { playbackContext = new AudioContext(); await playbackContext.resume(); }
    await audioContext.audioWorklet.addModule('/static/pcm-worklet.js');
    audioSource = audioContext.createMediaStreamSource(recordStream);
    audioNode = new AudioWorkletNode(audioContext, 'pcm-streamer');
    silentSink = audioContext.createGain(); silentSink.gain.value = 0;
    audioSource.connect(audioNode); audioNode.connect(silentSink); silentSink.connect(audioContext.destination);
    audioNode.port.onmessage = event => {
      if (socket?.readyState === WebSocket.OPEN && socket.bufferedAmount < 512000)
        socket.send(event.data); // ArrayBuffer, 16k mono PCM16 20ms.
    };
    listenMode = mode; status('listening');
    notification(mode === 'cloud' ? 'Hosted AI voice is active. Speak English or Arabic. Headphones recommended.' : 'Local live audio enabled. Headphones recommended.');
  } catch (error) {
    await stopStreaming({flush:false});
    notification(`Live microphone unavailable: ${error.message}`);
  }
}

function stopListening() {
  if (listenMode === 'stream' || listenMode === 'cloud') { void stopStreaming(); return; }
  if (listenMode === 'recognition' && activeRecognition) activeRecognition.stop();
  if (listenMode === 'recording' && recorder && recorder.state !== 'inactive') recorder.stop();
  listenMode = null; status('ready');
}

async function startRecording() {
  try {
    if (!navigator.mediaDevices || !window.MediaRecorder) throw new Error('Audio recording is unsupported in this browser.');
    recordStream = await navigator.mediaDevices.getUserMedia({audio: true});
    const pieces = [];
    recorder = new MediaRecorder(recordStream);
    const mime = recorder.mimeType || 'audio/webm';
    recorder.ondataavailable = e => { if (e.data.size) pieces.push(e.data); };
    recorder.onstop = async () => {
      recordStream?.getTracks().forEach(t => t.stop()); recordStream = null;
      if (!pieces.length) { notification('No audio captured.'); status('ready'); return; }
      status('processing');
      const subtype = mime.includes('mp4') ? 'mp4' : mime.includes('ogg') ? 'ogg' : 'webm';
      const form = new FormData(); form.append('file', new Blob(pieces, {type:mime}), `voice.${subtype}`);
      try {
        const url = `/api/transcribe?language=${encodeURIComponent(els.languageSelect.value)}`;
        const response = await fetch(url, {method:'POST', body:form});
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Transcription failed.');
        if (!data.text) { notification('No speech detected. Try again.'); status('ready'); return; }
        status('ready'); sendMessage(data.text);
      } catch (error) { notification(error.message); status('ready'); }
    };
    listenMode = 'recording'; recorder.start(); status('listening');
  } catch (error) { notification(error.message || 'Microphone access denied.'); status('ready'); }
}

function startRecognition() {
  const recog = new BrowserRecognition(); activeRecognition = recog;
  recog.lang = els.languageSelect.value === 'ar' ? 'ar-SA' : 'en-US';
  recog.continuous = false; recog.interimResults = true;
  let final = '';
  recog.onresult = event => {
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) final += event.results[i][0].transcript;
      else interim += event.results[i][0].transcript;
    }
    els.chatInput.value = final || interim;
  };
  recog.onerror = event => {
    if (event.error !== 'no-speech' && event.error !== 'aborted') notification(`Speech recognition: ${event.error}`);
  };
  recog.onend = () => {
    if (activeRecognition !== recog) return;
    activeRecognition = null; listenMode = null; status('ready');
    const recognized = final.trim();
    if (recognized) sendMessage(recognized);
  };
  try { recog.start(); listenMode = 'recognition'; status('listening'); }
  catch (error) { notification(error.message); status('ready'); }
}

function toggleMic() {
  if (listenMode) { stopListening(); return; }
  if (busy) { notification('Complete the current response first.'); return; }
  if (els.inputModeSelect.value === 'cloud') { void startStreaming('cloud'); return; }
  if (els.inputModeSelect.value === 'stream') { void startStreaming('stream'); return; }
  if (els.inputModeSelect.value === 'local' && config.stt_enabled) startRecording();
  else if (BrowserRecognition) startRecognition();
  else if (config.stt_enabled) startRecording();
  else notification('Voice recognition needs Chrome/Edge or optional offline STT. Text chat is ready.');
}

async function refreshStats() {
  try {
    const resp = await fetch('/api/stats'); if (!resp.ok) return;
    const metrics = await resp.json();
    els.metricTurns.textContent = metrics.total_turns;
    els.metricOrders.textContent = metrics.orders_checked;
    els.metricHandoffs.textContent = metrics.handoffs;
  } catch { /* Keep chat functional if metrics temporarily fail. */ }
}

async function initData() {
  try {
    const [configResponse, ordersResponse] = await Promise.all([fetch('/api/config'), fetch('/api/demo-orders')]);
    if (configResponse.ok) config = await configResponse.json();
    const modelNotice = document.getElementById('modelStatus');
    if (modelNotice) modelNotice.textContent = config.hosted_llm_enabled
      ? 'AI responses enabled · Hosted Groq model · Synthetic policies only'
      : 'Scripted demo replies · Hosted AI awaiting server API key';
    if (ordersResponse.ok) {
      const orders = await ordersResponse.json();
      els.ordersList.textContent = '';
      orders.forEach(order => {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'order-item';
        const symbol = document.createElement('span'); symbol.className = 'order-symbol'; symbol.textContent = '▣';
        const info = document.createElement('span'); info.className = 'order-info';
        const title = document.createElement('strong'); title.textContent = order.id;
        const sub = document.createElement('small'); sub.textContent = `${order.item} · ${order.status}`;
        info.append(title, sub);
        const arrow = document.createElement('span'); arrow.className = 'order-arrow'; arrow.textContent = '↗';
        button.append(symbol, info, arrow);
        button.addEventListener('click', () => sendMessage(`Track my order ${order.id}`));
        els.ordersList.appendChild(button);
      });
    }
    els.inputModeSelect.querySelector('[value="browser"]').disabled = !BrowserRecognition;
    els.inputModeSelect.querySelector('[value="local"]').disabled = !config.stt_enabled;
    els.inputModeSelect.querySelector('[value="stream"]').disabled = !config.stt_enabled || !window.AudioWorkletNode;
    if (!BrowserRecognition && config.stt_enabled) els.inputModeSelect.value = 'local';
    els.inputModeSelect.querySelector('[value="cloud"]').disabled = !config.cloud_voice_enabled || !window.AudioWorkletNode;
  if (config.cloud_voice_enabled && window.AudioWorkletNode) els.inputModeSelect.value = 'cloud';
  else if (!BrowserRecognition && !config.stt_enabled) els.inputModeSelect.disabled = true;
  els.voiceOutputMode.textContent = config.cloud_tts_enabled ? 'Hosted English / العربية' : 'Browser speech';
  } catch { els.ordersList.textContent = 'Sample records unavailable.'; }
  refreshStats();
}

els.sendBtn.addEventListener('click', () => sendMessage());
els.chatInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendMessage(); }
});
els.chatInput.addEventListener('input', () => {
  els.chatInput.style.height = 'auto';
  els.chatInput.style.height = `${Math.min(els.chatInput.scrollHeight, 120)}px`;
});
els.micBtn.addEventListener('click', toggleMic);
els.languageSelect.addEventListener('change', () => {
  if (connected) socket.send(JSON.stringify({type:'set_language', language:els.languageSelect.value}));
  notification(els.languageSelect.value === 'auto' ? 'Language auto-detection enabled for typed messages.' : 'Conversation language changed.');
});
els.soundBtn.addEventListener('click', () => {
  synthOn = !synthOn; els.soundBtn.classList.toggle('on', synthOn);
  els.soundBtn.title = synthOn ? 'Mute spoken replies' : 'Enable spoken replies';
  if (connected) socket.send(JSON.stringify({type:'set_voice_output', enabled:synthOn}));
  if (!synthOn) { cancelSpeech(); status('ready'); }
  notification(synthOn ? 'Spoken replies enabled.' : 'Spoken replies muted.');
});
els.resetBtn.addEventListener('click', () => {
  if (!connected) { notification('Agent is reconnecting.'); return; }
  if (listenMode) stopListening();
  cancelSpeech(); streamingMessage = null; speechBuffer = '';
  busy = false; els.sendBtn.disabled = false; status('ready');
  socket.send(JSON.stringify({type:'reset'}));
  transcript.length = 0;
  els.messages.textContent = '';
  const stamp = document.createElement('div'); stamp.className = 'day-stamp';
  const label = document.createElement('span'); label.textContent = 'NEW CONVERSATION'; stamp.appendChild(label);
  els.messages.appendChild(stamp);
  addMessage('assistant', "Hello! I'm SADA. Let's start a new sample support conversation.", {intent:'greeting'});
});
els.exportBtn.addEventListener('click', () => {
  if (!transcript.length) { notification('Send a message first to export a transcript.'); return; }
  const blob = new Blob([JSON.stringify({project:'SADA Voice AI', demo:true, conversation:transcript}, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = `sada-demo-session-${Date.now()}.json`; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => sendMessage(button.dataset.prompt)));
window.addEventListener('beforeunload', () => { if (reconnectTimeout) clearTimeout(reconnectTimeout); });

connect();
initData();
