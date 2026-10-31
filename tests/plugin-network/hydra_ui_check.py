"""Hydra 1.0 through the real interface, in headless Chromium (needs Python Playwright): the same two computers as
hydra_test.py. On B the Models page offers Hydra 1.0 from the host and "Get from host" sets it up; the chat
model picker never lists it; on A the Models page says it's installed and shared, and a looping long task's card
says it planned and reviewed with hydra:1.0. Saves screenshots in the work folder.
Usage: python3 hydra_ui_check.py <chimera binary> <workdir>"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hydra_test as ht
from playwright.sync_api import sync_playwright

it, check, api = ht.it, ht.check, ht.api


def main():
    ht.setup()
    for port in (ht.A_UI, ht.B_UI):
        api(port, "POST", "/api/settings", {"setup_done": True})
    ht.wait_for(lambda: ht.state(ht.B_UI)["helper"]["offered"], "B seeing the offer", 30)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        b = br.new_page(viewport={"width": 1280, "height": 900})
        b.goto("http://127.0.0.1:%d/" % ht.B_UI)
        b.click("button.mode[data-view=models]")
        row = b.locator(".pick", has_text="Hydra 1.0")
        row.wait_for(timeout=15000)
        b.screenshot(path=os.path.join(ht.WORK, "ui_B_models_before.png"))
        check("UI 1. B's Models page offers Hydra 1.0 from the host", row.locator("button[data-act=get-helper]").count() == 1, row.inner_text())
        row.locator("button[data-act=get-helper]").click()
        t0 = time.time()
        while time.time() - t0 < 60 and "Installed" not in row.inner_text():
            time.sleep(0.3)
        b.screenshot(path=os.path.join(ht.WORK, "ui_B_models_after.png"))
        check("UI 2. Get from host sets it up", "Installed" in row.inner_text(), row.inner_text())
        inst = b.locator(".inst", has_text="hydra:1.0")
        check("UI 3. the Installed list says what it's for", inst.count() == 1 and "helper" in inst.inner_text(), inst.inner_text() if inst.count() else "missing")
        b.click("button.mode[data-view=chat]")
        b.wait_for_timeout(1500)
        opts = b.locator("#sel-model option").all_inner_texts()
        check("UI 4. the chat model picker never lists the helper", opts and not any("hydra" in o for o in opts), str(opts))

        a = br.new_page(viewport={"width": 1280, "height": 900})
        a.goto("http://127.0.0.1:%d/" % ht.A_UI)
        a.click("button.mode[data-view=models]")
        arow = a.locator(".pick", has_text="Hydra 1.0")
        arow.wait_for(timeout=15000)
        check("UI 5. the host's Models page says it's installed and shared", "Installed, shared" in arow.inner_text(), arow.inner_text())
        a.click("button.mode[data-view=chat]")
        a.fill("#prompt", "Write a short guide to brewing green and black tea")
        a.check("#chk-task")
        a.check("#chk-loop")
        a.click("#btn-send")
        foot = a.locator(".plan-foot")
        t0 = time.time()
        while time.time() - t0 < 90 and not (foot.count() and "reviewed on" in foot.first.inner_text()):
            time.sleep(0.5)
        a.screenshot(path=os.path.join(ht.WORK, "ui_A_task.png"))
        text = foot.first.inner_text() if foot.count() else ""
        check("UI 6. the task card says it planned and reviewed with hydra:1.0",
              text.startswith("Planned on") and text.count("with hydra:1.0") == 2 and "reviewed on" in text, text)
        br.close()
    ok = all(r["ok"] for r in it.results)
    print("\n%d of %d checks passed" % (sum(r["ok"] for r in it.results), len(it.results)))
    return 0 if ok else 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        for p in reversed(it.procs):
            try:
                os.killpg(os.getpgid(p.pid), 15)
                p.wait(timeout=15)
            except Exception:
                pass
    sys.exit(code)
