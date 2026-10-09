"""Internal installed-desktop restart check; never enabled during normal use."""
from __future__ import annotations

import json
from pathlib import Path
import time


def start_preferences_smoke(application, window, view, data_dir: Path, phase: int, output: Path, port: int):
    from PySide6.QtCore import QTimer, qVersion
    from .desktop_preferences import DesktopPreferences, LAYOUT_KEY, TUTORIAL_KEY, MAP_PREFIX

    if phase == 1:
        # Exercise the final close flush independently of the regular polling.
        window._rocket_preferences.timer.stop()
    output.unlink(missing_ok=True)
    state = {"status": "pending"}
    started = time.monotonic()
    script = """(() => {
      window.__rocketPreferencesSmoke={status:'pending'};
      const pause=ms=>new Promise(r=>setTimeout(r,ms));
      async function wait(predicate) {
        const deadline=Date.now()+18000;
        while(Date.now()<deadline) { const value=predicate(); if(value) return value; await pause(40); }
        throw new Error('UI control or state did not become available');
      }
      function button(text,aria,selector='button') {
        return [...document.querySelectorAll(selector)].find(b=>aria?b.getAttribute('aria-label')===aria:b.textContent.trim()===text);
      }
      async function click(text,aria,selector) {
        const b=await wait(()=>button(text,aria,selector)); b.click(); await pause(140);
      }
      (async()=>{
        await wait(()=>document.querySelector('.app-shell') && document.querySelector('.workspace-nav'));
        if (PHASE===1) await click(null,'Hide assembly');
        else if(!button(null,'Show assembly')) throw new Error('Layout not restored at frontend initialization');
        await click('Getting started');
        if(PHASE===1) { await click('Next step'); await click('Next step'); }
        const title=(await wait(()=>document.getElementById('tutorial-step-title'))).textContent;
        await click(null,'Close tutorial');
        await click('Flight',null,'.workspace-nav button');
        await click(null,'Expand flight map');
        if(PHASE===1) {
          await click(null,'Add a map point','dialog button');
          const map=await wait(()=>document.querySelector('dialog .flight-map-svg'));
          map.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
          await wait(()=>document.querySelector('dialog [data-testid=map-point-name]'));
          await click('Save point',null,'dialog button');
        }
        await wait(()=>[...document.querySelectorAll('dialog .flight-map-landmarks li span')].some(e=>e.textContent==='Point 1'));
        localStorage.setItem('X-Rocket-Session','forbidden-secret-sentinel');
        window.__rocketPreferencesSmoke={status:'ok',tutorial_title:title,layout_restored:PHASE===2,map_point_visible:true};
      })().catch(error=>{window.__rocketPreferencesSmoke={status:'failed',error:String(error.message)};});
    })()""".replace("PHASE", str(phase))
    timer = QTimer(window)
    timer.setInterval(100)
    pending = False

    def poll():
        nonlocal pending
        if pending:
            return
        if time.monotonic() - started > 30:
            timer.stop()
            state.update(status="failed", error="Installed preferences smoke timed out")
            window.close()
            return
        pending = True
        def checked(value):
            nonlocal pending
            pending = False
            try:
                current = json.loads(value) if isinstance(value, str) else {}
            except ValueError:
                current = {}
            if current:
                state["last_ui_status"] = current.get("status")
            if current and current.get("status") in {"ok", "failed"}:
                state.update(current)
                timer.stop()
                window.close()
        view.page().runJavaScript("JSON.stringify(window.__rocketPreferencesSmoke || {})", checked)

    timer.timeout.connect(poll)

    # Run after the first document exists, without exposing any debugging port.
    def begin(ok):
        if ok:
            view.page().loadFinished.disconnect(begin)
            view.page().runJavaScript(script)
            timer.start()
    view.page().loadFinished.connect(begin)
    def timeout():
        if state.get("status") == "pending":
            timer.stop()
            state.update(status="failed", error="Installed preferences smoke timed out")
            window.close()
    QTimer.singleShot(30000, timeout)

    def finish(exit_code):
        timer.stop()
        stored = DesktopPreferences(data_dir)
        raw = stored.path.read_text("utf8") if stored.path.exists() else ""
        valid = (state.get("status") == "ok" and LAYOUT_KEY in stored.values and TUTORIAL_KEY in stored.values
                 and any(key.startswith(MAP_PREFIX) for key in stored.values)
                 and "forbidden-secret-sentinel" not in raw and window._rocket_preferences.close_ready)
        receipt = {**state, "phase": phase, "port": port, "qt_version": qVersion(),
                   "profile_off_the_record": view.page().profile().isOffTheRecord(),
                   "frozen": bool(getattr(__import__("sys"), "frozen", False)),
                   "close_flush_verified": valid}
        if not valid:
            receipt["status"] = "failed"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + "\n", "utf8")
        return exit_code if valid else 1

    return finish
