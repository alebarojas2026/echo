"""Host entry point for the teacher's numeric deployment checks.

On the host the layout's area comes from radio/nodes.json unless TEACHER_AREA or --area is given.
"""

import json
import os

from teacher.applab.python.preflight import main
from teacher.calibrate import NODES, area_from_nodes, area_text

if __name__ == "__main__":
    os.environ.setdefault("TEACHER_AREA", area_text(area_from_nodes(json.loads(NODES.read_text(encoding="utf-8")))[0]))
    main()
