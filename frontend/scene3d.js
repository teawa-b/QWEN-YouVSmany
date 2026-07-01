// You Vs Many — Three.js scene player.
// Drives the renderer-neutral SceneManifest as a real 3D stage: a rectangular
// debate table with 3 challengers on one side and the lone protagonist on the
// other. Characters are skinned Mixamo humanoids (FBX) driven by an animation
// mixer (seated idle <-> talking crossfade), camera cuts + captions from the
// manifest, and per-character voices (Qwen Cloud CosyVoice audio when the
// manifest carries audio_refs, else browser SpeechSynthesis so it still talks).

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { clone as skeletonClone } from "three/addons/utils/SkeletonUtils.js";

const PALETTE = [0xf0997b, 0x5dcaa5, 0xd4537e, 0xefbf4f, 0x85b7eb];
const ACCENT = 0x7b97ff;
const CHAR_HEIGHT = 1.7;   // target standing height (m) for scaling the Mixamo rig
const CHAIR_HEIGHT = 0.92; // real-ish chair height (m); seat lands ~0.46

// Themed studio look per premade set id (matches the manifest's scene_template).
const THEMES = {
  clean_white:     { bg: 0xeef1f6, floor: 0xdfe4ec, fog: 0xeef1f6, key: 1.15, amb: 0.9, dark: false },
  studio_midnight: { bg: 0x0c1530, floor: 0x10183a, fog: 0x0c1530, key: 1.3,  amb: 0.6, dark: true },
  amber_forum:     { bg: 0x241405, floor: 0x3a2510, fog: 0x241405, key: 1.25, amb: 0.6, dark: true },
};
const DEFAULT_THEME = THEMES.studio_midnight;

// ---- asset loaders (cached across episodes) ----
const gltfLoader = new GLTFLoader();
const fbxLoader = new FBXLoader();
const glbCache = new Map();
function loadGLB(url) {
  if (!glbCache.has(url)) glbCache.set(url, new Promise((res, rej) => gltfLoader.load(url, res, undefined, rej)));
  return glbCache.get(url);
}
function loadFBX(url) {
  return new Promise((res, rej) => fbxLoader.load(url, res, undefined, rej));
}

// One shared character rig + its animation clips, loaded once.
let characterAssets = null;
async function getCharacterAssets() {
  if (characterAssets) return characterAssets;
  const [rig, idle, talk] = await Promise.all([
    loadFBX("/assets/characters/remy.fbx"),
    loadFBX("/assets/characters/anim_idle.fbx"),
    loadFBX("/assets/characters/anim_talking.fbx"),
  ]);
  characterAssets = { rig, idle: idle.animations[0], talk: talk.animations[0] };
  return characterAssets;
}

// Scale + ground a loaded object: longest horizontal axis -> targetLen, sit on y=0,
// optionally rotate so the long axis runs along X. Returns {width,depth,height}.
function fitToFloor(obj, targetLen, alignLongToX = false) {
  let box = new THREE.Box3().setFromObject(obj);
  let size = box.getSize(new THREE.Vector3());
  if (alignLongToX && size.z > size.x) {
    obj.rotation.y = Math.PI / 2;
    obj.updateMatrixWorld(true);
    box = new THREE.Box3().setFromObject(obj);
    size = box.getSize(new THREE.Vector3());
  }
  const longest = Math.max(size.x, size.z) || 1;
  obj.scale.multiplyScalar(targetLen / longest);
  obj.updateMatrixWorld(true);
  box = new THREE.Box3().setFromObject(obj);
  const center = box.getCenter(new THREE.Vector3());
  obj.position.x -= center.x;
  obj.position.z -= center.z;
  obj.position.y -= box.min.y;
  obj.updateMatrixWorld(true);
  size = new THREE.Box3().setFromObject(obj).getSize(new THREE.Vector3());
  return { width: size.x, depth: size.z, height: size.y };
}

// Scale an object uniformly so its overall height == targetH, centered on x/z,
// grounded at y=0. Returns the applied scale.
function fitToHeight(obj, targetH) {
  let box = new THREE.Box3().setFromObject(obj);
  const h = box.getSize(new THREE.Vector3()).y || 1;
  obj.scale.multiplyScalar(targetH / h);
  obj.updateMatrixWorld(true);
  box = new THREE.Box3().setFromObject(obj);
  const c = box.getCenter(new THREE.Vector3());
  obj.position.x -= c.x;
  obj.position.z -= c.z;
  obj.position.y -= box.min.y;
  obj.updateMatrixWorld(true);
  return targetH / h;
}

