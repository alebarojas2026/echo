from pathlib import Path

import pytest

from teacher.privacy import scan, violations


@pytest.mark.parametrize("source", [
    "import cv2 as c; c.imwrite(path, pixels)",
    "from cv2 import imwrite as store; store(path, pixels)",
    "import cv2; writer = cv2.VideoWriter(path, 0, 10, (10, 10))",
    "import imageio.v3 as io; io.imwrite(path, pixels)",
    "from PIL import Image as I; image = I.open(source); image.save(path)",
    "from PIL import Image; Image.open(source).save(path)",
    "import cv2; output = cv2.imwrite; output(path, pixels)",
    "import matplotlib.pyplot as plt; plt.savefig(path)",
    "clip.write_videofile(path)",
    "handle.write(frame.tobytes())",
    "open('capture.jpg', 'wb')",
    "from pathlib import Path; Path('capture.png').write_bytes(pixels)",
    "import subprocess; subprocess.run(['ffmpeg', '-i', device, output])",
    "import cv2; cv2.imencode('.jpg', frame)[1].tofile(p)",
    "import numpy as np; np.save('frame.npy', frame)",
    "import numpy as np; np.savez(p, data=image)",
    "import numpy as np; np.savetxt(p, pixels)",
])
def test_detects_writers_and_aliases(source):
    assert violations(source, "candidate.py")


@pytest.mark.parametrize("source", [
    "import cv2; cap = cv2.VideoCapture(device); ok, frame = cap.read(); cv2.imshow('live', frame)",
    "config.write_text(json.dumps(corners))",
    "handle.write(json.dumps(label))",
    "open('capture.jpg', 'rb')",
    "model.save(path)",
    "import numpy as np; np.save(p, features)",
    "example = 'cv2.imwrite(path, frame)'",
])
def test_reading_display_and_numeric_output_allowed(source):
    assert not violations(source, "candidate.py")


def test_non_python_writers():
    assert violations("ffmpeg -i camera out.mp4", "record.sh")
    assert violations("fs.writeFileSync('frame.png', data)", "record.ts")


def test_scan_reports_new_nested_file(tmp_path):
    nested = tmp_path / "other/component"
    nested.mkdir(parents=True)
    (nested / "record.py").write_text("import cv2; cv2.imwrite(path, pixels)")
    assert "other/component/record.py:1" in scan(tmp_path)[0]


@pytest.mark.parametrize("suffix", [".cjs", ".mjs", ".cts", ".mts"])
def test_scan_module_extensions(tmp_path, suffix):
    (tmp_path / ("record" + suffix)).write_text("fs.writeFileSync('frame.png', pixels)", encoding="utf-8")
    assert scan(tmp_path)


def test_repository_has_no_image_or_video_writers():
    assert scan(Path(__file__).resolve().parents[2]) == []
