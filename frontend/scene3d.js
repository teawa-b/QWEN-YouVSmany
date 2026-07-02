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
const HEAD_TO_CROWN_Y = 0.17;
const CROWN_TO_UPPER_BODY_Y = 0.38;
const CLOSE_UPPER_BODY_DROP_Y = 0.44;
const CLOSE_CAMERA_TABLE_OFFSET_Z = 1.4;
const HEAD_BONE_NAMES = ["mixamorigHead", "Head"];

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

// The seated idle/talking clips are Mixamo exports authored for Remy's
// proportions, but every Mixamo character shares the same *local* per-bone
// rotation convention regardless of body size — that's the premise their
// whole animation library relies on, and it's why the raw clip can just be
// replayed on a differently-proportioned rig without touching most tracks.
// The one thing that ISN'T proportion-independent is the hip's *position*
// track (Remy's rig uses ~2x larger raw units than X/Y Bot), so we rescale
// only that track by (targetHipHeight / REMY_HIP_Y) before applying the clip.
const REMY_HIP_Y = 209.15078735351562; // remy.fbx "Body" mesh, mixamorigHips, bind pose

let characterAssetsPromise = null;
function getCharacterAssets() {
  if (!characterAssetsPromise) characterAssetsPromise = _loadCharacterAssets();
  return characterAssetsPromise;
}
async function _loadCharacterAssets() {
  const [maleRig, femaleRig, idleSrc, talkSrc] = await Promise.all([
    loadFBX("/assets/characters/y_bot.fbx"),
    loadFBX("/assets/characters/x_bot.fbx"),
    loadFBX("/assets/characters/anim_idle.fbx"),
    loadFBX("/assets/characters/anim_talking.fbx"),
  ]);

  // X Bot / Y Bot each ship a visible "*_Surface" mesh plus a "*_Joints"
  // debug mesh with its OWN duplicate bone hierarchy (same names) — drop it
  // entirely so bone-name lookups during animation binding stay unambiguous.
  for (const rig of [maleRig, femaleRig]) {
    const joints = [];
    rig.traverse((o) => { if (o.isSkinnedMesh && /_Joints$/i.test(o.name)) joints.push(o); });
    for (const o of joints) o.parent.remove(o);
  }

  const idleClip = idleSrc.animations[0];
  const talkClip = talkSrc.animations[0];

  const characterAssets = {
    rigs: { male: maleRig, female: femaleRig, neutral: maleRig },
    clips: {
      male: retargetForRig(maleRig, idleClip, talkClip),
      female: retargetForRig(femaleRig, idleClip, talkClip),
    },
  };
  characterAssets.clips.neutral = characterAssets.clips.male;
  return characterAssets;
}

// The largest SkinnedMesh remaining after _Joints removal is the character's
// real body ("Beta_Surface" / "Alpha_Surface" for X Bot / Y Bot).
function mainSkinnedMesh(rig) {
  let best = null;
  rig.traverse((o) => {
    if (o.isSkinnedMesh) {
      if (!best || o.skeleton.bones.length > best.skeleton.bones.length) best = o;
    }
  });
  return best;
}

// Local per-bone rotations copy cleanly between Mixamo rigs, but they still
// compound down the spine chain (Spine -> Spine1 -> Spine2 -> Neck -> Head).
// On Remy's proportions that reads as a forward lean; on X/Y Bot the same
// local angles compound into a much sharper bow that buries the head below
// close-up framing. Dropping these three from the clip keeps the seated
// lean (from Spine/Spine1 and the legs/arms) but holds the head upright.
const UPRIGHT_BONES = ["mixamorigSpine2", "mixamorigNeck", "mixamorigHead"];