const V = (x, y, z) => new THREE.Vector3(x, y, z);

class StagePlayer {
  constructor(host, data) {
    this.host = host;
    this.data = data;
    this.scene = data.scene;
    this.segments = (this.scene.segments || []).filter((s) => (s.end_s - s.start_s) > 0.01);
    this.cur = -1;
    this.playing = false;
    this.ready = false;
    this.disposed = false;
    this.chars = new Map(); // character_id -> {group, model, mixer, idle, talk, color, role, ring, plate}
    this.director = true;
    this.colorFor = data.colorFor;
    this.nameFor = data.nameFor;

    this._buildDom();
    this._initThree();
    this._buildWorld()
      .then(() => { this.ready = true; this._frameWide(); this._setReadyUI(); })
      .catch((e) => this._fail(e));
    this._loop();
  }

  _buildDom() {
    this.host.innerHTML = "";
    const cv = document.createElement("div");
    cv.className = "s3d-canvas";
    this.host.appendChild(cv);
    this.canvasHost = cv;

    const crop = document.createElement("div");
    crop.className = "s3d-crop";
    crop.title = "9:16 short crop-safe region";
    cv.appendChild(crop);

    const load = document.createElement("div");
    load.className = "s3d-loading";
    load.innerHTML = `<span class="s3d-spin"></span> Loading humanoid cast…`;
    cv.appendChild(load);
    this.loadEl = load;

    const cap = document.createElement("div");
    cap.className = "s3d-caption";
    cv.appendChild(cap);
    this.captionEl = cap;

    const badge = document.createElement("div");
    badge.className = "s3d-shot";
    cv.appendChild(badge);
    this.shotEl = badge;

    const bar = document.createElement("div");
    bar.className = "s3d-controls";
    bar.innerHTML = `
      <button class="s3d-btn s3d-play" disabled>▶ Play scene</button>
      <button class="s3d-btn s3d-restart" title="Restart">⟲</button>
      <div class="s3d-progress"><i></i></div>
      <span class="s3d-seg">loading…</span>
      <button class="s3d-btn s3d-free" title="Toggle free camera">🎥 Director</button>`;
    this.host.appendChild(bar);
    this.playBtn = bar.querySelector(".s3d-play");
    this.progFill = bar.querySelector(".s3d-progress > i");
    this.segLabel = bar.querySelector(".s3d-seg");
    this.freeBtn = bar.querySelector(".s3d-free");

    this.playBtn.onclick = () => (this.playing ? this.pause() : this.play());
    bar.querySelector(".s3d-restart").onclick = () => this.restart();
    this.freeBtn.onclick = () => this._toggleCamera();
  }

  _setReadyUI() {
    this.loadEl.style.display = "none";
    this.playBtn.disabled = false;
    this.segLabel.textContent = "—";
  }
  _fail(e) {
    console.error("[YVM3D]", e);
    this.loadEl.innerHTML = `⚠ Could not load the 3D cast (${(e && e.message) || e}).`;
  }

