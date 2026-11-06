// 3D globe of Netwatch connections (globe.gl, vendored). Used small in the rail card and big when expanded.
import { arcsFromState, ringsFromState, COLORS } from "./geo.js";

let countries = null;
async function loadCountries() {
  if (!countries) {
    const topo = await (await fetch("/vendor/countries-110m.json")).json();
    countries = topojson.feature(topo, topo.objects.countries).features;
  }
  return countries;
}

/**
 * Mount a globe in `el`. interactive=false: slow auto-rotate, no controls (rail preview).
 * onHover(item | null) reports the connection under the pointer (expanded view only).
 */
export function mountGlobe(el, { interactive, onHover = () => {} }) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const g = new Globe(el, { rendererConfig: { antialias: interactive, alpha: true } })
    .backgroundColor("rgba(0,0,0,0)")
    .showAtmosphere(true)
    .atmosphereColor("#0A84FF")
    .atmosphereAltitude(0.14)
    .polygonCapColor(() => "#1f2b38")
    .polygonSideColor(() => "rgba(0,0,0,0)")
    .polygonStrokeColor(() => "#33465a")
    .polygonAltitude(0.004)
    .arcColor((a) => COLORS[a.kind])
    // past connections are plain lines (cheap); only live/flagged ones are 3D tubes
    .arcStroke((a) => (a.kind === "flagged" ? 0.9 : a.kind === "live" ? 0.45 : null))
    .arcCurveResolution(32)
    .arcCircularResolution(4)
    .arcAltitudeAutoScale(0.4)
    .arcDashLength((a) => (a.kind === "past" ? 1 : 0.35))
    .arcDashGap((a) => (a.kind === "past" ? 0 : 0.25))
    .arcDashAnimateTime((a) => (reduce || a.kind === "past" ? 0 : 2400))
    .ringColor(() => (t) => `rgba(255,69,58,${1 - t})`)
    .ringMaxRadius(4)
    .ringPropagationSpeed(2)
    .ringRepeatPeriod(reduce ? 0 : 1400)
    .pointColor(() => "#ffffff")
    .pointAltitude(0.01)
    .pointRadius(0.35)
    .width(el.clientWidth)
    .height(el.clientHeight);

  const mat = g.globeMaterial();
  mat.color.set("#0b1622");
  mat.emissive?.set("#050b12");
  mat.shininess = 4;

  g.renderer().setPixelRatio(interactive ? Math.min(devicePixelRatio, 1.5) : 1);
  const controls = g.controls();
  controls.autoRotate = !reduce;
  controls.autoRotateSpeed = interactive ? 0.25 : 0.5;
  controls.enabled = interactive;
  controls.enableZoom = interactive;

  if (interactive) {
    g.onArcHover((a) => { onHover(a ? { ...a.item, count: a.count } : null); el.style.cursor = a ? "pointer" : ""; })
      .onArcClick((a) => { controls.autoRotate = false; onHover({ ...a.item, count: a.count }); });
    // stop the slow spin as soon as the user grabs or zooms, so their gesture isn't fought
    controls.addEventListener("start", () => { controls.autoRotate = false; });
  }

  loadCountries().then((f) => g.polygonsData(f)).catch(() => {});

  const ro = new ResizeObserver(() => g.width(el.clientWidth).height(el.clientHeight));
  ro.observe(el);
  // Never spin the GPU in a background tab
  let held = false;   // paused on purpose (another globe is open): tab switches must not wake it
  const vis = () => (document.hidden || held ? g.pauseAnimation() : g.resumeAnimation());
  document.addEventListener("visibilitychange", vis);

  let aimed = false;
  return {
    update(state) {
      if (!state) return;
      if (!aimed && state.home) {
        g.pointOfView({ lat: state.home.lat - 8, lng: state.home.lon + 20, altitude: interactive ? 2.1 : 2.4 }, 0);
        aimed = true;
      }
      g.arcsData(arcsFromState(state))
        .ringsData(ringsFromState(state))
        .pointsData(state.home ? [{ lat: state.home.lat, lng: state.home.lon }] : []);
    },
    pause() { held = true; g.pauseAnimation(); },
    resume() { held = false; if (!document.hidden) g.resumeAnimation(); },
    destroy() {
      ro.disconnect();
      document.removeEventListener("visibilitychange", vis);
      g.pauseAnimation();
      g._destructor?.();
      el.innerHTML = "";
    },
  };
}
