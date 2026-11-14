/* Scenario management, opened from the rail's scenario menu (`?section=scenarios`).
   It sits under the read map so the map itself stays a single screen. */
import { useCallback, useEffect, useRef } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ScenarioManager } from "../ScenarioManager";
import { scenarioCreateRequestToken, withoutScenarioCreateRequest } from "../scenarioNavigation";

export function ScenarioSection() {
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  const shown = params.get("section") === "scenarios";
  const nonce = (location.state as { scenarioNavNonce?: number } | null)?.scenarioNavNonce ?? 0;
  /** Ends the running follow (see below). */
  const follow = useRef<(() => void) | null>(null);

  // Only a rail request (manage or create, which carries a nonce) brings the section into view, even when it
  // is already open. Switching client or device rewrites the address without one, so the page stays put.
  // The map above may still be loading and grow after the first scroll, so the section follows the page
  // height until it settles; the user's own scroll, key or press ends that at once.
  useEffect(() => {
    const el = ref.current;
    if (!shown) { follow.current?.(); return; }
    if (!nonce || !el) return;
    follow.current?.();
    let frame = 0;
    const align = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => el.scrollIntoView({ behavior: "smooth", block: "start" }));
    };
    const ro = new ResizeObserver(align);
    if (el.parentElement) ro.observe(el.parentElement);
    const events = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
    const stop = () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(settle);
      ro.disconnect();
      events.forEach((n) => window.removeEventListener(n, stop));
      if (follow.current === stop) follow.current = null;
    };
    const settle = window.setTimeout(stop, 2000);
    events.forEach((n) => window.addEventListener(n, stop, { once: true, passive: true }));
    follow.current = stop;
    align();
    // No cleanup on a nonce change: a consumed create request drops the nonce, and the follow keeps going.
  }, [shown, nonce]);
  useEffect(() => () => follow.current?.(), []);

  // The read map keeps its spot in the address bar outside the router (see ReadMapPage writeSpot), so every
  // rewrite here starts from the live address, not the router's copy of it.
  // A consumed create request leaves history state, so a remount cannot reopen the dialog.
  const handled = useCallback(() => {
    navigate({ pathname: location.pathname, search: window.location.search, hash: location.hash }, {
      replace: true,
      state: withoutScenarioCreateRequest(location.state),
    });
  }, [location.hash, location.pathname, location.state, navigate]);

  // Collapse: drop `section` from the address.
  const collapse = useCallback(() => {
    const q = new URLSearchParams(window.location.search);
    q.delete("section");
    const search = q.toString();
    navigate({ pathname: location.pathname, search: search ? `?${search}` : "", hash: location.hash }, { replace: true, state: null });
  }, [location.hash, location.pathname, navigate]);

  if (!shown) return null;
  return (
    <div id="scenario-management" ref={ref} className="rm-scenarios">
      <ScenarioManager createRequestToken={scenarioCreateRequestToken(location.state, shown)} onCreateRequestHandled={handled}
        onClose={collapse} />
    </div>
  );
}
