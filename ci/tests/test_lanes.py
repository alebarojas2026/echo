import json

from ci.lanes import discover_lanes, lane_steps, requirement_lines


def test_a_lane_is_any_top_level_folder_with_test_files():
    paths = {
        "brain/tests/test_core.py",
        "brain/core.py",
        "agent/test_tools.py",  # a new folder is picked up without anyone listing it
        "store/deep/er/test_rows.py",
        "radio/README.md",  # no tests, no lane
        "test_top.py",  # a file at the root is not a lane
        "contracts/check.py",
    }
    assert discover_lanes(paths) == ["agent", "brain", "contracts", "store"]


def test_contracts_is_always_a_lane_and_web_comes_last():
    paths = {"contracts/check.py", "web/package.json", "web/src/main.ts", "sim/tests/test_fake.py"}
    assert discover_lanes(paths) == ["contracts", "sim", "web"]


def test_tests_inside_node_modules_or_web_do_not_make_lanes():
    paths = {"web/node_modules/x/test_x.py", "node_modules/test_y.py", "web/tools/test_prep.py"}
    assert discover_lanes(paths) == []


def test_python_lane_installs_its_requirements_then_runs_pytest_on_the_folder():
    steps = lane_steps("brain", {"brain/requirements.txt", "brain/tests/test_core.py"})
    assert [s["name"] for s in steps] == ["deps", "pytest"]
    assert steps[0]["setup"] is True
    assert steps[1]["cmd"].startswith("python -m pytest brain ")


def test_contracts_lane_also_checks_the_fixtures():
    steps = lane_steps("contracts", {"contracts/tests/test_check.py"})
    assert [s["name"] for s in steps] == ["pytest", "fixtures"]
    assert "contracts.check contracts/fixtures/valid*" in steps[1]["cmd"]


def test_web_lane_uses_the_package_typecheck_script():
    pkg = json.dumps({"scripts": {"typecheck": "tsc --noEmit", "test": "vitest run"}})
    steps = lane_steps("web", {"web/package.json"}, pkg)
    assert [s["name"] for s in steps] == ["npm ci", "tsc", "vitest", "vite build"]
    assert steps[1]["cmd"] == "npm run -s typecheck"
    assert all(s["cwd"] == "web" for s in steps)


def test_web_lane_falls_back_to_tsc_without_a_typecheck_script():
    steps = lane_steps("web", {"web/package.json"}, json.dumps({"scripts": {}}))
    assert steps[1]["cmd"] == "npx tsc --noEmit"


def test_requirement_lines_drop_comments_and_duplicates():
    files = {
        "sim/requirements.txt": "numpy\nwebsockets>=14\n",
        "brain/requirements.txt": "# a comment\nnumpy\nscikit-learn  # inline\n-r other.txt\n",
    }
    assert requirement_lines(files) == ["numpy", "scikit-learn", "websockets>=14"]