function retargetForRig(rig, idleClip, talkClip) {
  const skinned = mainSkinnedMesh(rig);
  rig.updateMatrixWorld(true);
  const hip = skinned.skeleton.bones[0];
  const hipWorld = new THREE.Vector3();
  hip.getWorldPosition(hipWorld);
  const hipScale = hipWorld.y / REMY_HIP_Y;

  function scaledHipClip(clip) {
    const out = clip.clone();
    const hipTrack = out.tracks.find((t) => t.name === hip.name + ".position");
    if (hipTrack) for (let i = 0; i < hipTrack.values.length; i++) hipTrack.values[i] *= hipScale;
    out.tracks = out.tracks.filter(
      (t) => !UPRIGHT_BONES.some((name) => t.name === name + ".quaternion"),
    );
    return out;
  }
  return { idle: scaledHipClip(idleClip), talk: scaledHipClip(talkClip) };
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

function inferPresentation(charObj) {
  const explicit = String(charObj.visual_presentation || "").toLowerCase();
  if (["male", "female", "neutral"].includes(explicit)) return explicit;

  const hints = `${charObj.character_id || ""} ${charObj.display_name || ""}`.toLowerCase();
  if (/\b(female|woman|girl|priya|lena|iris|mara|maya|sara|nora|ava)\b/.test(hints)) return "female";
  if (/\b(male|man|boy|devin|otis|tom|alex|sam|leo)\b/.test(hints)) return "male";
  return charObj.role === "protagonist" ? "male" : "neutral";
}

function findBone(root, names) {
  let found = null;
  root.traverse((o) => {
    if (found || !o.isBone) return;
    const clean = o.name.replace(/^.*:/, "");
    if (names.includes(o.name) || names.includes(clean)) found = o;
  });
  return found;
}

const V = (x, y, z) => new THREE.Vector3(x, y, z);

class StagePlayer {
  constructor(host, data, options = {}) {
    this.host = host;
    this.data = data;
    this.options = {
      aspectRatio: 16 / 9,
      captureSize: null,
      hideControls: false,
      hideOverlays: false,
      manualRender: false,
      pixelRatio: Math.min(window.devicePixelRatio, 2),
      showCropGuide: true,
      ...options,
    };
    this.scene = data.scene;
    this.segments = (this.scene.segments || []).filter((s) => (s.end_s - s.start_s) > 0.01);
    this.cur = -1;
    this.playing = false;
    this.ready = false;
    this.disposed = false;
    this.chars = new Map(); // character_id -> {group, model, mixer, idle, talk, color, role, ring}
    this.director = true;
    this.colorFor = data.colorFor;
    this.nameFor = data.nameFor;

    this._buildDom();
    this._initThree();
    this._buildWorld()
      .then(() => { this.ready = true; this._frameWide(); this._setReadyUI(); })
      .catch((e) => this._fail(e));
    if (!this.options.manualRender) this._loop();
  }

  _buildDom() {
    this.host.innerHTML = "";
    const cv = document.createElement("div");
    cv.className = "s3d-canvas";
    if (this.options.manualRender) cv.classList.add("capture");
    if (this.options.captureSize) {
      cv.style.width = `${this.options.captureSize.width}px`;
      cv.style.height = `${this.options.captureSize.height}px`;
    }
    cv.style.aspectRatio = `${this.options.aspectRatio}`;
    this.host.appendChild(cv);
    this.canvasHost = cv;

    const crop = document.createElement("div");
    crop.className = "s3d-crop";
    crop.title = "9:16 short crop-safe region";
    if (!this.options.showCropGuide || this.options.hideOverlays) crop.style.display = "none";
    cv.appendChild(crop);

    const load = document.createElement("div");
    load.className = "s3d-loading";
    load.innerHTML = `<span class="s3d-spin"></span> Loading humanoid cast…`;
    cv.appendChild(load);
    this.loadEl = load;

    const lt = document.createElement("div");
    lt.className = "s3d-lowerthird";
    lt.innerHTML = `<i class="s3d-lt-bar"></i><span class="s3d-lt-text"><b class="s3d-lt-name"></b><small class="s3d-lt-stance"></small></span>`;
    cv.appendChild(lt);
    if (this.options.hideOverlays) lt.style.display = "none";
    this.lowerThirdEl = lt;
    this.lowerThirdNameEl = lt.querySelector(".s3d-lt-name");
    this.lowerThirdStanceEl = lt.querySelector(".s3d-lt-stance");

    const cap = document.createElement("div");
    cap.className = "s3d-caption";
    cv.appendChild(cap);
    if (this.options.hideOverlays) cap.style.display = "none";
    this.captionEl = cap;

    const badge = document.createElement("div");
    badge.className = "s3d-shot";
    cv.appendChild(badge);
    if (this.options.hideOverlays) badge.style.display = "none";
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
    if (this.options.hideControls) bar.style.display = "none";
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
    const { w, h } = this._canvasSize();

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(this.options.pixelRatio);
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

    const heads = [...this.chars.values()].map((c) => c.headY).filter(Number.isFinite);
    const headY = heads.length
      ? Math.min(1.55, Math.max(1.12, heads.reduce((a, b) => a + b, 0) / heads.length))
      : 1.15;
    const frameYs = [...this.chars.values()].map((c) => c.frameY).filter(Number.isFinite);
    const frameY = frameYs.length
      ? Math.min(1.2, Math.max(0.82, frameYs.reduce((a, b) => a + b, 0) / frameYs.length))
      : headY - CROWN_TO_UPPER_BODY_Y;
    this.layout = { seatZ, headY, frameY, spanX };
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

    // skinned Mixamo human: Y Bot for male, X Bot for female presentation,
    // cloned per seat. `presentation` also drives voice selection below.
    const presentation = inferPresentation(charObj);
    const rig = assets.rigs[presentation] || assets.rigs.neutral;
    const clips = assets.clips[presentation] || assets.clips.neutral;
    const model = skeletonClone(rig);
    model.traverse((o) => { if (o.isMesh || o.isSkinnedMesh) { o.castShadow = true; o.frustumCulled = false; } });
    group.add(model);
    fitToHeight(model, CHAR_HEIGHT); // scale from T-pose standing height

    // Clips use standard bone-name paths (e.g. "mixamorigHips.position"), so
    // the mixer's root just needs to contain those named bones — the whole
    // cloned model works, PropertyBinding resolves by traversal + name.
    const mixer = new THREE.AnimationMixer(model);
    const idle = mixer.clipAction(clips.idle);
    const talk = mixer.clipAction(clips.talk);
    idle.play(); talk.play();
    idle.setEffectiveWeight(1); talk.setEffectiveWeight(0);
    mixer.update(0);

    // Drop feet to the floor now that the seated pose is applied, and scoot back
    // slightly (local -Z) so the hips sit over the seat rather than its front edge.
    const box = new THREE.Box3().setFromObject(model);
    model.position.y -= box.min.y;
    model.position.z -= 0.08;

    // active-speaker floor ring in the character's colour
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.34, 0.46, 40),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0, side: THREE.DoubleSide }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.02;
    group.add(ring);

    const character = {
      group,
      model,
      mixer,
      idle,
      talk,
      talkW: 0,
      color,
      role: charObj.role,
      presentation,
      ring,
      headY: 1.3,
      frameY: 0.95,
    };
    this._measureSeatedHead(character);
    this.chars.set(id, character);
  }

  // One-time measurement (not a per-frame reground): the model was already
  // grounded in _seat(), so this reads the actual Mixamo head bone. Bounding
  // boxes include raised hands during speech poses and aim the camera too high.
  _measureSeatedHead(ch) {
    ch.model.updateMatrixWorld(true);
    const head = findBone(ch.model, HEAD_BONE_NAMES);
    if (head) {
      const pos = new THREE.Vector3();
      head.getWorldPosition(pos);
      ch.headBoneY = pos.y;
      ch.headY = pos.y + HEAD_TO_CROWN_Y;
      ch.frameY = ch.headY - CROWN_TO_UPPER_BODY_Y;
      return;
    }

    const box = new THREE.Box3().setFromObject(ch.model);
    if (Number.isFinite(box.max.y)) {
      ch.headY = box.max.y;
      ch.frameY = box.max.y - CROWN_TO_UPPER_BODY_Y;
    }
  }

  // ---------- camera shots ----------
  // Heights are kept close to headY (near eye-level) rather than craned above
  // the cast — a broadcast panel shot looks across the table, not down on it.
  _shot(seg) {
    const L = this.layout, sp = seg.speaker_id;
    const ch = this.chars.get(sp);
    const cx = ch ? ch.group.position.x : 0;
    const headY = Number.isFinite(ch?.headY) ? ch.headY : L.headY;
    const frameY = Number.isFinite(ch?.frameY) ? ch.frameY : (L.frameY || headY - CROWN_TO_UPPER_BODY_Y);
    const closeFrameY = Math.max(0.72, headY - CLOSE_UPPER_BODY_DROP_Y);
    const sideZ = ch?.role === "protagonist" ? L.seatZ : -L.seatZ;
    const towardTable = sideZ > 0 ? -1 : 1;
    const vertical = this.options.aspectRatio < 1;
    const mediumDistance = vertical ? 1.72 : 2.15;
    const profileSide = vertical ? 1.08 : 1.35;
    switch (seg.camera?.shot) {
      case "intro_wide":
        return { pos: V(0, L.headY + 0.55, L.seatZ + 4.4), tgt: V(0, L.frameY, 0) };
      case "intro_table":
        return { pos: V(-1.25, L.headY + 0.2, L.seatZ + 2.5), tgt: V(0.15, L.frameY, -0.1) };
      case "intro_panel":
        return { pos: V(0, L.headY + 0.28, -L.seatZ - 2.5), tgt: V(0, L.frameY, -L.seatZ) };
      case "speaker_close":
        return { pos: V(cx * 0.58 + (sideZ > 0 ? 0.35 : 0), headY + 0.04, sideZ + towardTable * 1.4), tgt: V(cx, closeFrameY, sideZ) };
      case "speaker_medium":
        return { pos: V(cx * 0.5 + (sideZ > 0 ? 0.25 : 0), headY + 0.12, sideZ + towardTable * mediumDistance), tgt: V(cx, Math.max(0.74, headY - 0.5), sideZ) };
      case "speaker_profile":
        return { pos: V(cx + (cx <= 0 ? -profileSide : profileSide), headY + 0.05, sideZ + towardTable * 0.75), tgt: V(cx, Math.max(0.76, headY - 0.48), sideZ) };
      case "speaker_over_table":
        return { pos: V(cx * 0.38, headY + 0.22, -sideZ + towardTable * 0.5), tgt: V(cx, Math.max(0.78, headY - 0.46), sideZ) };
      case "protagonist_close":
        // Waist-up view from the table edge: upper torso fills the frame.
        return { pos: V(0.35, headY + 0.04, L.seatZ - CLOSE_CAMERA_TABLE_OFFSET_Z), tgt: V(0, closeFrameY, L.seatZ) };
      case "challenger_close":
        // Match the protagonist crop for challengers on the opposite bench.
        return { pos: V(cx * 0.58, headY + 0.04, -L.seatZ + CLOSE_CAMERA_TABLE_OFFSET_Z), tgt: V(cx, closeFrameY, -L.seatZ) };
      case "two_shot":
        // Side profile across the table showing both benches.
        return { pos: V(this.tableDim.width / 2 + 2.1, L.headY + 0.12, 0.1), tgt: V(0, L.frameY, 0) };
      case "reaction":
        return { pos: V(-(this.tableDim.width / 2 + 1.6), L.headY + 0.18, L.seatZ + 0.3), tgt: V(0, L.frameY, -L.seatZ * 0.4) };
      case "wide_master":
      default:
        return { pos: V(0, L.headY + 0.25, L.seatZ + 3.5), tgt: V(0, L.frameY, 0) };
    }
  }

  _frameWide() {
    const L = this.layout || { headY: 1.15, frameY: 0.9, seatZ: 1.1 };
    this.camDesiredPos = V(0, L.headY + 0.3, L.seatZ + 3.9);
    this.camDesiredTarget = V(0, L.frameY, 0);
    this.camera.position.copy(this.camDesiredPos);
    this.controls.target.copy(this.camDesiredTarget);
  }

  setReferenceShot({ speakerId, shot, speaking = false } = {}) {
    if (!this.ready) return;
    const seg = { speaker_id: speakerId, dialogue: "", camera: { shot } };
    const cam = this._shot(seg);
    this.camDesiredPos = cam.pos;
    this.camDesiredTarget = cam.tgt;
    this.camera.position.copy(this.camDesiredPos);
    this.controls.target.copy(this.camDesiredTarget);
    this.activeId = speaking ? speakerId : null;
    this.playing = Boolean(speaking);
    this.shotEl.textContent = String(shot || "").replace("_", " ");
    if (!this.options.hideOverlays && speakerId) this._setLowerThird(speakerId);
    else this._setLowerThird(null);
    this.renderReferenceFrame(1 / 30);
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
    this._setLowerThird(isCaption ? null : seg.speaker_id);
  }
  _clearSpeaking() { this.activeId = null; this._setLowerThird(null); }

  // Broadcast-style lower third: name + stance, fixed in the lower-left of
  // frame. Re-plays its slide-in whenever the active speaker changes; hides
  // during non-spoken caption beats (no one to attribute it to).
  _setLowerThird(speakerId) {
    if (!speakerId) {
      this.lowerThirdEl.classList.remove("on");
      this._lowerThirdSpeaker = null;
      return;
    }
    if (speakerId === this._lowerThirdSpeaker) return; // same speaker holds; no re-animate
    this._lowerThirdSpeaker = speakerId;
    const ch = this.chars.get(speakerId);
    const color = ch ? "#" + ch.color.toString(16).padStart(6, "0") : "#7b97ff";
    this.lowerThirdEl.style.setProperty("--c", color);
    this.lowerThirdNameEl.textContent = this.nameFor(speakerId);
    this.lowerThirdStanceEl.textContent = this._stanceFor(speakerId);
    // Restart the CSS transition even if it's already showing (speaker cuts).
    this.lowerThirdEl.classList.remove("on");
    void this.lowerThirdEl.offsetWidth; // force reflow
    this.lowerThirdEl.classList.add("on");
  }

  _stanceFor(speakerId) {
    const c = (this.data.cast || []).find((x) => x.character_id === speakerId);
    if (!c) return "";
    if (c.role === "protagonist") return c.stance === "against" ? "Against" : "For";
    return c.stance === "for" ? "For" : "Against";
  }

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
    const ref = cue ? cue.audio_ref : null;
    // CosyVoice clips are served by the backend (/audio/..); resolve relative
    // refs against the API origin, not the frontend origin.
    if (ref && ref.startsWith("/")) return (this.data.apiBase || "") + ref;
    return ref;
  }

  _voiceParamsFor(charId) {
    const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
    const en = voices.filter((v) => /en[-_]/i.test(v.lang));
    const pool = en.length ? en : voices;
    const ch = this.chars.get(charId);
    const idx = ch ? [...this.chars.keys()].indexOf(charId) : 0;
    const femaleNames = /female|woman|girl|zira|susan|samantha|victoria|karen|moira|serena|aria/i;
    const maleNames = /male|man|guy|david|mark|alex|daniel|fred|george|tom/i;
    const preferred =
      ch?.presentation === "female"
        ? pool.filter((v) => femaleNames.test(v.name))
        : ch?.presentation === "male"
          ? pool.filter((v) => maleNames.test(v.name))
          : [];
    const voicePool = preferred.length ? preferred : pool;
    const voice = voicePool.length ? voicePool[idx % voicePool.length] : null;
    const pitch =
      ch?.presentation === "female"
        ? [1.22, 1.12, 1.32, 1.18, 1.26][idx % 5]
        : ch && ch.role === "protagonist"
          ? 0.85
          : [0.92, 1.0, 0.86, 1.04, 0.78][idx % 5];
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
    this.renderReferenceFrame(dt);
  }

  renderReferenceFrame(dt = 1 / 30) {
    if (this.director) {
      const k = 1 - Math.pow(0.0016, dt);
      this.camera.position.lerp(this.camDesiredPos, k);
      this.controls.target.lerp(this.camDesiredTarget, k);
    }

    for (const [id, ch] of this.chars) {
      const speaking = id === this.activeId && this.playing;
      const target = speaking ? 1 : 0;
      ch.talkW += (target - ch.talkW) * (1 - Math.pow(0.02, dt)); // smooth crossfade
      ch.talk.setEffectiveWeight(ch.talkW);
      ch.idle.setEffectiveWeight(1 - ch.talkW);
      ch.mixer.update(dt);
      ch.ring.material.opacity += ((speaking ? 0.55 : 0) - ch.ring.material.opacity) * 0.15;
    }

    this.controls.update();
    this.renderer.render(this.scene3, this.camera);
  }

  _canvasSize() {
    if (this.options.captureSize) {
      return {
        w: this.options.captureSize.width,
        h: this.options.captureSize.height,
      };
    }
    const w = this.canvasHost.clientWidth || 640;
    const h = Math.round(w / this.options.aspectRatio);
    return { w, h };
  }

  _resize() {
    const { w, h } = this._canvasSize();
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

function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

let current = null;
window.YVM3D = {
  show(data, options = {}) {
    const host = document.getElementById("stage3d");
    if (!host) return;
    if (current) current.dispose();
    current = new StagePlayer(host, data, options);
    window.__YVM3D_DEBUG = current;
    return current;
  },
};