  _initThree() {
    const theme = this.theme = THEMES[this.scene.scene_template?.template_id] || DEFAULT_THEME;
    const w = this.canvasHost.clientWidth || 640;
    const h = w * 9 / 16;

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.canvasHost.appendChild(this.renderer.domElement);

    this.scene3 = new THREE.Scene();
    this.scene3.background = new THREE.Color(theme.bg);
    this.scene3.fog = new THREE.Fog(theme.fog, 10, 24);

    this.camera = new THREE.PerspectiveCamera(38, w / h, 0.1, 100);
    this.camera.position.set(0, 3, 6);
    this.camDesiredPos = this.camera.position.clone();
    this.camDesiredTarget = V(0, 1, 0);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.target.copy(this.camDesiredTarget);
    this.controls.enabled = false;

    this.scene3.add(new THREE.HemisphereLight(0xffffff, theme.floor, theme.amb));
    const key = new THREE.DirectionalLight(0xffffff, theme.key);
    key.position.set(4, 8, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.near = 1; key.shadow.camera.far = 30;
    key.shadow.camera.left = -8; key.shadow.camera.right = 8;
    key.shadow.camera.top = 8; key.shadow.camera.bottom = -8;
    key.shadow.bias = -0.0004;
    this.scene3.add(key);
    const rim = new THREE.DirectionalLight(0xbcd0ff, 0.45);
    rim.position.set(-6, 4, -5);
    this.scene3.add(rim);

    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(18, 48),
      new THREE.MeshStandardMaterial({ color: theme.floor, roughness: 0.96 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    this.scene3.add(floor);

    this.clock = new THREE.Clock();
    this._onResize = () => this._resize();
    window.addEventListener("resize", this._onResize);
  }

  async _buildWorld() {
    const stage = new THREE.Group();
    this.scene3.add(stage);

    // ---- table (poly.pizza, CC0) ----
    let tableDim = { width: 3.2, depth: 1.3, height: 0.75 };
    try {
      const g = await loadGLB("/assets/props/table.glb");
      const table = g.scene.clone(true);
      table.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
      tableDim = fitToFloor(table, 3.2, true);
      stage.add(table);
    } catch (e) {
      const t = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.1, 1.3),
        new THREE.MeshStandardMaterial({ color: 0x6b4a2f, roughness: 0.8 }));
      t.position.y = 0.7; t.castShadow = true; t.receiveShadow = true; stage.add(t);
    }
    this.tableDim = tableDim;

    const chairGLB = await loadGLB("/assets/props/chair.glb").catch(() => null);
    const assets = await getCharacterAssets();

    // ---- seats: 3 challengers (far, -Z) + protagonist (near, +Z) ----
    const cast = this.data.cast;
    const protagonist = cast.find((c) => c.role === "protagonist") || cast[0];
    const challengers = cast.filter((c) => c.role !== "protagonist");
    const seatZ = Math.max(1.05, tableDim.depth / 2 + 0.62);
    const spanX = Math.min(tableDim.width - 0.6, 2.7);
    const n = challengers.length;
    const xs = n > 1 ? challengers.map((_, i) => -spanX / 2 + (spanX * i) / (n - 1)) : [0];

    challengers.forEach((c, i) => this._seat(c, xs[i], -seatZ, 0, assets, chairGLB));
    this._seat(protagonist, 0, seatZ, Math.PI, assets, chairGLB); // faces -Z toward the bench

    this.layout = { seatZ, headY: 1.15, spanX };
  }

  _seat(charObj, x, z, faceY, assets, chairGLB) {
    const id = charObj.character_id;
    const color = this.colorFor(id);
    const group = new THREE.Group();
    group.position.set(x, 0, z);
    // Face the table centre. Mixamo rigs face +Z by default, so a group yaw of
    // atan2(-x,-z) points each seat's forward at the origin.
    group.rotation.y = Math.atan2(-x, -z);
    this.scene3.add(group);

    // chair (back on the outer side, seat opening toward the table = local +Z)
    if (chairGLB) {
      const chair = chairGLB.scene.clone(true);
      chair.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
      fitToHeight(chair, CHAIR_HEIGHT);
      chair.position.z = -0.02;
      group.add(chair);
    }

    // skinned Mixamo human, cloned from the shared rig
    const model = skeletonClone(assets.rig);
    model.traverse((o) => { if (o.isMesh || o.isSkinnedMesh) { o.castShadow = true; o.frustumCulled = false; } });
    group.add(model);
    fitToHeight(model, CHAR_HEIGHT); // scale from T-pose standing height

    const mixer = new THREE.AnimationMixer(model);
    const idle = mixer.clipAction(assets.idle);
    const talk = mixer.clipAction(assets.talk);
    idle.play(); talk.play();
    idle.setEffectiveWeight(1); talk.setEffectiveWeight(0);
    mixer.update(0);

    // drop feet to the floor now that the seated pose is applied
    const box = new THREE.Box3().setFromObject(model);
    model.position.y -= box.min.y;
    model.position.z -= 0.08; // scoot back (local -Z) so the hips sit over the seat

    // active-speaker floor ring in the character's colour
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.34, 0.46, 40),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0, side: THREE.DoubleSide }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.02;
    group.add(ring);

    const plate = this._nameplate(this.nameFor(id), color);
    plate.position.set(0, 1.9, 0);
    group.add(plate);

