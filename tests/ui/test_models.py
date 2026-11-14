"""Loading models: one that fails, the 3D view before the slices are done, a new model starting clean,
and a model squared by its button."""
import pytest

from .helpers import settle, plan, set_fields, state, use, ROOT


@pytest.mark.timeout(600)
def test_a_model_that_cannot_be_loaded_says_so_and_keeps_the_job(page):
    """The reported confusion: an upload that fails leaves the previous model on screen while the file box names the
    new one, and the only word about it is a line of red text. It has to be a dialog, and the box has to let go."""
    page.click('nav button[data-t="model"]')
    page.click('#modes button[data-m="stacked"]') if page.is_visible('#modes button[data-m="stacked"]') else None
    settle(page)
    before = plan(page)["counts"]["parts"]
    bad = ROOT / "working-files" / "not-a-mesh.stl"
    bad.write_bytes(b"this is not a mesh" * 100)
    page.set_input_files("#file", str(bad))
    page.wait_for_function("() => document.getElementById('oops').open", timeout=120_000)
    assert "could not be loaded" in page.text_content("#oops_title")
    page.click("#oops_go")
    assert page.eval_on_selector("#file", "el => el.files.length") == 0      # the box lets go of the file
    assert plan(page)["counts"]["parts"] == before                           # and the job is untouched
    bad.unlink(missing_ok=True)
    assert not page.errors, page.errors


@pytest.mark.timeout(600)
def test_the_model_is_on_screen_before_the_slices_are_finished(page):
    """The reported one: a slow slice showed nothing at all until the last sheet was nested. The build says as soon
    as it has finished with the mesh, and the 3D view fills with it then — while the slices are still being cut —
    and the overlay lists the stages so the wait has a shape."""
    page.click('nav button[data-t="model"]')
    before = page.evaluate("() => [window.__t.ghostUrl(), window.__t.plan().counts.faces]")
    page.select_option("#example", "head_igea")            # detailed enough that the stages take seconds
    page.wait_for_function("old => window.__t.ghostUrl() !== old[0] && window.__t.ghost().length > 0",
                           arg=before, timeout=300_000)
    # the model is up, and the plan it belongs to has not come back yet: that gap is the whole point
    assert page.evaluate("() => window.__t.plan().counts.faces") == before[1]
    rows = page.eval_on_selector_all("#busy_steps li", "ls => ls.map(l => l.className + '|' + l.textContent)")
    assert len(rows) >= 6, rows
    assert any(r.startswith("done|") for r in rows) and any(r.startswith("now|") for r in rows), rows
    assert " of " in page.text_content("#busy_txt"), page.text_content("#busy_txt")   # "step 4 of 8 · … · 20%"
    settle(page)
    assert page.evaluate("() => window.__t.plan().counts.faces") != before[1]
    assert not page.errors, page.errors


@pytest.mark.timeout(600)
def test_a_new_model_does_not_inherit_the_last_one_s_geometry(page):
    """Axis lines, curve points and per-slice edits live in one model's millimetres and under its own part labels.
    Place three radial fans on one model, open another, and radial has to start from a single centred axis again —
    the fan belonged to the model it was drawn on, and so did the memory of it."""
    use(page, mode="radial")
    page.evaluate("""() => {
        const h = window.__t.plan().bbox[2] / 2, s = window.__t.state();
        s.axes = [[[-40, 0, -h * .66], [40, 0, -h * .66]], [[-40, 0, 0], [40, 0, 0]], [[-40, 0, h * .66], [40, 0, h * .66]]];
        s.spine = 1; s.offset = {'R1-2a': 5};
        document.getElementById('p_count').dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    settle(page)
    assert len(state(page)["axes"]) == 3

    page.click('nav button[data-t="model"]')
    page.select_option("#example", "torus")                  # opens interlocked: a different technique entirely
    settle(page)
    assert page.evaluate("() => window.__t.state().axes ?? null") == []
    assert page.evaluate("() => window.__t.state().offset ?? null") == {}

    use(page, mode="radial")
    assert state(page)["axes"] == [], "the last model's fan came back"
    used = page.evaluate("() => window.__t.plan().axes3d")
    assert len(used) == 1, used                              # one axis…
    assert abs(used[0][0][0]) < 1e-6 and abs(used[0][0][1]) < 1e-6, used   # …through the middle of the model

    # Bug 004: an upload kept the last example's model settings — the horse's size 300, round 2, thicken 1 — and a
    # plain cube came back with rounded corners and a hole closed up. An upload starts from the model as drawn.
    use(page, "horse")
    assert state(page)["round"] == 2   # the preset this is about, really applied
    page.set_input_files("#file", str(ROOT / "examples" / "cube.stl"))
    settle(page)
    got = page.evaluate("() => { const s = window.__t.state(); return [s.size, s.round, s.thicken] }")
    assert got == [[0, 0, 0], 0, 0], got
    assert [round(e) for e in plan(page)["bbox"]] == [180, 180, 180]   # the cube at its own size, not 300

    # an example, then the same file again: the box still held it, so choosing it fired nothing and the example stayed
    page.select_option("#example", "egg")
    settle(page)
    page.set_input_files("#file", str(ROOT / "examples" / "cube.stl"))
    settle(page)
    assert [round(e) for e in plan(page)["bbox"]] == [180, 180, 180], "the same file picked again did not load"
    assert not page.errors, page.errors


@pytest.mark.timeout(600)
def test_a_model_a_few_degrees_off_square_is_squared_by_its_button(page):
    """Bug 001: a cube turned 85° instead of 90° stacked into a staircase and nothing said so. The Model tab now says
    how far off it sits, and its button turns it the rest of the way."""
    use(page, "cube")
    assert page.is_hidden("#square")                         # square already: nothing to offer
    set_fields(page, [("p_rotate_0", 85)])
    settle(page)
    assert page.is_visible("#square"), "a cube 5° off square was not noticed"
    page.click("#square button")
    settle(page)
    assert state(page)["rotate"] == [90, 0, 0]
    assert page.is_hidden("#square")
    assert [round(e) for e in plan(page)["bbox"]] == [180, 180, 180]   # square again: no tilted, taller box
    assert not page.errors, page.errors
