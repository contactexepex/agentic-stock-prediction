"""Build design/system/styleguide.html from styleguide.template.html with the system inlined."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from system import inline_system
HERE = Path(__file__).resolve().parent
html = inline_system((HERE / "styleguide.template.html").read_text())
(HERE / "styleguide.html").write_text(html)
print("styleguide.html", len(html), "bytes")