    this.chars.set(id, { group, model, mixer, idle, talk, talkW: 0, color, role: charObj.role, ring, plate });
  }

  _nameplate(text, color) {
    const c = document.createElement("canvas");
    c.width = 256; c.height = 64;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "rgba(10,13,17,0.82)";
    roundRect(ctx, 4, 12, 248, 40, 12); ctx.fill();
    ctx.strokeStyle = "#" + color.toString(16).padStart(6, "0");
    ctx.lineWidth = 3; roundRect(ctx, 4, 12, 248, 40, 12); ctx.stroke();
    ctx.fillStyle = "#e9ecf2";
    ctx.font = "600 26px -apple-system,Segoe UI,Inter,sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, 128, 33, 232);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
    spr.scale.set(0.9, 0.225, 1);
    spr.renderOrder = 10;
    return spr;
  }

  // ---------- camera shots ----------
  _shot(seg) {
    const L = this.layout, sp = seg.speaker_id;
    const ch = this.chars.get(sp);
    const cx = ch ? ch.group.position.x : 0;
    switch (seg.camera?.shot) {
      case "protagonist_close":
        return { pos: V(0.95, L.headY + 0.35, L.seatZ - 1.35), tgt: V(0, L.headY, L.seatZ) };
      case "challenger_close":
        return { pos: V(cx * 0.5, L.headY + 0.5, 0.9), tgt: V(cx, L.headY - 0.05, -L.seatZ) };
      case "two_shot":
        return { pos: V(this.tableDim.width / 2 + 2.4, L.headY + 0.6, 0.2), tgt: V(0, L.headY - 0.05, 0) };
      case "reaction":
        return { pos: V(-(this.tableDim.width / 2 + 1.8), L.headY + 1.2, L.seatZ + 0.6), tgt: V(0, L.headY - 0.1, -L.seatZ * 0.35) };
      case "wide_master":
      default:
        return { pos: V(0, L.headY + 1.7, L.seatZ + 3.7), tgt: V(0, L.headY - 0.1, 0) };
    }
  }

  _frameWide() {
    const L = this.layout || { headY: 1.15, seatZ: 1.1 };
    this.camDesiredPos = V(0, L.headY + 1.8, L.seatZ + 3.9);
    this.camDesiredTarget = V(0, L.headY - 0.1, 0);
    this.camera.position.copy(this.camDesiredPos);
    this.controls.target.copy(this.camDesiredTarget);
  }

  // ---------- playback ----------
  play() {
    if (this.disposed || !this.ready) return;
    this._unlockAudio();
    this.playing = true;
    this.playBtn.textContent = "❚❚ Pause";
    if (this.cur < 0 || this.cur >= this.segments.length) this._goto(0);
    else this._speakCurrent();
  }
  pause() {
    this.playing = false;
    this.playBtn.textContent = "▶ Play scene";
    window.speechSynthesis && window.speechSynthesis.cancel();
    if (this._audio) this._audio.pause();
    if (this._holdTimer) clearTimeout(this._holdTimer);
  }
  restart() {
    this.pause(); this.cur = -1; this._frameWide();
    this.progFill.style.width = "0%"; this.segLabel.textContent = "—";
    this.captionEl.classList.remove("on"); this._clearSpeaking();
  }

  _goto(i) {
    this.cur = i;
    if (i >= this.segments.length) { this._finish(); return; }
    const seg = this.segments[i];
    const shot = this._shot(seg);
    this.camDesiredPos = shot.pos; this.camDesiredTarget = shot.tgt;
    this.segLabel.textContent = `seg ${i + 1}/${this.segments.length}`;
    this.progFill.style.width = `${(i / this.segments.length) * 100}%`;
    this._setSpeaking(seg);
    this._speakCurrent();
  }
  _next() { if (this.playing) this._goto(this.cur + 1); }

  _finish() {
    this.playing = false;
    this.playBtn.textContent = "▶ Replay";
    this.progFill.style.width = "100%";
    this.segLabel.textContent = "done";
    this.cur = -1;
    this.captionEl.classList.remove("on");
    this._clearSpeaking();
    this._frameWide();
  }

  _setSpeaking(seg) {
    const isCaption = seg.speaker_id === "caption";
    this.activeId = isCaption ? null : seg.speaker_id;
    this.shotEl.textContent = (seg.camera?.shot || "").replace("_", " ");
    const ch = this.chars.get(seg.speaker_id);
    const who = isCaption ? "" : this.nameFor(seg.speaker_id);
    this.captionEl.innerHTML = isCaption
      ? `<span class="ritual">${esc(seg.dialogue)}</span>`
      : `<b style="color:#${(ch?.color || 0xffffff).toString(16).padStart(6, "0")}">${esc(who)}</b> ${esc(seg.dialogue)}`;
    this.captionEl.classList.add("on");
  }
  _clearSpeaking() { this.activeId = null; }

  _speakCurrent() {
    const seg = this.segments[this.cur];
    if (!seg) return;
    if (this._holdTimer) clearTimeout(this._holdTimer);
    if (this._audio) { this._audio.onended = null; this._audio.pause(); this._audio = null; }

    const isCaption = seg.speaker_id === "caption";
    this._speakDur = Math.max(0.6, seg.end_s - seg.start_s) * 1000;
    if (isCaption) { this._holdTimer = setTimeout(() => this._next(), Math.max(1100, this._speakDur)); return; }

    const audioRef = this._audioRefFor(seg);
    if (audioRef) {
      const a = new Audio(audioRef);
      this._audio = a;
      a.onended = () => this._next();
      a.onerror = () => this._speakWeb(seg);
      a.play().catch(() => this._speakWeb(seg));
      return;
    }
    this._speakWeb(seg);
  }

  _speakWeb(seg) {
    const synth = window.speechSynthesis;
    if (!synth) { this._holdTimer = setTimeout(() => this._next(), this._speakDur); return; }
    synth.cancel();
    const u = new SpeechSynthesisUtterance(seg.dialogue);
    const vp = this._voiceParamsFor(seg.speaker_id);
    if (vp.voice) u.voice = vp.voice;
    u.pitch = vp.pitch; u.rate = vp.rate;
    u.onend = () => this._next();
    u.onerror = () => { this._holdTimer = setTimeout(() => this._next(), 400); };
    this._speakDur = Math.max(900, seg.dialogue.split(/\s+/).length / 2.6 * 1000);
    synth.speak(u);
  }

  _audioRefFor(seg) {
    const cue = (this.scene.audio || []).find(
      (a) => a.speaker_id === seg.speaker_id && Math.abs(a.start_s - seg.start_s) < 0.05,
    );
    return cue ? cue.audio_ref : null;
  }

  _voiceParamsFor(charId) {
    const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
    const en = voices.filter((v) => /en[-_]/i.test(v.lang));
    const pool = en.length ? en : voices;
    const ch = this.chars.get(charId);
    const idx = ch ? [...this.chars.keys()].indexOf(charId) : 0;
    const voice = pool.length ? pool[idx % pool.length] : null;
    const pitch = ch && ch.role === "protagonist" ? 0.85 : [1.18, 0.95, 1.32, 1.05, 0.78][idx % 5];
    const rate = ch && ch.role === "protagonist" ? 0.98 : [1.05, 0.97, 1.1, 1.0, 0.93][idx % 5];
    return { voice, pitch, rate };
  }

  _unlockAudio() {
    if (this._audioUnlocked) return;
    this._audioUnlocked = true;
    if (window.speechSynthesis) window.speechSynthesis.getVoices();
  }

  _toggleCamera() {
    this.director = !this.director;
    this.controls.enabled = !this.director;
    this.freeBtn.textContent = this.director ? "🎥 Director" : "🖐 Free cam";
    if (this.director) this.controls.target.copy(this.camDesiredTarget);
  }

  // ---------- render loop ----------
  _loop() {
    if (this.disposed) return;
    this._raf = requestAnimationFrame(() => this._loop());
    const dt = Math.min(this.clock.getDelta(), 0.05);

    if (this.director) {
      const k = 1 - Math.pow(0.0016, dt);
      this.camera.position.lerp(this.camDesiredPos, k);
      this.controls.target.lerp(this.camDesiredTarget, k);
    }

    for (const [id, ch] of this.chars) {
      ch.mixer.update(dt);
      const speaking = id === this.activeId && this.playing;
      const target = speaking ? 1 : 0;
      ch.talkW += (target - ch.talkW) * (1 - Math.pow(0.02, dt)); // smooth crossfade
      ch.talk.setEffectiveWeight(ch.talkW);
      ch.idle.setEffectiveWeight(1 - ch.talkW);
      ch.ring.material.opacity += ((speaking ? 0.55 : 0) - ch.ring.material.opacity) * 0.15;
      const s = 1 + (speaking ? 0.12 : 0);
      ch.plate.scale.x += (0.9 * s - ch.plate.scale.x) * 0.15;
      ch.plate.scale.y += (0.225 * s - ch.plate.scale.y) * 0.15;
    }

    this.controls.update();
    this.renderer.render(this.scene3, this.camera);
  }

  _resize() {
    const w = this.canvasHost.clientWidth || 640;
    const h = w * 9 / 16;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  dispose() {
    this.disposed = true;
    this.pause();
    cancelAnimationFrame(this._raf);
    window.removeEventListener("resize", this._onResize);
    this.renderer.dispose();
    this.canvasHost && (this.canvasHost.innerHTML = "");
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

let current = null;
window.YVM3D = {
  show(data) {
    const host = document.getElementById("stage3d");
    if (!host) return;
    if (current) current.dispose();
    current = new StagePlayer(host, data);
  },
};
